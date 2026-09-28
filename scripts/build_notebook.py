"""Build an importable, self-contained Fabric notebook from the tested source."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "notebooks" / "FonterraSalesEmulator.ipynb"


def cell(kind, cell_id, source, *, parameters=False):
    result = {
        "cell_type": kind, "id": cell_id, "metadata": {},
        "source": [line + "\n" for line in source.strip().splitlines()],
    }
    if kind == "code":
        result.update({"execution_count": None, "outputs": []})
        result["metadata"]["microsoft"] = {"language": "python"}
    if parameters:
        result["metadata"]["tags"] = ["parameters"]
    return result


def build_notebook():
    cells = [
        cell("markdown", "intro", """
# Fonterra real-time orders, dispatch and sales

**Connected streaming demo | Workspace: `rayfin-3d-production-factory` | Synthetic data only**

Inspired by the [Fabric Retail Sales Jumpstart](https://jumpstart.fabric.microsoft.com/catalog/retail-sales/).
This is an original, standalone generator, not a connection to Fonterra's systems.
**Run all** publishes a bounded live simulation to **FonterraSalesStream**, source **FonterraSalesSource**,
then stores the complete JSON events in **FonterraSales** / **FonterraSalesRaw** in **FonterraEventhouse**.
The notebook resolves the custom endpoint credentials at runtime using your Fabric identity; no keys are embedded.
Set `MODE = "preview"` to inspect synthetic data without publishing.
Running in Fabric still starts a billable notebook session. Stop the session when finished.

**Important portfolio correction (as of 12 September 2026):**
Fonterra [completed the Mainland Group sale to Lactalis on 31 March 2026](https://www.fonterra.com/nz/en/our-stories/media/fonterra-completes-sale-of-mainland-group-to-lactalis.html).
The current [corporate brand list](https://www.fonterra.com/nz/en/our-co-operative/our-brands.html) is Anchor Food Professionals,
NZMP, Nutiani and Farm Source; Anchor consumer ownership is retained in Greater China.
The notebook includes all names in that corporate list and the 12-brand
[successor consumer directory](https://www.mainlanddairy.com/en/brands.html), with separate ownership scopes.
NZ supermarket orders are **on by default** and include explicitly labelled NZ divested-consumer comparison scopes.
Other former consumer markets remain off unless the broader comparison parameter is enabled.
Farm Source is listed but excluded from dairy transactions because it provides farmer services.

This is not an exhaustive trademark/SKU register. Sub-brands, licensed territories and regional offerings need
business validation. Historical Australian Dairies and Duck River, and unverified De Winkel, are not included in
the active catalogue. Generic dairy-assortment placeholders are used where precise current products are unverified.
All packs, prices, FX, routes, customers and quantities are invented. Geographic points identify cities,
not Fonterra facilities. Categories and pack sizes are demonstration choices, not an official product catalogue.
"""),
        cell("markdown", "bootstrap-title", """
## 1. Streaming library bootstrap

Fabric includes `semantic-link-sempy` for authenticated REST access. The native `%pip` bootstrap ensures
the Event Hubs SDK and WebSocket transport dependency are available; Fabric restarts Python after inline
library changes, before parameters are defined.
This setup cell can contact PyPI even when the later simulation mode is preview.
For a notebook job, pass `_inlineInstallationEnabled = True` while this setup cell is present.
For production schedules, prefer a pinned Fabric Environment dependency over session-scoped installs.
"""),
        cell("code", "sdk-bootstrap", """
%pip install --quiet 'azure-eventhub>=5.11.5,<6' 'websocket-client>=1.8,<2'
"""),
        cell("markdown", "instructions", """
## 2. Parameters

The default `MODE = "eventstream"` sends to the configured custom endpoint using wall-clock pacing.
Switch to `MODE = "preview"` for a **virtual-clock** run that finishes quickly, showing
the same lifecycle logic as live mode without sending data. Preview timestamps can be in the future.
`CONNECTION_MODE = "fabric"` discovers workspace/Eventstream/source IDs by exact name and retrieves credentials
with the current notebook identity. That identity needs **read and write** access to the Eventstream.
Explicit `key_vault` and `environment` modes remain available; lookup failures never silently switch credential sources.

Each incoming customer order follows **ORDER_RECEIVED -> ORDER_DISPATCHED -> ORDER_DELIVERED -> SALE_COMPLETED**,
or **ORDER_RECEIVED -> ORDER_CANCELLED**. Dispatch/delivery delays are compressed demo seconds, not real lead times.
"Order in" means incoming customer orders, not supplier purchase orders or goods receipts.
One sale closes one full order; this is not a real inventory/ERP model, split-shipment model, or separate POS sell-through feed.

`MAX_ORDERS` caps order arrivals; normal completion drains their lifecycle events.
The duration limit stops even if orders are unfinished and reports them explicitly.
`ORDERS_PER_SECOND` controls arrivals, not total events (up to four events per completed order).
The pending-order cap applies backpressure; it never silently drops an order.
A seed reproduces values with the same start time/run ID; each notebook run gets a new run ID to avoid duplicate identities.
"""),
        cell("code", "parameters", """
MODE = "eventstream"
CONNECTION_MODE = "fabric"
WORKSPACE_NAME = "rayfin-3d-production-factory"
EVENTSTREAM_NAME = "FonterraSalesStream"
EVENTSTREAM_SOURCE_NAME = "FonterraSalesSource"
SIMULATION_RUN_ID = ""  # Empty generates a fresh UUID; set a new UUID to correlate a smoke run.
INCLUDE_DIVESTED_BRANDS = False
INCLUDE_NZ_SUPERMARKET_ORDERS = True
MAX_ORDERS = 60
MAX_DURATION_SECONDS = 120.0
ORDERS_PER_SECOND = 1.0
MAX_PENDING_ORDERS = 100
SEED = 42
CANCELLATION_PROBABILITY = 0.05
LATE_DELIVERY_PROBABILITY = 0.15
DISPATCH_DELAY_SECONDS = 5.0
DELIVERY_DELAY_SECONDS = 10.0
SALE_DELAY_SECONDS = 2.0

# Optional override when CONNECTION_MODE = "key_vault".
KEY_VAULT_URL = ""
KEY_VAULT_SECRET_NAME = ""
""", parameters=True),
        cell("markdown", "dependencies", """
## 3. Reusable generator

The core simulator uses only Python's standard library and does not require a lakehouse.
The library bootstrap above makes the publisher ready for **Run all** in Fabric.
The following four cells are embedded source: no repository checkout or external `.py` files are needed.
"""),
    ]
    source = (ROOT / "src" / "fonterra_simulator.py").read_text(encoding="utf-8")
    sections = source.split("# %% ")[1:]
    for index, section in enumerate(sections, 1):
        title, _, code = section.partition("\n")
        cells.append(cell("code", f"generator-{index}", f"# {title}\n{code}"))
    cells.extend([
        cell("markdown", "catalog-title", """
## 4. Inspect the catalogue before running

Current-mode transactions: Anchor Food Professionals (Singapore foodservice), NZMP (ingredients),
Nutiani (B2B nutrition), Anchor (Greater China consumer).
`INCLUDE_NZ_SUPERMARKET_ORDERS = True` also enables the NZ comparison catalogue: Anchor (NZ),
Mainland, Kapiti, Chesdale and Fresh 'n Fruity. These remain labelled `DivestedComparison`.
Comparison mode adds former consumer scopes for Anchor, Anlene, Anmum, Mainland, Perfect Italiano, Kapiti,
Western Star, Bega (licensed), Chesdale, Fernleaf, Fresh 'n Fruity and Ratthi.

The first product in each order rotates through every enabled brand/category, rather than relying on
random coverage. Set `MAX_ORDERS >= len(enabled_products)` and allow enough time to exercise the full list.
Orders never mix brands, ownership scopes or currencies. Additional random lines stay in the same scope.
"""),
        cell("code", "catalog-preview", """
enabled_products = build_products(INCLUDE_DIVESTED_BRANDS, INCLUDE_NZ_SUPERMARKET_ORDERS)
enabled_scopes = {product["BrandScopeId"] for product in enabled_products}
print(f"Catalogue as of {CATALOG_AS_OF}: {len(BRANDS)} ownership scopes; {len(enabled_products)} enabled demo products")
for row in catalog_rows():
    enabled = row["ScopeId"] in enabled_scopes
    print(f"{'ON ' if enabled else 'OFF'} | {row['ScopeId']:8} | {row['Brand']:26} | {row['Status']} | {row['Categories']}")
"""),
        cell("markdown", "run-title", """
## 5. Generate events

Preview displays a summary plus two complete JSON messages. It makes no network calls.
Live mode sends one JSON order snapshot per Event Hub message, partitioned by `OrderKey`.
SDK retries reuse the same `EventId`; **at-least-once delivery means Eventhouse must deduplicate**.
Network failures stop the run rather than pretending delivery succeeded. After a failure, delivery of the last
event may be uncertain. There is no durable producer checkpoint or automatic resume.

**Stop:** interrupt this cell if needed, then use Fabric's **Stop session** control to release compute.
The producer closes on interruption. A synchronous network operation may take up to its timeout/retry budget to return.
The final statistics report generated events, acknowledged sends and unfinished orders.
"""),
        cell("code", "run", """
if MODE not in ("preview", "eventstream"):
    raise ValueError("MODE must be 'preview' or 'eventstream'.")

config = SimulationConfig(
    max_orders=MAX_ORDERS, max_duration_seconds=MAX_DURATION_SECONDS,
    orders_per_second=ORDERS_PER_SECOND, max_pending_orders=MAX_PENDING_ORDERS,
    seed=SEED, include_divested_brands=INCLUDE_DIVESTED_BRANDS,
    include_nz_supermarket_orders=INCLUDE_NZ_SUPERMARKET_ORDERS,
    cancellation_probability=CANCELLATION_PROBABILITY,
    late_delivery_probability=LATE_DELIVERY_PROBABILITY,
    dispatch_delay_seconds=DISPATCH_DELAY_SECONDS,
    delivery_delay_seconds=DELIVERY_DELAY_SECONDS, sale_delay_seconds=SALE_DELAY_SECONDS,
)
config.validate()

if MODE == "preview":
    simulation = SalesSimulation(config, run_id=SIMULATION_RUN_ID or None)
    samples = []
    observed_scopes = set()
    observed_products = set()
    for event in simulation.events():
        if len(samples) < 2:
            samples.append(event)
        if event["EventType"] == "ORDER_RECEIVED":
            observed_scopes.add(event["BrandScopeId"])
            observed_products.update(line["ProductCode"] for line in event["lines"])
    print(json.dumps(simulation.stats, indent=2))
    print(f"Observed {len(observed_scopes)} brand scopes and {len(observed_products)}/{len(enabled_products)} products.")
    if len(observed_products) != len(enabled_products):
        print("Catalogue coverage incomplete: increase MAX_ORDERS or duration, or lower the pending-order constraint.")
    print(json.dumps(samples, indent=2, allow_nan=False))
else:
    if CONNECTION_MODE == "fabric":
        connection_string = resolve_eventstream_connection(
            WORKSPACE_NAME, EVENTSTREAM_NAME, EVENTSTREAM_SOURCE_NAME)
    elif CONNECTION_MODE == "key_vault":
        if not KEY_VAULT_URL or not KEY_VAULT_SECRET_NAME:
            raise ValueError("key_vault mode requires KEY_VAULT_URL and KEY_VAULT_SECRET_NAME.")
        connection_string = load_eventstream_connection(KEY_VAULT_URL, KEY_VAULT_SECRET_NAME)
    elif CONNECTION_MODE == "environment":
        connection_string = load_eventstream_connection()
    else:
        raise ValueError("CONNECTION_MODE must be 'fabric', 'key_vault', or 'environment'.")
    try:
        print(f"Publishing bounded live simulation to {EVENTSTREAM_NAME} / {EVENTSTREAM_SOURCE_NAME}.")
        stream_to_eventstream(config, connection_string, run_id=SIMULATION_RUN_ID or None)
    finally:
        del connection_string
"""),
        cell("markdown", "contract", """
## 6. Event contract and aggregation rules

| Fields | Meaning |
|---|---|
| `SchemaVersion`, `IsSynthetic`, `CatalogAsOf`, `ClockMode` | Provenance, synthetic flag and virtual/realtime clock |
| `EventId`, `SimulationRunId`, `EventSequence`, `EventType`, `EventTime` | Unique lifecycle event, run ID, per-order sequence, UTC ISO event time |
| `OrderKey`, `OrderDate`, `ExpectedDeliveryDate`, `DispatchDate`, `DeliveryDate` | Correlation and Unix-second dates; actual dispatch/delivery stay null until those events |
| `BrandScopeId`, `Brand`, `PortfolioStatus`, `Channel` | Ownership-aware slicing; **brand name alone is not an ownership key** |
| `Country`, `City`, `Latitude`, `Longitude`, `WarehouseId`, `CustomerKey`, `StoreKey` | Invented routing and identifiers, city-level mapping |
| `DestinationId`, `DestinationName`, `DestinationType`, `DestinationCountryCode` | Explicit delivery destination; simulated outlet IDs/names |
| `DestinationCity`, `DestinationRegion`, `DestinationLatitude`, `DestinationLongitude`, `SupermarketChain` | NZ locality and chain; coordinates are city centres, not actual branches |
| `IsNZSupermarketDelivery` | True from order receipt when the planned destination is an NZ supermarket |
| `IsDispatchedToNZSupermarket` | False at receipt/cancellation; true from dispatch onwards for an NZ supermarket order |
| `CurrencyCode`, `ExchangeRate`, `ReportingCurrencyCode` | Local currency, fixed synthetic NZD/local rate, NZD reporting |
| `OrderNetAmount`, `OrderNetAmountNZD` | Snapshot amounts, repeated on lifecycle events; **do not sum across event types** |
| `SalesAmount`, `SalesAmountNZD` | Zero except on `SALE_COMPLETED`; demonstration revenue, tax excluded |
| `lines[]` | Product key/code/name, brand/category, hypothetical pack, quantity, batch, storage condition, source URLs |
| `lines.UnitPrice`, `lines.NetPrice`, `lines.UnitCost` | Per-selling-unit list price, discounted price and invented cost |
| `lines.LineNetAmount`, `lines.LineNetAmountNZD` | Quantity times discounted unit price, and rounded reporting amount |
| `lines.OrderedQuantityDelta`, `lines.DispatchedQuantityDelta`, `lines.SoldQuantityDelta` | Stage-specific quantity increments; never sum unlike selling units as physical volume |
| `IsLate`, `CancellationReason` | Simulated late delivery and customer cancellation scenarios |

Money is calculated with integer cents/Decimal rounding, then serialized as JSON numbers.
Use decimal types downstream. Convert each line to NZD and round before summing; FX is not live.
Keep `ExchangeRate` as a decimal/real, **not** the Jumpstart's `tolong()` (which truncates fractional rates).

**Prevent double counting:** first deduplicate by `EventId`, then filter sales or expand lines.
Order-level `SalesAmount` is not additive after `mv-expand lines`; sum `lines.SalesAmount` instead.
For current order status use the highest `EventSequence` per `OrderKey`.
When comparing scopes, retain `PortfolioStatus` and `BrandScopeId` in grouping/filtering.
Do not mix local-currency revenue; group by `CurrencyCode` or use `SalesAmountNZD`.

This is an extended schema, **not a drop-in replacement for the original SalesRaw mapping/dashboard**.
Its nested-line shape and core `OrderKey`/`OrderDate`/`DeliveryDate`/`CustomerKey`/`StoreKey` fields are familiar,
but the later Eventhouse schema and transformations must include lifecycle and provenance fields.
"""),
        cell("markdown", "next-steps", """
## 7. New Zealand supermarket dispatch

Schema **1.1** adds destination fields to orders and their typed KQL event/line tables.
Examples use New World, PAK'nSAVE, Woolworths, Four Square, FreshChoice and SuperValue labels,
with **invented demo outlets** in Auckland, Wellington, Christchurch, Hamilton, Tauranga and Dunedin.
These are not real branches, customer relationships, live stock or verified supply contracts.
Supermarket replenishment quantities are illustrative 12-120 selling units per line, not consumer POS baskets.
Other markets keep their existing routes; ingredient/foodservice orders are not relabelled as supermarket orders.

Filter `EventType == "ORDER_DISPATCHED"` to count dispatch events, rather than counting
the flag again on delivered and sold snapshots. Existing schema-1.0 history has no supermarket
destination information and remains unknown; it is not retroactively assigned to invented outlets.

```kql
FonterraOrderLinesUnique
| where EventTime > ago(1d)
| where EventType == "ORDER_DISPATCHED" and IsDispatchedToNZSupermarket == true
| summarize UnitsDispatched=sum(DispatchedQuantityDelta)
    by SupermarketChain, DestinationName, DestinationCity, DestinationRegion,
       ProductCode, QuantityUnit, PackSize, PortfolioStatus
```

## 8. Check the connected pipeline

**FonterraSalesEmulator -> FonterraSalesStream / FonterraSalesSource -> FonterraEventhouse /
FonterraSales / FonterraSalesRaw**

The destination maps the entire incoming JSON object into `Payload:dynamic`, preserving nested lines and
every lifecycle field. After running the notebook, open the **FonterraSales** KQL database and run:

```kql
FonterraSalesRaw
| where todatetime(Payload.EventTime) > ago(1h)
| extend EventId = tostring(Payload.EventId), EventTime = todatetime(Payload.EventTime)
| summarize arg_max(EventTime, *) by EventId
| summarize Events = count() by EventType = tostring(Payload.EventType)
```

Filter `tostring(Payload.SimulationRunId)` to the run ID printed by this notebook to isolate one run.
This verifies arrival without double-counting retries. For sales, filter `SALE_COMPLETED`, then expand lines
and sum line-level revenue. The stored raw envelope is retained; no fields are discarded.
Do not reuse the original POS-only revenue query unmodified.

The `fabric` connection mode retrieves the current source key each run; it requires no manually copied
connection string or Key Vault. Use `key_vault` or `environment` only for an explicit override.
Never paste credentials into cells/outputs. The [source-connection API](https://learn.microsoft.com/en-us/rest/api/fabric/eventstream/topology/get-eventstream-source-connection)
requires Eventstream read/write permissions.

Live transport uses AMQP-over-WebSockets (HTTPS/443), synchronous acknowledgements and bounded SDK retries.
This notebook is a demonstration producer, not a 24/7 ingestion service. A real deployment requires actual
POS/ERP/order sources, approved product and territory master data, durable checkpoints/outbox,
stock/reservation logic, operational monitoring and reconciled commercial/accounting semantics.

### Source notes

- [Current corporate brands](https://www.fonterra.com/nz/en/our-co-operative/our-brands.html)
- [Mainland sale completed, 31 March 2026](https://www.fonterra.com/nz/en/our-stories/media/fonterra-completes-sale-of-mainland-group-to-lactalis.html)
- [Successor consumer brand directory](https://www.mainlanddairy.com/en/brands.html)
- [AFP product categories and regional operator split](https://www.anchorfoodprofessionals.com/global/en.html)
- [NZMP ingredient categories](https://www.nzmp.com/global/en.html)
- [Nutiani B2B nutrition](https://www.nutiani.com/nz/en.html)
- [Bega licensing/divestment update, 26 August 2025](https://www.fonterra.com/nz/en/our-stories/media/update-on-divestment-of-consumer-and-associated-businesses.html)
- [Historical Australian portfolio](https://www.fonterra.com/au/en/about-us/our-brands.html)

These sources evidence brands and broad categories, not the invented products/prices in this notebook.
"""),
    ])
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Synapse PySpark", "language": "python", "name": "synapse_pyspark"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_notebook(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Built {OUTPUT.name}")
