import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.build_notebook import build_notebook
from src.fonterra_simulator import resolve_eventstream_connection


WS = "11111111-1111-4111-8111-111111111111"
ES = "22222222-2222-4222-8222-222222222222"
SOURCE = "33333333-3333-4333-8333-333333333333"
BASE = f"/v1/workspaces/{WS}/eventstreams/{ES}"
ITEMS = f"/v1/workspaces/{WS}/items?type=Eventstream"
CONNECTION = "Endpoint=sb://example.servicebus.windows.net/;SharedAccessKeyName=Send;SharedAccessKey=fake==;EntityPath=events"


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class Client:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return self.pages[path]


def pages():
    return {
        "/v1/workspaces": Response({"value": [{"id": WS, "displayName": "workspace"}]}),
        ITEMS: Response({"value": [{"id": ES, "displayName": "stream", "type": "Eventstream"}]}),
        f"{BASE}/topology": Response({"sources": [{"id": SOURCE, "name": "source", "type": "CustomEndpoint"}]}),
        f"{BASE}/sources/{SOURCE}/connection": Response({
            "type": "CustomEndpoint", "accessKeys": {"primaryConnectionString": CONNECTION},
        }),
    }


class EndpointResolutionTests(unittest.TestCase):
    def test_notebook_bootstrap_covers_all_transport_requirements(self):
        notebook = build_notebook()
        bootstrap = next(cell for cell in notebook["cells"] if cell["id"] == "sdk-bootstrap")
        command = "".join(bootstrap["source"])
        requirements = (Path(__file__).resolve().parents[1] / "requirements-streaming.txt").read_text()
        for requirement in requirements.splitlines():
            if requirement and not requirement.startswith("#"):
                self.assertIn(f"'{requirement}'", command)
        ids = [cell["id"] for cell in notebook["cells"]]
        self.assertLess(ids.index("sdk-bootstrap"), ids.index("parameters"))

    def test_discovers_ids_and_does_not_print_keys(self):
        client = Client(pages())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            connection = resolve_eventstream_connection("workspace", "stream", "source", client=client)
        self.assertEqual(connection, CONNECTION)
        self.assertEqual(client.calls, list(pages()))
        self.assertEqual(output.getvalue(), "")

    def test_workspace_and_item_pagination_encode_tokens(self):
        responses = pages()
        for path in ("/v1/workspaces", ITEMS):
            original = responses[path]
            responses[path] = Response({"value": [], "continuationToken": "next+/="})
            joiner = "&" if "?" in path else "?"
            responses[f"{path}{joiner}continuationToken=next%2B%2F%3D"] = original
        client = Client(responses)
        self.assertEqual(resolve_eventstream_connection("workspace", "stream", "source", client=client), CONNECTION)
        self.assertEqual(len(client.calls), 6)

    def test_missing_or_duplicate_names_and_wrong_source_type(self):
        changes = [
            ("/v1/workspaces", {"value": []}),
            ("/v1/workspaces", {"value": [{"id": WS, "displayName": "workspace"}] * 2}),
            (ITEMS, {"value": [{"id": ES, "displayName": "stream", "type": "Notebook"}]}),
            (f"{BASE}/topology", {"sources": []}),
            (f"{BASE}/topology", {"sources": [{"id": SOURCE, "name": "source", "type": "SampleData"}]}),
            (f"{BASE}/topology", {"sources": [{"id": SOURCE, "name": "source", "type": "CustomEndpoint"}] * 2}),
            (f"{BASE}/sources/{SOURCE}/connection", {"type": "KafkaEndpoint"}),
            (f"{BASE}/sources/{SOURCE}/connection", {"type": "CustomEndpoint", "accessKeys": {}}),
        ]
        for path, payload in changes:
            with self.subTest(path=path, payload=payload):
                responses = pages()
                responses[path] = Response(payload)
                with self.assertRaises(ValueError):
                    resolve_eventstream_connection("workspace", "stream", "source", client=Client(responses))

    def test_permission_errors_and_bad_responses_do_not_leak(self):
        for status in (401, 403, 404, 429, 500):
            responses = pages()
            responses[f"{BASE}/sources/{SOURCE}/connection"] = Response({"key": "secret-must-not-leak"}, status)
            with self.subTest(status=status), self.assertRaises(RuntimeError) as error:
                resolve_eventstream_connection("workspace", "stream", "source", client=Client(responses))
            self.assertIn(str(status), str(error.exception))
            self.assertNotIn("secret-must-not-leak", str(error.exception))
        for payload in ([], {}, {"value": [], "continuationUri": "https://example.com"}):
            responses = pages()
            responses["/v1/workspaces"] = Response(payload)
            with self.assertRaises(RuntimeError):
                resolve_eventstream_connection("workspace", "stream", "source", client=Client(responses))

    def test_repeated_continuation_token_fails(self):
        response = Response({"value": [], "continuationToken": "repeat"})
        client = Client({"/v1/workspaces": response, "/v1/workspaces?continuationToken=repeat": response})
        with self.assertRaisesRegex(RuntimeError, "repeated"):
            resolve_eventstream_connection("workspace", "stream", "source", client=client)
        self.assertEqual(len(client.calls), 2)

    def test_empty_names_rejected_before_network(self):
        client = Client({})
        for names in (("", "stream", "source"), ("workspace", "", "source"), ("workspace", "stream", " ")):
            with self.assertRaises(ValueError):
                resolve_eventstream_connection(*names, client=client)
        self.assertEqual(client.calls, [])

    def test_notebook_default_live_branch_resolves_then_publishes(self):
        namespace = {"__name__": "__main__"}
        resolver = Mock(return_value=CONNECTION)
        publisher = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            for cell in build_notebook()["cells"]:
                if cell["cell_type"] != "code":
                    continue
                if cell["id"] == "sdk-bootstrap":
                    self.assertTrue("".join(cell["source"]).startswith("%pip install"))
                    continue
                if cell["id"] == "run":
                    namespace["resolve_eventstream_connection"] = resolver
                    namespace["stream_to_eventstream"] = publisher
                exec(compile("".join(cell["source"]), cell["id"], "exec"), namespace)
        resolver.assert_called_once_with("rayfin-3d-production-factory", "FonterraSalesStream", "FonterraSalesSource")
        publisher.assert_called_once_with(namespace["config"], CONNECTION, run_id=None)
        self.assertNotIn("connection_string", namespace)
        self.assertEqual(namespace["config"].max_orders, 60)
        self.assertEqual(namespace["config"].max_duration_seconds, 120)
        self.assertTrue(namespace["config"].include_nz_supermarket_orders)
        self.assertFalse(namespace["config"].include_divested_brands)


if __name__ == "__main__":
    unittest.main()
