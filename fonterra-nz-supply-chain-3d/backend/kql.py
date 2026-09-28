import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse
from uuid import UUID

import httpx
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential
from pydantic import ValidationError

from .models import Snapshot


LOG = logging.getLogger("fonterra.kql")
QUERY_PATH = Path(__file__).resolve().parents[1] / "fabric" / "factory_snapshot.kql"


class FeedError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Settings:
    cluster: str
    database: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None):
        env = os.environ if environment is None else environment
        cluster = env.get("FONTERRA_KQL_CLUSTER", "").rstrip("/")
        database = env.get("FONTERRA_KQL_DATABASE", "")
        url = urlparse(cluster)
        if (url.scheme != "https" or not (url.hostname or "").endswith(".kusto.fabric.microsoft.com")
                or url.username or url.password or url.path or url.query or url.fragment
                or url.port not in (None, 443)):
            raise ValueError("FONTERRA_KQL_CLUSTER must be an HTTPS Fabric Kusto cluster origin.")
        try:
            database = str(UUID(database))
        except ValueError as error:
            raise ValueError("FONTERRA_KQL_DATABASE must be the FonterraSales database GUID.") from error
        return cls(cluster, database)


def extract_snapshot(result: dict) -> Snapshot:
    if result.get("error") or result.get("Errors"):
        raise FeedError("kql_query_failed", "KQL reported a query failure. Check the typed tables and backend logs.")
    for table in result.get("Tables", []):
        names = [column["ColumnName"] for column in table["Columns"]]
        if table.get("TableName") == "QueryStatus":
            for row in table["Rows"]:
                entry = dict(zip(names, row))
                if entry.get("Severity", 6) <= 2:
                    raise FeedError("kql_query_failed", "KQL returned incomplete results; no partial snapshot was accepted.")
    tables = [table for table in result.get("Tables", [])
              if [column["ColumnName"] for column in table["Columns"]] == ["Snapshot"]]
    if len(tables) != 1 or len(tables[0]["Rows"]) != 1 or len(tables[0]["Rows"][0]) != 1:
        raise FeedError("invalid_snapshot", "KQL did not return the expected single factory snapshot.")
    value = tables[0]["Rows"][0][0]
    try:
        payload = json.loads(value) if isinstance(value, str) else value
        return Snapshot.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        LOG.error("Snapshot contract validation failed (%s).", type(error).__name__)
        raise FeedError("invalid_snapshot", "KQL returned inconsistent factory data. Confirm the schema and retry.") from error


class KqlFeed:
    def __init__(self, settings: Settings, *, credential=None, http_client=None, clock=time.monotonic):
        self.settings = settings
        self.credential = credential if credential is not None else AzureCliCredential(process_timeout=20)
        self.http = http_client if http_client is not None else httpx.Client(timeout=30, follow_redirects=False)
        self.clock = clock
        self.query = QUERY_PATH.read_text(encoding="utf-8")
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = float("-inf")
        self.token = None

    def snapshot(self) -> Snapshot:
        with self.lock:
            if self.cached is not None and self.clock() - self.cached_at < 2:
                return self.cached
            try:
                if self.token is None or self.token.expires_on < time.time() + 120:
                    self.token = self.credential.get_token("https://kusto.kusto.windows.net/.default")
            except ClientAuthenticationError as error:
                LOG.warning("Azure CLI authentication failed.")
                raise FeedError("authentication_required",
                    "Sign in to Azure CLI with an account that can read FonterraSales, then refresh.", 401) from error
            try:
                response = self.http.post(
                    self.settings.cluster + "/v1/rest/query",
                    headers={"Authorization": "Bearer " + self.token.token, "Accept": "application/json"},
                    json={"db": self.settings.database, "csl": self.query},
                )
            except httpx.RequestError as error:
                LOG.warning("KQL transport failed (%s).", type(error).__name__)
                raise FeedError("kql_unreachable", "The KQL endpoint is unreachable. The previous snapshot may be stale.", 503) from error
            if not 200 <= response.status_code < 300:
                LOG.warning("KQL HTTP failure: status=%s.", response.status_code)
                if response.status_code in (401, 403):
                    self.token = None
                    raise FeedError("kql_access_denied", "The signed-in account cannot read FonterraSales.", 403)
                if response.status_code == 429:
                    raise FeedError("kql_throttled", "Fabric is throttling queries. Wait before refreshing.", 503)
                raise FeedError("kql_query_failed", "KQL rejected the snapshot query. Check the backend configuration.")
            try:
                body = response.json()
            except json.JSONDecodeError as error:
                raise FeedError("invalid_snapshot", "The KQL endpoint did not return JSON.") from error
            if not isinstance(body, dict):
                raise FeedError("invalid_snapshot", "The KQL response has an unexpected shape.")
            result = extract_snapshot(body)
            self.cached, self.cached_at = result, self.clock()
            return result

    def close(self):
        self.http.close()
        self.credential.close()
