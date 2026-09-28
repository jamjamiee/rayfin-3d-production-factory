"""Provision the Fonterra custom-endpoint -> Eventhouse route, without Spark.

Requires requests, jmespath, Azure CLI login; azure-eventhub and websocket-client for --probe.
Example:
  python scripts/provision_streaming.py --environment prod --workspace NAME --phase deploy

IDs are resolved at runtime, credentials stay in memory, and POST is never retried.
No files, notebook definitions, or jobs are written by this program.
Current REST references:
https://learn.microsoft.com/rest/api/fabric/eventstream/items/update-eventstream-definition
https://learn.microsoft.com/rest/api/fabric/eventstream/topology/get-eventstream-source-connection
https://learn.microsoft.com/rest/api/fabric/kqldatabase/items/create-kql-database
https://github.com/microsoft/fabric-event-streams/blob/main/API%20Templates/eventstream-definition.json
"""

import argparse
import base64
import copy
import datetime
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import jmespath
import requests

FABRIC = "https://api.fabric.microsoft.com"
KUSTO = "https://kusto.kusto.windows.net"
TABLE = "FonterraSalesRaw"
MAPPING = "FonterraSalesRawJson"


def log(label, data):
    print(json.dumps({label: data}, ensure_ascii=True), flush=True)


def shape(value):
    """Describe response keys/types, never response values (including credentials)."""
    if isinstance(value, dict):
        return {key: shape(val) for key, val in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def named(items, name, key="displayName"):
    matches = jmespath.search(f"[?{key} == `{json.dumps(name)}`]", items)
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous name: {name}; refusing mutation")
    # Fail on case-only conflicts rather than creating another object.
    if not matches and any(str(x.get(key, "")).casefold() == name.casefold() for x in items):
        raise RuntimeError(f"Case-only name collision: {name}")
    return matches[0] if matches else None


class Client:
    def __init__(self, timeout=1200):
        self.timeout = timeout
        self.tokens = {}
        self.secrets = []

    def token(self, audience):
        cached = self.tokens.get(audience)
        if cached and time.monotonic() - cached[0] < 2400:
            return cached[1]
        result = subprocess.run(
            [shutil.which("az") or "az", "account", "get-access-token",
             "--resource", audience, "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Azure CLI token acquisition failed for {audience}; log in again")
        token = result.stdout.strip()
        if not token:
            raise RuntimeError("Azure CLI returned an empty token")
        self.tokens[audience] = (time.monotonic(), token)
        self.secrets.append(token)
        return token

    def redact(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"(?i)(SharedAccessKey=)[^;\s\"']+", r"\1[REDACTED]", text)
        text = re.sub(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", "[REDACTED]", text)
        return text[:4000]

    def request(self, method, path, body=None, audience=FABRIC, sensitive=False):
        url = path if path.startswith("https://") else FABRIC + "/v1/" + path.lstrip("/")
        parsed = urlparse(url)
        valid = parsed.scheme == "https" and not parsed.username and not parsed.password
        host = parsed.hostname or ""
        if audience == FABRIC:
            valid &= host == "api.fabric.microsoft.com"
        else:
            valid &= host.endswith((".kusto.fabric.microsoft.com", ".kusto.windows.net"))
        if not valid:
            raise RuntimeError("Refusing to forward bearer credentials to an untrusted endpoint")
        try:
            response = requests.request(
                method, url, json=body,
                headers={"Authorization": "Bearer " + self.token(audience), "Accept": "application/json"},
                timeout=180, allow_redirects=False,
            )
        except requests.RequestException:
            raise RuntimeError(
                f"{method} {parsed.path}: transport failure; outcome uncertain, do not retry POST"
            ) from None
        if not 200 <= response.status_code < 300:
            details = "credential-response body withheld" if sensitive else self.redact(response.text)
            raise RuntimeError(
                f"{method} {parsed.path}: HTTP {response.status_code}; "
                f"requestId={response.headers.get('request-id', response.headers.get('x-ms-request-id'))}; "
                f"{details}"
            )
        return response

    def call(self, method, path, body=None, result=False):
        response = self.request(method, path, body)
        log("http", {"method": method, "path": path, "status": response.status_code})
        if response.status_code != 202:
            return response.json() if response.content else {}
        location = response.headers.get("Location")
        operation = response.headers.get("x-ms-operation-id")
        log("lro", {"location": location, "operationId": operation,
                    "retryAfter": response.headers.get("Retry-After")})
        if not location:
            raise RuntimeError("202 without Location: stop and inspect; never repeat initiating POST")
        # Fabric sometimes returns a regional analysis.windows.net Location.
        # Poll the same operation on the documented public API, not the regional host.
        if urlparse(location).hostname != "api.fabric.microsoft.com":
            if not operation or not re.fullmatch(r"[0-9a-fA-F-]{36}", operation):
                raise RuntimeError("Regional LRO without a valid operation ID; stop")
            location = f"{FABRIC}/v1/operations/{operation}"
        deadline = time.monotonic() + self.timeout
        delay = int(response.headers.get("Retry-After", "10"))
        while time.monotonic() < deadline:
            time.sleep(max(1, delay))
            response = self.request("GET", location)
            state = response.json()
            status = state.get("status")
            log("operation", {"id": operation, "status": status})
            if status == "Succeeded":
                return self.request("GET", location.rstrip("/") + "/result").json() if result else {}
            if status in ("Failed", "Cancelled", "Canceled"):
                raise RuntimeError(f"LRO {operation} {status}: {self.redact(json.dumps(state))}")
            delay = int(response.headers.get("Retry-After", "10"))
        raise RuntimeError(f"LRO timeout: resume polling {location}; never repeat POST")

    def pages(self, path):
        items = []
        while path:
            page = self.request("GET", path).json()
            items.extend(page["value"])
            path = page.get("continuationUri")
            if page.get("continuationToken") and not path:
                raise RuntimeError("Continuation token without URI; discovery incomplete")
        return items

    def kql(self, uri, database, command):
        path = "/v1/rest/mgmt" if command.lstrip().startswith(".") else "/v1/rest/query"
        response = self.request("POST", uri.rstrip("/") + path,
                                {"db": database, "csl": command}, audience=KUSTO)
        data = response.json()
        if data.get("error") or data.get("Errors"):
            raise RuntimeError(self.redact(json.dumps(data)))
        # Kusto can return a successful HTTP status with a query-status error table.
        for table in data.get("Tables", []):
            if table.get("TableName") == "QueryStatus":
                cols = [c["ColumnName"] for c in table["Columns"]]
                for row in table["Rows"]:
                    entry = dict(zip(cols, row))
                    if entry.get("Severity", 6) <= 2:
                        raise RuntimeError(self.redact(json.dumps(entry)))
        return data


def rows(data):
    tables = data.get("Tables", [])
    if not tables:
        return []
    table = tables[0]
    return [dict(zip([c["ColumnName"] for c in table["Columns"]], row)) for row in table["Rows"]]


def discover(client, args):
    workspace = named(client.pages("workspaces"), args.workspace)
    if not workspace:
        raise RuntimeError("Workspace not found; no workspace will be created")
    if args.expected_workspace_id and workspace["id"] != args.expected_workspace_id:
        raise RuntimeError("Workspace ID does not match the explicitly supplied guard")
    capacities = client.pages("capacities")
    capacity = next((c for c in capacities if c["id"] == workspace.get("capacityId")), None)
    if not capacity or capacity["state"] != "Active":
        raise RuntimeError("Workspace capacity missing, inaccessible, or not Active")
    if args.expected_capacity_id and capacity["id"] != args.expected_capacity_id:
        raise RuntimeError("Capacity ID does not match the explicitly supplied guard")
    log("environment", args.environment)
    log("workspace", workspace)
    log("capacity", capacity)
    log("items", [{k: i.get(k) for k in ("id", "displayName", "type")}
                  for i in client.pages(f"workspaces/{workspace['id']}/items")])
    claims = json.loads(base64.urlsafe_b64decode(client.token(FABRIC).split(".")[1] + "==="))
    assignments = client.pages(f"workspaces/{workspace['id']}/roleAssignments")
    own_roles = [a["role"] for a in assignments if a["principal"]["id"] == claims["oid"]]
    log("callerWorkspaceRoles", own_roles)
    if not set(own_roles).intersection({"Admin", "Member", "Contributor"}):
        raise RuntimeError("No direct authoring workspace role verified; group roles need manual review")
    return workspace


def ensure_item(client, ws, collection, name, extra=None):
    path = f"workspaces/{ws}/{collection}"
    item = named(client.pages(path), name)
    if item:
        log("reuse", {"name": name, "id": item["id"]})
        return client.request("GET", path + "/" + item["id"]).json(), False
    client.call("POST", path, {"displayName": name, **(extra or {})})
    # Read-only visibility retries after a confirmed completed create.
    for _ in range(12):
        item = named(client.pages(path), name)
        if item:
            return client.request("GET", path + "/" + item["id"]).json(), True
        time.sleep(5)
    raise RuntimeError(f"Create completed but {name} is not visible; do not recreate")


def eventhouse(client, args, ws):
    house, _ = ensure_item(client, ws, "eventhouses", args.eventhouse)
    log("eventhouse", house)
    databases = client.pages(f"workspaces/{ws}/kqlDatabases")
    log("existingDatabases", databases)
    database, _ = ensure_item(
        client, ws, "kqlDatabases", args.database,
        {"creationPayload": {"databaseType": "ReadWrite", "parentEventhouseItemId": house["id"]}},
    )
    props = database.get("properties", {})
    if props.get("parentEventhouseItemId") != house["id"]:
        raise RuntimeError("Named database is not in the expected Eventhouse; refusing changes")
    if props.get("databaseType") != "ReadWrite":
        raise RuntimeError("Named database is not writable")
    log("database", database)
    return house, database


def kql_commands():
    group = None
    path = Path(__file__).resolve().parents[1] / "fabric" / "fonterra.kql"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("// @"):
            group = line.split()[1][1:]
        elif line.strip() and not line.startswith("//"):
            yield group, line


def canonical_mapping(mapping):
    return [{"column": m.get("column", m.get("Column")),
             "datatype": m.get("datatype", m.get("DataType")),
             "path": m.get("path", m.get("Properties", m.get("properties", {})).get("Path"))}
            for m in mapping]


def schema(client, database, apply=False):
    uri, db = database["properties"]["queryServiceUri"], database["id"]
    principals = rows(client.kql(uri, db, f".show database ['{db}'] principals"))
    log("kqlPrincipalRoles", sorted({p["Role"] for p in principals}))
    tables = rows(client.kql(uri, db, ".show tables"))
    exists = named(tables, TABLE, "TableName") is not None
    functions = rows(client.kql(uri, db, ".show functions"))
    existing_mapping = None
    if exists:
        table_schema = rows(client.kql(uri, db, f".show table {TABLE} schema as json"))
        log("existingSchema", table_schema)
        columns = json.loads(table_schema[0]["Schema"])["OrderedColumns"]
        payload = next((c for c in columns if c["Name"] == "Payload"), None)
        if payload and payload.get("CslType") != "dynamic":
            raise RuntimeError("Existing Payload column is not dynamic; refusing schema mutation")
        mappings = rows(client.kql(uri, db, f".show table {TABLE} ingestion json mappings"))
        existing_mapping = named(mappings, MAPPING, "Name")
        log("existingMapping", existing_mapping)
        if existing_mapping:
            expected = [{"column": "Payload", "datatype": "dynamic", "path": "$"}]
            if canonical_mapping(json.loads(existing_mapping["Mapping"])) != expected:
                raise RuntimeError("Existing mapping differs; refusing to overwrite")
        for policy in ("retention", "caching", "ingestiontime"):
            log("existingPolicy", rows(client.kql(uri, db, f".show table {TABLE} policy {policy}")))
    if apply:
        # Preflight ALL function collisions before any schema write.
        commands = list(kql_commands())
        for group, command in commands:
            if group == "function":
                name = re.search(r"\) (\w+)\(\)", command).group(1)
                existing = named(functions, name, "Name")
                if existing:
                    body = command[command.index("{"):]
                    normalize = lambda x: " ".join(x.split())
                    if normalize(existing["Body"]) != normalize(body):
                        raise RuntimeError(f"Existing function {name} differs; preserve it and stop")
        for group, command in commands:
            if group == "query" or (group == "new-table-policy" and exists):
                continue
            if group == "mapping" and existing_mapping:
                continue
            if group == "function":
                name = re.search(r"\) (\w+)\(\)", command).group(1)
                if named(functions, name, "Name"):
                    continue
            client.kql(uri, db, command)
            log("schemaApplied", command)
    if not exists and not apply:
        raise RuntimeError("Raw table is missing")
    verified_schema = rows(client.kql(uri, db, f".show table {TABLE} schema as json"))
    columns = json.loads(verified_schema[0]["Schema"])["OrderedColumns"]
    if not any(c["Name"] == "Payload" and c.get("CslType") == "dynamic" for c in columns):
        raise RuntimeError("Payload:dynamic schema validation failed")
    log("verifiedSchema", verified_schema)
    verified_mappings = rows(client.kql(uri, db, f".show table {TABLE} ingestion json mappings"))
    mapping = named(verified_mappings, MAPPING, "Name")
    if not mapping or canonical_mapping(json.loads(mapping["Mapping"])) != [
        {"column": "Payload", "datatype": "dynamic", "path": "$"}
    ]:
        raise RuntimeError("Whole-envelope mapping validation failed")
    log("verifiedMapping", verified_mappings)
    log("verifiedFunctions", rows(client.kql(uri, db, ".show functions")))


def merge_topology(topology, args, ws, database_id):
    """Add only our nodes. Preserve unrelated nodes, IDs, and unknown properties."""
    graph = copy.deepcopy(topology)
    for key in ("sources", "streams", "operators", "destinations"):
        graph.setdefault(key, [])
    graph.setdefault("compatibilityLevel", "1.0")
    desired = {
        "sources": {"name": args.source, "type": "CustomEndpoint", "properties": {}},
        "streams": {"name": args.stream, "type": "DefaultStream", "properties": {},
                    "inputNodes": [{"name": args.source}]},
        "destinations": {
            "name": args.destination, "type": "Eventhouse",
            "properties": {"dataIngestionMode": "DirectIngestion", "workspaceId": ws,
                           "itemId": database_id, "tableName": TABLE,
                           "connectionName": "FonterraSalesStreamConnection",
                           "mappingRuleName": MAPPING},
            "inputNodes": [{"name": args.stream}],
        },
    }
    for category, target in desired.items():
        current = named(graph[category], target["name"], "name")
        if current is None:
            for other in ("sources", "streams", "operators", "destinations"):
                if other != category and named(graph[other], target["name"], "name"):
                    raise RuntimeError(f"Node name collision: {target['name']}")
            graph[category].append(target)
        else:
            if current["type"] != target["type"]:
                raise RuntimeError(f"Existing node type conflict: {target['name']}")
            if "inputNodes" in target and current.get("inputNodes") != target["inputNodes"]:
                raise RuntimeError(f"Existing input wiring conflict: {target['name']}")
            for key, value in target["properties"].items():
                old = current.setdefault("properties", {}).get(key)
                if old is not None and old != value:
                    raise RuntimeError(f"Existing {target['name']} property conflict: {key}")
                current["properties"][key] = value
    return graph


def part(path, data):
    return {"path": path, "payloadType": "InlineBase64",
            "payload": base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii")}


def decoded(definition, path):
    parts = [p for p in definition["parts"] if p["path"] == path]
    if len(parts) != 1 or parts[0]["payloadType"] != "InlineBase64":
        raise RuntimeError(f"Missing/ambiguous/unsupported definition part {path}")
    return json.loads(base64.b64decode(parts[0]["payload"]))


def deploy_stream(client, args, ws, database):
    stream, created = ensure_item(client, ws, "eventstreams", args.eventstream)
    path = f"workspaces/{ws}/eventstreams/{stream['id']}"
    definition = client.call("POST", path + "/getDefinition", result=True)["definition"]
    graph = decoded(definition, "eventstream.json")
    log("existingTopology", graph)
    merged = merge_topology(graph, args, ws, database["id"])
    prop_parts = [p for p in definition["parts"] if p["path"] == "eventstreamProperties.json"]
    properties = decoded(definition, "eventstreamProperties.json") if prop_parts else {}
    # Preserve unrelated properties; only the explicitly named eventstream is configured.
    configured = {**properties, "retentionTimeInDays": 1, "eventThroughputLevel": "Low"}
    if merged != graph or configured != properties:
        new_definition = copy.deepcopy(definition)
        new_definition["parts"] = [
            p for p in definition["parts"]
            if p["path"] not in ("eventstream.json", "eventstreamProperties.json")
        ] + [part("eventstream.json", merged), part("eventstreamProperties.json", configured)]
        # Reject a concurrent definition edit before submitting our merged definition.
        latest = client.call("POST", path + "/getDefinition", result=True)["definition"]
        if latest != definition:
            raise RuntimeError("Eventstream changed during preflight; refusing overwrite")
        client.call("POST", path + "/updateDefinition", {"definition": new_definition})
    else:
        log("topologyUnchanged", stream["id"])
    return stream


def verify_stream(client, args, ws, stream, database):
    path = f"workspaces/{ws}/eventstreams/{stream['id']}"
    graph = client.request("GET", path + "/topology").json()
    log("runtimeTopology", graph)
    source = named(graph["sources"], args.source, "name")
    destination = named(graph["destinations"], args.destination, "name")
    if not source or not destination:
        raise RuntimeError("Required source or destination missing from runtime topology")
    deadline = time.monotonic() + 600
    while True:
        source = client.request("GET", path + "/sources/" + source["id"]).json()
        destination = client.request("GET", path + "/destinations/" + destination["id"]).json()
        log("nodeStatus", {"source": source, "destination": destination})
        if any(n.get("error") or n.get("status") == "Failed" for n in (source, destination)):
            raise RuntimeError("Runtime node failed; see explicit nodeStatus diagnostics")
        if source.get("status") in ("Running", "Created") and destination.get("status") == "Running":
            break
        if time.monotonic() > deadline:
            raise RuntimeError("Runtime readiness timeout; resources preserved, no POST retries")
        time.sleep(20)
    definition = client.call("POST", path + "/getDefinition", result=True)["definition"]
    deployed = decoded(definition, "eventstream.json")
    if merge_topology(deployed, args, ws, database["id"]) != deployed:
        raise RuntimeError("Deployed definition does not contain the complete intended route")
    properties = decoded(definition, "eventstreamProperties.json")
    if properties.get("retentionTimeInDays") != 1 or properties.get("eventThroughputLevel") != "Low":
        raise RuntimeError("Eventstream retention/throughput validation failed")
    log("deployedTopology", deployed)
    log("deployedProperties", properties)
    connection_path = path + "/sources/" + source["id"] + "/connection"
    connection = client.request("GET", connection_path, sensitive=True).json()
    log("sourceConnection", {"api": FABRIC + "/v1/" + connection_path, "schema": shape(connection)})
    keys = connection.get("accessKeys", {})
    for value in keys.values():
        if isinstance(value, str) and value:
            client.secrets.append(value)
    connection_string = keys.get("primaryConnectionString", "")
    log("sourceCredentialAvailability", {key: bool(value) for key, value in keys.items()})
    if connection_string:
        fields = dict(field.split("=", 1) for field in connection_string.split(";") if "=" in field)
        log("connectionStringFieldNames", sorted(fields))
        if (urlparse(fields.get("Endpoint", "")).hostname != connection.get("fullyQualifiedNamespace")
                or fields.get("EntityPath") != connection.get("eventHubName")):
            raise RuntimeError("Source namespace/entity path do not match connection string")
    if connection.get("type") != "CustomEndpoint" or not connection_string:
        raise RuntimeError("Source connection lacks usable custom endpoint credentials")
    return source, destination, connection


def envelopes_equal(actual, expected):
    """Kusto dynamic may normalize ISO timestamps; compare their instant, not spelling."""
    left, right = copy.deepcopy(actual), copy.deepcopy(expected)
    for payload in (left, right):
        if isinstance(payload.get("EventTime"), str):
            payload["EventTime"] = datetime.datetime.fromisoformat(
                payload["EventTime"].replace("Z", "+00:00")
            )
    return left == right


def probe(client, database, connection):
    """Exactly one marked event, zero send retries, then read-only ingestion polling."""
    from azure.eventhub import EventData, EventHubProducerClient, TransportType
    try:
        import websocket  # noqa: F401 -- fail before preparing/sending a probe
    except ImportError:
        raise RuntimeError("Probe requires websocket-client; no message prepared or sent") from None

    event = {
        "EventId": str(uuid.uuid4()), "SimulationRunId": str(uuid.uuid4()),
        "EventSequence": 0, "EventTime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "EventType": "ORDER_RECEIVED", "OrderKey": str(uuid.uuid4()),
        "BrandScopeId": "INFRASTRUCTURE_PROBE", "PortfolioStatus": "SYNTHETIC_PROBE",
        "InfrastructureProbe": True, "ProbeMarker": "FonterraEventstreamEnvelopeProbe",
        "FXRate": 0.6125,
        "lines": [{"LineNumber": 1, "SalesAmount": 12.345, "FXRate": 0.6125}],
        "UnmodeledExtension": {"preserved": True, "values": ["nested", 1, 0.6125]},
    }
    log("probePrepared", {"EventId": event["EventId"], "SimulationRunId": event["SimulationRunId"],
                          "messages": 1, "sendRetries": 0})
    producer = EventHubProducerClient.from_connection_string(
        connection["accessKeys"]["primaryConnectionString"],
        eventhub_name=connection["eventHubName"],
        transport_type=TransportType.AmqpOverWebsocket,
        retry_total=0, logging_enable=False,
    )
    send_attempted = False
    try:
        with producer:
            batch = producer.create_batch()
            message = EventData(json.dumps(event))
            message.content_type = "application/json"
            batch.add(message)
            send_attempted = True
            producer.send_batch(batch, timeout=60)
    except Exception as exc:
        # SDK errors can contain connection details: report only class, never str(exc).
        outcome = "outcome uncertain, do not resend" if send_attempted else "send not attempted"
        raise RuntimeError(f"Probe transport {type(exc).__name__}; {outcome}") from None
    log("probeAccepted", {"EventId": event["EventId"], "messages": 1})
    uri, db = database["properties"]["queryServiceUri"], database["id"]
    query = (
        f"{TABLE} | where ingestion_time() > ago(1h) "
        f"| where tostring(Payload.EventId) == '{event['EventId']}' | project Payload | take 3"
    )
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        result = rows(client.kql(uri, db, query))
        if result:
            payload = result[0]["Payload"]
            payload = json.loads(payload) if isinstance(payload, str) else payload
            if not envelopes_equal(payload, event):
                raise RuntimeError("Probe arrived but whole-envelope equality failed")
            log("ingestionProof", {"EventId": event["EventId"],
                                    "SimulationRunId": event["SimulationRunId"],
                                    "rawRows": len(result), "wholeEnvelopeSemanticallyEqual": True,
                                    "fractionalFX": payload["FXRate"],
                                    "lineSalesAmount": payload["lines"][0]["SalesAmount"]})
            result = rows(client.kql(
                uri, db,
                "FonterraSalesLines() | where EventTime > ago(1h) "
                f"| where EventId == '{event['EventId']}' "
                "| project EventId, EventType, LineSalesAmount, FXRate=toreal(Line.FXRate)",
            ))
            log("helperFunctionProof", result)
            if len(result) != 1 or result[0]["LineSalesAmount"] != 12.345:
                raise RuntimeError("Flattened line helper validation failed")
            return
        log("ingestionPending", {"EventId": event["EventId"]})
        time.sleep(20)
    try:
        failures = rows(client.kql(
            uri, db,
            f".show ingestion failures | where FailedOn > ago(1h) and Table == '{TABLE}' "
            "| project FailedOn, ErrorCode, FailureStatus | take 10",
        ))
        log("ingestionFailures", failures)
    except RuntimeError as exc:
        # Some Fabric endpoints reject this ADX management command (HTTP 400).
        # Preserve the primary timeout diagnostic instead of masking it.
        log("ingestionFailureDiagnosticsUnavailable", client.redact(str(exc)))
    raise RuntimeError("Probe accepted but not found within 600 seconds; do not resend")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=("dev", "test", "prod"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--expected-workspace-id")
    parser.add_argument("--expected-capacity-id")
    parser.add_argument("--eventhouse", default="FonterraEventhouse")
    parser.add_argument("--database", default="FonterraSales")
    parser.add_argument("--eventstream", default="FonterraSalesStream")
    parser.add_argument("--source", default="FonterraSalesSource")
    parser.add_argument("--stream", default="FonterraSalesDefaultStream")
    parser.add_argument("--destination", default="FonterraSalesDestination")
    parser.add_argument("--phase", choices=("discover", "eventhouse", "deploy", "verify"),
                        default="discover")
    parser.add_argument("--probe", action="store_true",
                        help="Send exactly one marked ORDER_RECEIVED event; never use on an uncertain resend")
    args = parser.parse_args()
    if args.probe and args.phase not in ("deploy", "verify"):
        parser.error("--probe requires --phase deploy or verify")
    client = Client()
    try:
        workspace = discover(client, args)
        if args.phase == "discover":
            return
        if args.phase == "eventhouse":
            eventhouse(client, args, workspace["id"])
            return
        ws = workspace["id"]
        if args.phase == "deploy":
            house, database = eventhouse(client, args, ws)
            schema(client, database, apply=True)
            stream = deploy_stream(client, args, ws, database)
        else:
            database = named(client.pages(f"workspaces/{ws}/kqlDatabases"), args.database)
            stream = named(client.pages(f"workspaces/{ws}/eventstreams"), args.eventstream)
            if not database or not stream:
                raise RuntimeError("Required resources missing; verification never creates them")
            schema(client, database)
        _, _, connection = verify_stream(client, args, ws, stream, database)
        if args.probe:
            probe(client, database, connection)
    except RuntimeError as exc:
        log("error", client.redact(str(exc)))
        sys.exit(1)


if __name__ == "__main__":
    main()
