import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from azure.core.exceptions import ClientAuthenticationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.kql import FeedError, KqlFeed, Settings, extract_snapshot
from backend.models import Snapshot
from backend.server import create_app


CLUSTER = "https://test.kusto.fabric.microsoft.com"
DATABASE = "00000000-0000-0000-0000-000000000001"
WHEN = "2026-09-12T07:00:00Z"


def snapshot_fixture():
    return {
        "generatedAt": WHEN, "windowHours": 24, "maxOrders": 200, "scope": "NZ supermarket deliveries",
        "productionSource": "Illustrative, not telemetry.", "orders": [], "lines": [], "activity": [],
        "totals": {"totalOrders": 0, "awaitingDispatch": 0, "inTransit": 0, "delivered": 0,
                   "cancelled": 0, "lateOrders": 0, "salesNZD": "0.00", "lastEventAt": None},
    }


def response_body(snapshot=None):
    return {"Tables": [{"TableName": "PrimaryResult",
                        "Columns": [{"ColumnName": "Snapshot", "DataType": "String"}],
                        "Rows": [[json.dumps(snapshot if snapshot is not None else snapshot_fixture())]]}]}


class SettingsTests(unittest.TestCase):
    def test_requires_explicit_known_cluster_origin_and_database(self):
        self.assertEqual(Settings.from_environment({"FONTERRA_KQL_CLUSTER": CLUSTER,
                                                    "FONTERRA_KQL_DATABASE": DATABASE}), Settings(CLUSTER, DATABASE))
        for cluster in ("http://test.kusto.fabric.microsoft.com", "https://evil.example",
                        CLUSTER + "/redirect", CLUSTER + "?target=evil", "https://user:password@test.kusto.fabric.microsoft.com",
                        "https://test.kusto.fabric.microsoft.com.evil.example", CLUSTER + ":9999"):
            with self.subTest(cluster=cluster), self.assertRaises(ValueError):
                Settings.from_environment({"FONTERRA_KQL_CLUSTER": cluster, "FONTERRA_KQL_DATABASE": DATABASE})
        with self.assertRaises(ValueError):
            Settings.from_environment({})


class SnapshotTests(unittest.TestCase):
    def test_empty_data_is_a_valid_explicit_snapshot(self):
        snapshot = extract_snapshot(response_body())
        self.assertEqual(snapshot.orders, [])
        self.assertIsNone(snapshot.totals.lastEventAt)

    def test_query_failures_are_not_empty_successes(self):
        for result in ({"error": {"code": "Failed"}}, {"Tables": []},
                       {"Tables": [{"Columns": [{"ColumnName": "Snapshot"}], "Rows": []}]}):
            with self.subTest(result=result), self.assertRaises(FeedError):
                extract_snapshot(result)
        result = response_body()
        result["Tables"].append({"TableName": "QueryStatus", "Columns": [{"ColumnName": "Severity"}], "Rows": [[2]]})
        with self.assertRaises(FeedError):
            extract_snapshot(result)

    def test_partial_or_nonfinite_data_is_rejected(self):
        for amount in ("NaN", "Infinity", "-1.0", "not money"):
            value = snapshot_fixture()
            value["totals"]["salesNZD"] = amount
            with self.subTest(amount=amount), self.assertRaises(FeedError):
                extract_snapshot(response_body(value))
        value = snapshot_fixture()
        value["orders"] = [{"id": "incomplete"}]
        with self.assertRaises(FeedError):
            extract_snapshot(response_body(value))

    def test_naive_dates_are_rejected(self):
        value = snapshot_fixture()
        value["generatedAt"] = "2026-09-12T07:00:00"
        with self.assertRaises(ValidationError):
            Snapshot.model_validate(value)


class FeedTests(unittest.TestCase):
    def make_feed(self, handler, clock=lambda: 0):
        credential = Mock()
        credential.get_token.return_value = SimpleNamespace(token="test-only-token", expires_on=time.time() + 3600)
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        return KqlFeed(Settings(CLUSTER, DATABASE), credential=credential, http_client=client, clock=clock)

    def test_read_only_fixed_query_token_and_short_cache(self):
        calls = []
        now = [0.0]

        def handler(request):
            calls.append(request)
            self.assertEqual(str(request.url), CLUSTER + "/v1/rest/query")
            self.assertEqual(request.headers["Authorization"], "Bearer test-only-token")
            body = json.loads(request.content)
            self.assertEqual(body["db"], DATABASE)
            self.assertIn("FonterraOrdersCurrent", body["csl"])
            self.assertNotIn(".set-or-", body["csl"])
            return httpx.Response(200, json=response_body())

        feed = self.make_feed(handler, clock=lambda: now[0])
        first = feed.snapshot()
        self.assertIs(feed.snapshot(), first)
        self.assertEqual(len(calls), 1)
        now[0] = 3
        feed.snapshot()
        self.assertEqual(len(calls), 2)
        feed.credential.get_token.assert_called_once()
        feed.close()

    def test_http_failures_do_not_serve_stale_data_as_fresh(self):
        for status in (301, 401, 403, 429, 500):
            with self.subTest(status=status):
                feed = self.make_feed(lambda request: httpx.Response(status, text="private upstream body"))
                with self.assertRaises(FeedError) as failure:
                    feed.snapshot()
                self.assertNotIn("private upstream body", str(failure.exception))
                self.assertNotIn("test-only-token", str(failure.exception))
                feed.close()

    def test_authentication_failure_is_explicit(self):
        feed = self.make_feed(lambda request: httpx.Response(200, json=response_body()))
        feed.credential.get_token.side_effect = ClientAuthenticationError(message="private credential details")
        with self.assertRaises(FeedError) as failure:
            feed.snapshot()
        self.assertEqual(failure.exception.code, "authentication_required")
        self.assertNotIn("private credential details", str(failure.exception))
        feed.close()


class ServerTests(unittest.TestCase):
    def test_relative_api_contract_and_no_browser_token(self):
        feed = Mock()
        feed.snapshot.return_value = Snapshot.model_validate(snapshot_fixture())
        with TestClient(create_app(feed)) as client:
            response = client.get("/api/factory/snapshot")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["orders"], [])
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("token", response.text)
            self.assertEqual(client.get("/api/not-a-route").status_code, 404)
            self.assertEqual(client.get("/api/health", headers={"Host": "evil.example"}).status_code, 400)
            feed.snapshot.side_effect = FeedError("kql_unreachable", "KQL is unreachable.", 503)
            failure = client.get("/api/factory/snapshot")
            self.assertEqual(failure.status_code, 503)
            self.assertEqual(failure.json()["error"]["code"], "kql_unreachable")


if __name__ == "__main__":
    unittest.main()
