"""Deploy typed KQL tables additively; preserve raw ingestion and existing objects.

python -m scripts.deploy_typed_sales --workspace NAME --database FonterraSales --apply
Without --apply, only discovery, collision checks and raw classification run.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from scripts.provision_streaming import Client, discover, log, named, rows
from scripts.typed_sales_schema import (
    CLASSIFY, FUNCTIONS, OWNER, RAW, TABLES, TRANSFORMS, VIEWS,
    backfill_query, function_command, policy_command, table_command, update_policy, view_command,
)


def normalize(text):
    return " ".join(text.strip().strip("{}").split())


def column_signature(schema):
    return [(column["Name"], column["CslType"]) for column in schema["OrderedColumns"]]


def assert_schema(name, actual):
    if actual != TABLES[name]:
        raise RuntimeError(f"{name} schema/order differs from the typed contract; refusing destructive changes.")


def policy_value(result):
    value = result[0].get("Policy") if result else None
    return json.loads(value) if value else []


def assert_policy(table, existing, *, required=False):
    if not existing:
        if required:
            raise RuntimeError(f"Required automatic update policy is missing on {table}.")
        return
    desired = update_policy(table)[0]
    if len(existing) != 1 or any(existing[0].get(key) != value for key, value in desired.items()):
        raise RuntimeError(f"Existing update policy on {table} differs; refusing to overwrite.")


def legacy_manifest():
    path = Path(__file__).resolve().parents[1] / "fabric" / "fonterra_typed_v1_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def assert_upgrade_schema(name, actual, manifest):
    legacy = [tuple(column) for column in manifest["tables"][name]]
    if TABLES[name][:len(legacy)] != legacy or actual not in (legacy, TABLES[name]):
        raise RuntimeError(f"{name} is not the exact v1 or v1.1 schema; refusing an unsafe upgrade.")


def assert_upgrade_function(name, existing, manifest):
    digest = hashlib.sha256(normalize(existing["Body"]).encode()).hexdigest()
    current_digest = hashlib.sha256(normalize(FUNCTIONS[name]).encode()).hexdigest()
    if (existing.get("Parameters") != "()" or existing.get("DocString") not in (manifest["owner"], OWNER)
            or digest not in (manifest["functionHashes"][name], current_digest)):
        raise RuntimeError(f"{name} is not a known managed v1/v1.1 function; preserve the custom definition.")


def upgrade_v1(client, database, apply=False):
    """Resume an explicitly requested additive upgrade, including interrupted policy pauses."""
    uri, db = database["properties"]["queryServiceUri"], database["id"]
    manifest = legacy_manifest()
    tables = rows(client.kql(uri, db, ".show tables"))
    functions = rows(client.kql(uri, db, ".show functions"))
    views = rows(client.kql(uri, db, ".show materialized-views"))
    for table in TABLES:
        existing = named(tables, table, "TableName")
        if not existing or existing.get("DocString") not in (manifest["owner"], OWNER):
            raise RuntimeError(f"{table} must be an existing managed v1/v1.1 table.")
        schema = json.loads(rows(client.kql(uri, db, f".show table {table} schema as json"))[0]["Schema"])
        assert_upgrade_schema(table, column_signature(schema), manifest)
        policy = policy_value(rows(client.kql(uri, db, f".show table {table} policy update")))
        # Only our exact policy may be paused/resumed; never overwrite another consumer.
        if len(policy) == 1 and policy[0].get("IsEnabled") is False:
            policy[0]["IsEnabled"] = True
        assert_policy(table, policy, required=True)
    for name in FUNCTIONS:
        existing = named(functions, name, "Name")
        if not existing:
            raise RuntimeError(f"Missing managed function {name}; not an upgradeable installation.")
        assert_upgrade_function(name, existing, manifest)
    for name, (source, query) in VIEWS.items():
        existing = named(views, name, "Name")
        if (not existing or existing.get("DocString") not in (manifest["owner"], OWNER)
                or existing["SourceTable"] != source or normalize(existing["Query"]) != normalize(query)
                or not existing["IsEnabled"]):
            raise RuntimeError(f"{name} differs from the enabled managed view; refusing replacement.")
    log("upgradePreflight", "Known v1/v1.1 installation; additive destination columns only.")
    if not apply:
        return

    # Auto schema propagation is enabled BEFORE extending either view source table.
    for name, (source, query) in VIEWS.items():
        client.kql(uri, db, f".alter materialized-view with (autoUpdateSchema=true, docString='{OWNER}') "
                           f"{name} on table {source} {{ {query} }}")
    restored = False
    try:
        for table in TABLES:
            policy = update_policy(table)
            policy[0]["IsEnabled"] = False
            client.kql(uri, db, f".alter table {table} policy update '{json.dumps(policy)}'")
            actual = policy_value(rows(client.kql(uri, db, f".show table {table} policy update")))
            if len(actual) != 1 or any(actual[0].get(key) != value for key, value in policy[0].items()):
                raise RuntimeError(f"Could not verify the update policy pause on {table}.")
        for table in TABLES:
            client.kql(uri, db, table_command(table))
            client.kql(uri, db, f".alter table {table} docstring '{OWNER}'")
        for name in FUNCTIONS:
            client.kql(uri, db, function_command(name))
        for table, function in TRANSFORMS.items():
            schema = rows(client.kql(uri, db, f"{function}() | take 0 | getschema"))
            assert_schema(table, [(column["ColumnName"], column["ColumnType"]) for column in schema])
        for table in TABLES:
            client.kql(uri, db, policy_command(table))
            assert_policy(table, policy_value(rows(client.kql(uri, db, f".show table {table} policy update"))),
                          required=True)
        restored = True
        log("upgradePoliciesRestored", "Transactional flattening restored; deployment will backfill missed raw keys.")
    finally:
        if not restored:
            log("upgradeRecoveryRequired", "Upgrade interrupted. Raw streaming was not changed. Some typed policies "
                "may be paused; fix the reported error and rerun --upgrade-v1 --apply to resume and backfill. "
                "Do not publish schema-1.1 events or manually enable incompatible policies.")


def wait_kusto(client, uri, database, result, timeout=600):
    entries = rows(result)
    operation_id = entries[0].get("OperationId") if entries else None
    if not operation_id:
        raise RuntimeError("Async KQL operation returned no OperationId; inspect server state, do not resubmit.")
    log("kustoOperationId", operation_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(10)
        statuses = rows(client.kql(uri, database, f".show operations {operation_id}"))
        if not statuses:
            continue
        state = statuses[0]["State"]
        log("kustoOperation", {"id": operation_id, "state": state})
        if state == "Completed":
            return
        if state not in ("InProgress", "Scheduled", "Pending"):
            raise RuntimeError(f"KQL operation {operation_id} did not complete: {statuses[0]}")
    raise RuntimeError(f"Continue monitoring KQL operation {operation_id}; do not repeat its create command.")


def deploy(client, database, apply=False):
    uri, db = database["properties"]["queryServiceUri"], database["id"]
    tables = rows(client.kql(uri, db, ".show tables"))
    if not named(tables, RAW, "TableName"):
        raise RuntimeError("FonterraSalesRaw must already exist; provision the Eventstream route first.")
    raw_schema = json.loads(rows(client.kql(uri, db, f".show table {RAW} schema as json"))[0]["Schema"])
    if ("Payload", "dynamic") not in column_signature(raw_schema):
        raise RuntimeError("Expected the existing Payload:dynamic raw envelope.")
    functions = rows(client.kql(uri, db, ".show functions"))
    views = rows(client.kql(uri, db, ".show materialized-views"))
    policies = {}
    changed_functions = set()
    for name in TABLES:
        if named(functions, name, "Name") or named(views, name, "Name"):
            raise RuntimeError(f"Object-kind collision for {name}.")
        if named(tables, name, "TableName"):
            schema = json.loads(rows(client.kql(uri, db, f".show table {name} schema as json"))[0]["Schema"])
            assert_schema(name, column_signature(schema))
            policies[name] = policy_value(rows(client.kql(uri, db, f".show table {name} policy update")))
            assert_policy(name, policies[name])
    for name, body in FUNCTIONS.items():
        if named(tables, name, "TableName") or named(views, name, "Name"):
            raise RuntimeError(f"Object-kind collision for {name}.")
        existing = named(functions, name, "Name")
        if existing and normalize(existing["Body"]) != normalize(body):
            if existing.get("DocString") == OWNER and not any(policies.values()):
                changed_functions.add(name)
            else:
                raise RuntimeError(f"Function {name} already exists with another definition; preserve it.")
    for name, (source, query) in VIEWS.items():
        if named(tables, name, "TableName") or named(functions, name, "Name"):
            raise RuntimeError(f"Object-kind collision for {name}.")
        existing = named(views, name, "Name")
        if existing and (existing.get("SourceTable") != source or normalize(existing["Query"]) != normalize(query)):
            raise RuntimeError(f"Materialized view {name} differs; refusing replacement.")
    log("classification", rows(client.kql(uri, db, CLASSIFY + "\n| summarize Rows=count() by ValidationError")))
    if not apply:
        return

    for name in TABLES:
        if not named(tables, name, "TableName"):
            client.kql(uri, db, table_command(name))
            client.kql(uri, db, f".alter table {name} docstring '{OWNER}'")
            client.kql(uri, db, f".alter table {name} policy ingestiontime true")
            client.kql(uri, db, f""".alter table {name} policy retention '{{"SoftDeletePeriod":"7.00:00:00","Recoverability":"Enabled"}}'""")
            client.kql(uri, db, f".alter table {name} policy caching hot = 1d")
            log("createdTable", name)
    for name in FUNCTIONS:
        if not named(functions, name, "Name") or name in changed_functions:
            client.kql(uri, db, function_command(name))
    # The ordered projection must match before any live ingestion policy is attached.
    for table, function in TRANSFORMS.items():
        result = rows(client.kql(uri, db, f"{function}() | take 0 | getschema"))
        actual = [(column["ColumnName"], column["ColumnType"]) for column in result]
        assert_schema(table, actual)
        log("validatedProjection", {"table": table, "columns": len(actual)})
    for name in VIEWS:
        if not named(views, name, "Name"):
            wait_kusto(client, uri, db, client.kql(uri, db, view_command(name)))
            client.kql(uri, db, f""".alter materialized-view {name} policy retention '{{"SoftDeletePeriod":"7.00:00:00","Recoverability":"Enabled"}}'""")
            client.kql(uri, db, f".alter materialized-view {name} policy caching hot = 1d")
    for table in TABLES:
        if not policies.get(table):
            client.kql(uri, db, policy_command(table))
        assert_policy(table, policy_value(rows(client.kql(uri, db, f".show table {table} policy update"))), required=True)
        log("automaticFlatteningEnabled", table)

    # Install policies first; concurrent live/backfill overlaps are safe in the Unique views.
    for table in TABLES:
        query = backfill_query(table)
        missing = rows(client.kql(uri, db, query + "\n| count"))[0]["Count"]
        log("backfillMissingKeys", {"table": table, "rows": missing})
        if missing:
            client.kql(uri, db, f".set-or-append {table} <|\n{query}")
        remaining = rows(client.kql(uri, db, query + "\n| count"))[0]["Count"]
        if remaining:
            raise RuntimeError(f"{table}: {remaining} keys still missing after backfill; inspect before retrying.")
    verify(client, uri, db)


def verify(client, uri, db):
    for table in TABLES:
        schema = json.loads(rows(client.kql(uri, db, f".show table {table} schema as json"))[0]["Schema"])
        assert_schema(table, column_signature(schema))
        assert_policy(table, policy_value(rows(client.kql(uri, db, f".show table {table} policy update"))), required=True)
        log("typedTableRows", {"table": table, "rows": rows(client.kql(uri, db, f"{table} | count"))[0]["Count"]})
    for view in VIEWS:
        details = rows(client.kql(uri, db, f".show materialized-view {view}"))[0]
        if not details["IsEnabled"] or not details["IsHealthy"]:
            raise RuntimeError(f"Materialized view {view} is not enabled and healthy.")
        source = VIEWS[view][0]
        schema = rows(client.kql(uri, db, f"{view} | take 0 | getschema"))
        actual = {column["ColumnName"]: column["ColumnType"] for column in schema}
        if actual != dict(TABLES[source]):
            raise RuntimeError(f"Materialized view {view} has not adopted the source schema.")
        log("materializedViewRows", {"view": view, "rows": rows(client.kql(uri, db, f"{view} | count"))[0]["Count"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--database", default="FonterraSales")
    parser.add_argument("--environment", default="prod", choices=("dev", "test", "prod"))
    parser.add_argument("--expected-workspace-id")
    parser.add_argument("--expected-capacity-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--upgrade-v1", action="store_true",
                        help="Explicit, guarded, additive v1-to-v1.1 migration; safe to resume after interruption.")
    args = parser.parse_args()
    client = Client()
    workspace = discover(client, args)
    database = named(client.pages(f"workspaces/{workspace['id']}/kqlDatabases"), args.database)
    if not database:
        raise RuntimeError("Target KQL database does not exist.")
    principals = rows(client.kql(database["properties"]["queryServiceUri"], database["id"],
                                 f".show database ['{database['id']}'] principals"))
    log("kqlRoles", sorted({entry["Role"] for entry in principals}))
    if args.upgrade_v1:
        upgrade_v1(client, database, args.apply)
        if not args.apply:
            return
    deploy(client, database, args.apply)


if __name__ == "__main__":
    main()
