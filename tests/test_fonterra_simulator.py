import contextlib
import io
import json
import unittest
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.build_notebook import build_notebook
from src.fonterra_simulator import (
    BRANDS, NZ_SUPERMARKET_CHAINS, NZ_DESTINATION_CITIES,
    SalesSimulation, SimulationConfig, build_products, cents,
    load_eventstream_connection, publish_event, validate_event,
)


START = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
RUN_ID = "eca3d393-082f-42a5-b4e1-99a9a69b9be3"
CONNECTION = "Endpoint=sb://example.servicebus.windows.net/;SharedAccessKeyName=Send;SharedAccessKey=fake==;EntityPath=events"


def simulate(config=None):
    sim = SalesSimulation(config or SimulationConfig(), start_time=START, run_id=RUN_ID)
    return sim, list(sim.events())


class CatalogTests(unittest.TestCase):
    def test_all_evidenced_brands_and_scopes(self):
        self.assertEqual(len(BRANDS), 17)
        current = {p["Brand"] for p in build_products()}
        self.assertEqual(current, {"Anchor", "Anchor Food Professionals", "NZMP", "Nutiani"})
        comparison = {b.name for b in BRANDS if b.portfolio_status != "CurrentFonterra"}
        self.assertEqual(comparison, {
            "Anchor", "Anlene", "Anmum", "Mainland", "Perfect Italiano", "Kapiti",
            "Western Star", "Bega", "Chesdale", "Fernleaf", "Fresh 'n Fruity", "Ratthi",
        })
        farm = next(b for b in BRANDS if b.name == "Farm Source")
        self.assertFalse(farm.event_eligible)

    def test_comparison_opt_in_and_stable_product_keys(self):
        current = build_products()
        all_products = build_products(True)
        self.assertTrue(all(p["PortfolioStatus"] == "CurrentFonterra" for p in current))
        self.assertEqual(current, [p for p in all_products if p["PortfolioStatus"] == "CurrentFonterra"])
        self.assertEqual(len({p["ProductKey"] for p in all_products}), len(all_products))
        self.assertEqual(len({p["ProductCode"] for p in all_products}), len(all_products))
        self.assertTrue(all(p["BrandSourceUrls"] for p in all_products))
        with self.assertRaises(ValueError):
            build_products("false")

    def test_every_brand_category_generates_orders(self):
        for comparison in (False, True):
            with self.subTest(comparison=comparison):
                products = build_products(comparison)
                config = SimulationConfig(max_orders=len(products), include_divested_brands=comparison,
                                          cancellation_probability=0)
                sim, events = simulate(config)
                observed = {line["ProductKey"] for e in events if e["EventType"] == "ORDER_RECEIVED"
                            for line in e["lines"]}
                self.assertEqual(observed, {p["ProductKey"] for p in products})
                self.assertEqual(sim.stats["unfinished_orders"], 0)

    def test_nz_gate_only_adds_nz_consumer_comparisons(self):
        products = build_products(include_nz_supermarket_orders=True)
        self.assertEqual(len(products), 23)
        comparisons = [p for p in products if p["PortfolioStatus"] != "CurrentFonterra"]
        self.assertEqual(len(comparisons), 7)
        self.assertEqual({p["BrandScopeId"] for p in comparisons}, {"ANC-LEG", "MAIN", "KAP", "CHES", "FF"})
        self.assertTrue(all(p["MarketCode"] == "NZ" and p["Channel"] == "Retail" for p in comparisons))
        self.assertEqual(build_products(True, True), build_products(True))
        with self.assertRaises(ValueError):
            build_products(include_nz_supermarket_orders="True")


class DestinationTests(unittest.TestCase):
    def test_destinations_are_consistent_and_dispatch_flags_follow_actual_dispatch(self):
        config = SimulationConfig(max_orders=92, max_duration_seconds=90, orders_per_second=4,
                                  include_nz_supermarket_orders=True,
                                  cancellation_probability=0, late_delivery_probability=0)
        sim, events = simulate(config)
        self.assertEqual(sim.stats["unfinished_orders"], 0)
        nz = [e for e in events if e["IsNZSupermarketDelivery"]]
        self.assertTrue(nz)
        self.assertEqual({e["SupermarketChain"] for e in nz}, set(NZ_SUPERMARKET_CHAINS))
        self.assertEqual({e["DestinationCity"] for e in nz}, {c[0] for c in NZ_DESTINATION_CITIES})
        locations, orders = {}, defaultdict(list)
        for event in events:
            self.assertEqual(event["SchemaVersion"], "1.1")
            self.assertEqual(event["DestinationCountryCode"], event["MarketCode"])
            for field in ("City", "Latitude", "Longitude"):
                self.assertEqual(event[field], event["Destination" + field])
            self.assertEqual(event["StoreName"], event["DestinationName"])
            self.assertEqual(event["IsDispatchedToNZSupermarket"],
                             event["IsNZSupermarketDelivery"] and event["DispatchDate"] is not None)
            orders[event["OrderKey"]].append(event)
            if event["IsNZSupermarketDelivery"]:
                self.assertEqual(event["PortfolioStatus"], "DivestedComparison")
                self.assertEqual(event["DestinationType"], "Supermarket")
                self.assertEqual(event["CurrencyCode"], "NZD")
                self.assertTrue(event["DestinationName"].startswith("SIM - "))
                self.assertTrue(all(12 <= line["Quantity"] <= 120 for line in event["lines"]))
                identity = (event["StoreKey"], event["DestinationName"], event["DestinationRegion"])
                self.assertEqual(locations.setdefault(event["DestinationId"], identity), identity)
            else:
                self.assertEqual(event["SupermarketChain"], "")
                self.assertFalse(event["IsDispatchedToNZSupermarket"])
        for snapshots in orders.values():
            self.assertEqual(len({e["DestinationId"] for e in snapshots}), 1)
            if snapshots[0]["IsNZSupermarketDelivery"]:
                self.assertEqual([e["IsDispatchedToNZSupermarket"] for e in snapshots], [False, True, True, True])

    def test_cancelled_nz_orders_are_never_dispatched(self):
        _, events = simulate(SimulationConfig(include_nz_supermarket_orders=True, cancellation_probability=1))
        nz = [e for e in events if e["IsNZSupermarketDelivery"]]
        self.assertTrue(nz)
        self.assertTrue(all(e["DispatchDate"] is None and not e["IsDispatchedToNZSupermarket"] for e in nz))
        self.assertEqual({e["EventType"] for e in nz}, {"ORDER_RECEIVED", "ORDER_CANCELLED"})

    def test_incorrect_destination_flags_are_rejected(self):
        _, events = simulate(SimulationConfig(include_nz_supermarket_orders=True, cancellation_probability=0))
        receipt = next(e for e in events if e["IsNZSupermarketDelivery"] and e["EventType"] == "ORDER_RECEIVED")
        for changed in ({"IsDispatchedToNZSupermarket": True}, {"IsNZSupermarketDelivery": False},
                        {"SupermarketChain": ""}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_event({**receipt, **changed})


class LifecycleTests(unittest.TestCase):
    def test_lifecycle_dates_money_and_ids(self):
        config = SimulationConfig(include_divested_brands=True, cancellation_probability=0,
                                  late_delivery_probability=0)
        sim, events = simulate(config)
        grouped = defaultdict(list)
        self.assertEqual(len(events), config.max_orders * 4)
        self.assertEqual(len({e["EventId"] for e in events}), len(events))
        self.assertEqual([e["EventTime"] for e in events], sorted(e["EventTime"] for e in events))
        for event in events:
            validate_event(event)
            self.assertEqual(json.loads(json.dumps(event, allow_nan=False)), event)
            grouped[event["OrderKey"]].append(event)
        for order in grouped.values():
            self.assertEqual([e["EventSequence"] for e in order], [1, 2, 3, 4])
            self.assertEqual([e["EventType"] for e in order],
                             ["ORDER_RECEIVED", "ORDER_DISPATCHED", "ORDER_DELIVERED", "SALE_COMPLETED"])
            self.assertIsNone(order[0]["DispatchDate"])
            self.assertIsNone(order[0]["DeliveryDate"])
            self.assertIsNone(order[1]["DeliveryDate"])
            self.assertLessEqual(order[0]["OrderDate"], order[1]["DispatchDate"])
            self.assertLessEqual(order[1]["DispatchDate"], order[2]["DeliveryDate"])
            self.assertFalse(order[2]["IsLate"])
            self.assertEqual(order[3]["SalesAmount"], order[0]["OrderNetAmount"])
            self.assertEqual(sum(cents(e["SalesAmount"]) for e in order), cents(order[0]["OrderNetAmount"]))
            self.assertEqual(sum(e["OrderCountDelta"] for e in order), 1)
            for event in order:
                self.assertEqual(event["OrderNetAmount"], order[0]["OrderNetAmount"])
                self.assertEqual(event["PortfolioStatus"], order[0]["PortfolioStatus"])
                self.assertEqual(event["OrderNetAmountNZD"],
                                 sum(cents(line["LineNetAmountNZD"]) for line in event["lines"]) / 100)
                for i, line in enumerate(event["lines"]):
                    self.assertEqual(line["Quantity"], order[0]["lines"][i]["Quantity"])
                    self.assertEqual(line["UnitPrice"], order[0]["lines"][i]["UnitPrice"])
                    self.assertLessEqual(line["UnitCost"], line["NetPrice"])
                    self.assertLessEqual(line["NetPrice"], line["UnitPrice"])
                    for kind, field in (
                        ("ORDER_RECEIVED", "OrderedQuantityDelta"),
                        ("ORDER_DISPATCHED", "DispatchedQuantityDelta"),
                        ("SALE_COMPLETED", "SoldQuantityDelta"),
                    ):
                        self.assertEqual(line[field], line["Quantity"] if event["EventType"] == kind else 0)
        self.assertEqual(sim.stats["stop_reason"], "completed")

    def test_cancellations_never_dispatch_or_sell(self):
        sim, events = simulate(SimulationConfig(cancellation_probability=1))
        self.assertEqual({e["EventType"] for e in events}, {"ORDER_RECEIVED", "ORDER_CANCELLED"})
        self.assertTrue(all(e["SalesAmount"] == 0 for e in events))
        self.assertTrue(all(e["DispatchDate"] is None for e in events))
        self.assertEqual(sim.stats["event_counts"]["ORDER_CANCELLED"], 60)

    def test_late_delivery_and_currency_fraction(self):
        _, events = simulate(SimulationConfig(cancellation_probability=0, late_delivery_probability=1,
                                             include_divested_brands=True))
        delivered = [e for e in events if e["EventType"] == "ORDER_DELIVERED"]
        self.assertTrue(all(e["IsLate"] for e in delivered))
        self.assertTrue(all(e["DeliveryDate"] > e["ExpectedDeliveryDate"] for e in delivered))
        self.assertTrue(any(e["ExchangeRate"] < 1 for e in events))

    def test_determinism_and_rerun_identity(self):
        _, first = simulate()
        _, second = simulate()
        self.assertEqual(first, second)
        new_run = SalesSimulation(SimulationConfig(), start_time=START)
        self.assertNotEqual(next(new_run.events())["EventId"], first[0]["EventId"])

    def test_duration_limit_reports_open_orders(self):
        sim, events = simulate(SimulationConfig(max_duration_seconds=3))
        self.assertEqual(sim.stats["stop_reason"], "duration_limit")
        self.assertGreater(sim.stats["unfinished_orders"], 0)
        self.assertTrue(all(e["EventType"] == "ORDER_RECEIVED" for e in events))

    def test_backpressure_bounds_state_and_drains(self):
        sim, events = simulate(SimulationConfig(max_orders=10, max_pending_orders=1,
                                              max_duration_seconds=500, cancellation_probability=0))
        self.assertEqual(sim.stats["peak_pending_orders"], 1)
        self.assertEqual(sim.stats["unfinished_orders"], 0)
        self.assertEqual(len(events), 40)

    def test_realtime_pacing_and_cutoff_with_fake_clock(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            self.assertGreater(seconds, 0)
            sleeps.append(seconds)
            now[0] += seconds

        sim = SalesSimulation(SimulationConfig(max_orders=2, cancellation_probability=0,
                                              late_delivery_probability=0),
                              start_time=START, run_id=RUN_ID)
        events = list(sim.events(realtime=True, clock=lambda: now[0], sleeper=sleep))
        self.assertEqual(len(events), 8)
        self.assertTrue(sleeps)
        self.assertTrue(all(e["ClockMode"] == "Realtime" for e in events))
        self.assertGreaterEqual(now[0], 18)
        self.assertLess(now[0], 19)

        now[0] = 0
        sim = SalesSimulation(SimulationConfig(max_duration_seconds=0.25))
        events = list(sim.events(realtime=True, clock=lambda: now[0], sleeper=sleep))
        self.assertEqual(len(events), 1)
        self.assertEqual(sim.stats["stop_reason"], "duration_limit")
        self.assertAlmostEqual(now[0], 0.25)

    def test_close_and_double_run(self):
        sim = SalesSimulation(SimulationConfig())
        events = sim.events()
        next(events)
        events.close()
        self.assertEqual(sim.stats["unfinished_orders"], 1)
        self.assertEqual(sim.stats["stop_reason"], "interrupted_or_consumer_stopped")
        with self.assertRaises(RuntimeError):
            list(sim.events())

    def test_invalid_parameters_and_naive_time(self):
        invalid = {
            "max_orders": [0, -1, 1.5, True], "max_pending_orders": [0, -1],
            "max_duration_seconds": [0, float("inf"), float("nan"), True],
            "orders_per_second": [0, -1, "10"], "dispatch_delay_seconds": [0],
            "delivery_delay_seconds": [-1], "sale_delay_seconds": [float("nan")],
            "cancellation_probability": [-0.1, 1.1, float("nan")],
            "late_delivery_probability": [2, True], "include_divested_brands": ["False"],
            "include_nz_supermarket_orders": ["False", 1, None],
            "seed": [1.2],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    SalesSimulation(replace(SimulationConfig(), **{name: value}))
        with self.assertRaises(ValueError):
            SalesSimulation(SimulationConfig(), start_time=datetime(2026, 1, 1))


class PublisherTests(unittest.TestCase):
    def test_secret_sources_fail_closed(self):
        self.assertEqual(load_eventstream_connection(environment={
            "FONTERRA_EVENTSTREAM_CONNECTION_STRING": CONNECTION}), CONNECTION)
        calls = []

        def get_secret(url, name):
            calls.append((url, name))
            return CONNECTION

        self.assertEqual(load_eventstream_connection("https://demo.vault.azure.net/", "sender",
                                                    secret_getter=get_secret), CONNECTION)
        self.assertEqual(calls, [("https://demo.vault.azure.net/", "sender")])
        for connection in ("", "bad", CONNECTION.replace(";EntityPath=events", "")):
            with self.assertRaises(ValueError) as error:
                load_eventstream_connection(environment={"FONTERRA_EVENTSTREAM_CONNECTION_STRING": connection})
            self.assertNotIn("fake==", str(error.exception))
        for vault in ("http://demo.vault.azure.net", "https://example.com",
                      "https://demo.vault.azure.net/secret", "https://user@demo.vault.azure.net"):
            with self.assertRaises(ValueError):
                load_eventstream_connection(vault, "sender", secret_getter=get_secret)

    def test_message_shape_partition_key_and_send_failure(self):
        class EventData:
            def __init__(self, body):
                self.body = body

        class Batch:
            def __init__(self):
                self.items = []

            def add(self, item):
                self.items.append(item)

        class Producer:
            def create_batch(self, *, partition_key):
                self.partition_key = partition_key
                return Batch()

            def send_batch(self, batch, *, timeout):
                self.batch = batch
                self.timeout = timeout

        sim = SalesSimulation(SimulationConfig(max_orders=1))
        event = next(sim.events(realtime=True, clock=lambda: 0))
        producer = Producer()
        publish_event(producer, event, event_data_class=EventData)
        self.assertEqual(producer.partition_key, event["OrderKey"])
        self.assertEqual(producer.timeout, 30)
        self.assertEqual(len(producer.batch.items), 1)
        message = producer.batch.items[0]
        self.assertEqual(message.message_id, event["EventId"])
        self.assertEqual(message.content_type, "application/json")
        self.assertEqual(json.loads(message.body), event)
        with patch.object(producer, "send_batch", side_effect=TimeoutError("failed")):
            with self.assertRaises(TimeoutError):
                publish_event(producer, event, event_data_class=EventData)
        _, preview = simulate(SimulationConfig(max_orders=1))
        with self.assertRaises(ValueError):
            publish_event(producer, preview[0], event_data_class=EventData)


class NotebookTests(unittest.TestCase):
    def test_persisted_notebook_matches_source_and_executes_without_network(self):
        path = Path(__file__).resolve().parents[1] / "notebooks" / "FonterraSalesEmulator.ipynb"
        notebook = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(notebook, build_notebook())
        self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "synapse_pyspark")
        namespace = {"__name__": "__main__"}
        with contextlib.redirect_stdout(io.StringIO()), \
                patch("socket.socket", side_effect=AssertionError("Network forbidden")):
            for cell in notebook["cells"]:
                self.assertTrue(all(line.endswith("\n") for line in cell["source"]))
                if cell["cell_type"] == "code":
                    self.assertEqual(cell["outputs"], [])
                    self.assertIsNone(cell["execution_count"])
                    if cell["id"] == "sdk-bootstrap":
                        self.assertTrue("".join(cell["source"]).startswith("%pip install"))
                        continue  # Fabric executes this native magic; local tests use the installed SDK.
                    exec(compile("".join(cell["source"]), cell["id"], "exec"), namespace)
                    if cell["id"] == "parameters":
                        self.assertEqual(namespace["MODE"], "eventstream")
                        self.assertEqual(namespace["CONNECTION_MODE"], "fabric")
                        namespace["MODE"] = "preview"
        self.assertEqual(namespace["simulation"].stats["stop_reason"], "completed")
        self.assertEqual(namespace["simulation"].stats["unfinished_orders"], 0)
        self.assertEqual(len(namespace["observed_products"]), len(namespace["enabled_products"]))


if __name__ == "__main__":
    unittest.main()
