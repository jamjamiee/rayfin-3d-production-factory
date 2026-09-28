"""Infrastructure-only offline tests; no notebook or Azure API calls."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.provision_streaming import (
    Client, canonical_mapping, decoded, envelopes_equal, kql_commands, merge_topology,
    named, part, shape,
)


class StreamingInfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(source="FonterraSalesSource",
                                    stream="FonterraSalesDefaultStream",
                                    destination="FonterraSalesDestination")
        self.empty = {"sources": [], "streams": [], "operators": [], "destinations": [],
                      "compatibilityLevel": "1.1"}

    def test_merge_is_idempotent_and_does_not_mutate_input(self):
        original = copy.deepcopy(self.empty)
        graph = merge_topology(self.empty, self.args, "workspace", "database")
        self.assertEqual(self.empty, original)
        self.assertEqual(graph, merge_topology(graph, self.args, "workspace", "database"))
        self.assertEqual(graph["destinations"][0]["properties"]["itemId"], "database")
        self.assertEqual(graph["destinations"][0]["properties"]["dataIngestionMode"],
                         "DirectIngestion")

    def test_preserve_unrelated_nodes_and_server_ids(self):
        graph = merge_topology(self.empty, self.args, "workspace", "database")
        graph["sources"][0]["id"] = "server-assigned"
        other = {"name": "OtherSource", "type": "SampleData", "properties": {"type": "Buses"}}
        graph["sources"].append(other)
        graph["futureProperty"] = {"preserve": True}
        self.assertEqual(graph, merge_topology(graph, self.args, "workspace", "database"))

    def test_route_conflict_stops_without_overwrite(self):
        graph = merge_topology(self.empty, self.args, "workspace", "database")
        graph["destinations"][0]["properties"]["itemId"] = "unrelated-database"
        with self.assertRaisesRegex(RuntimeError, "property conflict"):
            merge_topology(graph, self.args, "workspace", "database")

    def test_duplicate_and_case_collision_names_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
            named([{"displayName": "One"}, {"displayName": "One"}], "One")
        with self.assertRaisesRegex(RuntimeError, "Case-only"):
            named([{"displayName": "one"}], "One")

    def test_definition_encoding_roundtrip(self):
        definition = {"parts": [part("eventstream.json", self.empty)]}
        self.assertEqual(decoded(definition, "eventstream.json"), self.empty)

    def test_mapping_handles_kusto_normalized_and_request_forms(self):
        a = [{"column": "Payload", "datatype": "dynamic", "Properties": {"Path": "$"}}]
        b = [{"column": "Payload", "datatype": "dynamic", "path": "$"}]
        self.assertEqual(canonical_mapping(a), canonical_mapping(b))

    def test_connection_shape_contains_no_values(self):
        description = shape({"type": "CustomEndpoint", "accessKeys": {"primaryKey": "SECRET"}})
        self.assertEqual(description["accessKeys"]["primaryKey"], "str")
        self.assertNotIn("SECRET", str(description))

    def test_dynamic_timestamp_normalization_is_lossless(self):
        expected = {"EventTime": "2026-09-12T05:32:20.431256+00:00",
                    "FXRate": 0.6125, "lines": [{"SalesAmount": 12.345}]}
        actual = copy.deepcopy(expected)
        actual["EventTime"] = "2026-09-12T05:32:20.4312560Z"
        self.assertTrue(envelopes_equal(actual, expected))
        actual["FXRate"] = 0
        self.assertFalse(envelopes_equal(actual, expected))

    def test_lro_polls_once_without_repeating_post(self):
        client = Client()
        first = Mock(status_code=202, headers={
            "Location": "https://regional.analysis.windows.net/v1/operations/operation",
            "x-ms-operation-id": "00000000-0000-0000-0000-000000000001", "Retry-After": "1",
        })
        poll = Mock()
        poll.json.return_value = {"status": "Succeeded"}
        client.request = Mock(side_effect=[first, poll])
        with patch("scripts.provision_streaming.time.sleep"):
            client.call("POST", "workspaces/workspace/eventstreams", {"displayName": "One"})
        self.assertEqual([c.args[0] for c in client.request.call_args_list], ["POST", "GET"])
        self.assertIn("https://api.fabric.microsoft.com/v1/operations/",
                      client.request.call_args_list[1].args[1])

    def test_policy_commands_are_explicitly_new_table_only(self):
        commands = list(kql_commands())
        policies = [(group, cmd) for group, cmd in commands if " policy " in cmd]
        self.assertEqual(len(policies), 3)
        self.assertTrue(all(group == "new-table-policy" for group, _ in policies))
        self.assertFalse(any(".ingest " in cmd for _, cmd in commands))
        line_function = next(cmd for group, cmd in commands if "FonterraSalesLines() {" in cmd)
        self.assertIn("toreal(Line.SalesAmount)", line_function)


if __name__ == "__main__":
    unittest.main()
