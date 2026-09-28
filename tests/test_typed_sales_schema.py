import unittest
from pathlib import Path

from scripts.deploy_typed_sales import (
    assert_policy, assert_schema, assert_upgrade_schema, assert_upgrade_function, legacy_manifest,
)
from scripts.typed_sales_schema import (
    EVENT_FIELDS, LINE_FIELDS, TABLES, TRANSFORMS, VIEWS, EVENT_TABLE, LINE_TABLE,
    DESTINATION_FIELDS, FUNCTIONS, OWNER, backfill_query, cast, render, update_policy, view_command,
)
from src.fonterra_simulator import SalesSimulation, SimulationConfig


class TypedSchemaTests(unittest.TestCase):
    def test_every_business_payload_field_has_a_typed_column(self):
        event = next(SalesSimulation(SimulationConfig(max_orders=1)).events())
        self.assertEqual(set(event) - {"lines"}, {name for name, _ in EVENT_FIELDS})
        self.assertEqual(set(event["lines"][0]), {name for name, _ in LINE_FIELDS})

    def test_grains_and_numeric_types(self):
        for table, columns in TABLES.items():
            with self.subTest(table=table):
                self.assertEqual(len(columns), len({name for name, _ in columns}))
        event = dict(TABLES[EVENT_TABLE])
        line = dict(TABLES[LINE_TABLE])
        self.assertEqual(event["EventId"], "guid")
        self.assertEqual(event["OrderDate"], "datetime")
        self.assertEqual(line["Quantity"], "long")
        self.assertEqual(line["LineNumber"], "int")
        self.assertEqual(line["ExchangeRate"], "decimal")
        self.assertEqual(line["SalesAmount"], "decimal")
        self.assertNotIn("OrderNetAmount", line)
        self.assertNotIn("Payload", event)
        self.assertNotIn("Payload", line)
        self.assertIn("EventId, LineNumber", VIEWS["FonterraOrderLinesUnique"][1])
        self.assertIn("arg_max(EventSequence, *)", VIEWS["FonterraOrdersCurrent"][1])

    def test_policies_and_backfill_are_separate(self):
        self.assertTrue(all("ingestion_time()" not in body for body in FUNCTIONS.values()))
        for table in TABLES:
            with self.subTest(table=table):
                policy = update_policy(table)
                self.assertEqual(policy[0]["Source"], "FonterraSalesRaw")
                self.assertTrue(policy[0]["IsTransactional"])
                self.assertEqual(policy[0]["Query"], TRANSFORMS[table] + "()")
                self.assertIn("join kind=leftanti", backfill_query(table))
                self.assertNotIn("join", policy[0]["Query"])
                self.assertNotIn(".set-or-replace", render())

    def test_preflight_refuses_mismatched_schema_and_policies(self):
        assert_schema(EVENT_TABLE, TABLES[EVENT_TABLE])
        with self.assertRaises(RuntimeError):
            assert_schema(EVENT_TABLE, list(reversed(TABLES[EVENT_TABLE])))
        assert_policy(EVENT_TABLE, [])
        assert_policy(EVENT_TABLE, update_policy(EVENT_TABLE))
        with self.assertRaises(RuntimeError):
            assert_policy(EVENT_TABLE, [], required=True)
        with self.assertRaises(RuntimeError):
            assert_policy(EVENT_TABLE, [{"Source": "AnotherSource"}])

    def test_checked_in_kql_matches_generator(self):
        path = Path(__file__).resolve().parents[1] / "fabric" / "fonterra_typed.kql"
        self.assertEqual(path.read_text(encoding="utf-8"), render())

    def test_destination_columns_are_appended_without_reordering_legacy_data(self):
        manifest = legacy_manifest()
        for table in (EVENT_TABLE, LINE_TABLE):
            legacy = [tuple(column) for column in manifest["tables"][table]]
            self.assertEqual(TABLES[table], legacy + DESTINATION_FIELDS)
            assert_upgrade_schema(table, legacy, manifest)
            assert_upgrade_schema(table, TABLES[table], manifest)
            with self.assertRaises(RuntimeError):
                assert_upgrade_schema(table, legacy + [("CustomColumn", "string")], manifest)
        self.assertEqual(len(TABLES[EVENT_TABLE]), 55)
        self.assertEqual(len(TABLES[LINE_TABLE]), 70)
        for view in VIEWS:
            self.assertIn("autoUpdateSchema=true", view_command(view))

    def test_legacy_destinations_are_unknown_not_fabricated(self):
        for name, kind in DESTINATION_FIELDS:
            expression = cast(name, kind)
            self.assertIn('Payload.SchemaVersion) == "1.1"', expression)
            self.assertIn('""' if kind == "string" else f"{kind}(null)", expression)
        self.assertIn('!in ("1.0", "1.1")', FUNCTIONS["FonterraClassifyRaw"])

    def test_upgrade_preserves_custom_functions(self):
        manifest = legacy_manifest()
        name = "FonterraClassifyRaw"
        existing = {"Body": FUNCTIONS[name], "DocString": OWNER, "Parameters": "()"}
        assert_upgrade_function(name, existing, manifest)
        for mutation in ({"Body": "print Changed=1"}, {"DocString": "Custom"},
                         {"Parameters": "(Changed:string)"}):
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                assert_upgrade_function(name, {**existing, **mutation}, manifest)


if __name__ == "__main__":
    unittest.main()
