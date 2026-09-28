"""Single source of truth for the typed KQL schemas and transformations."""

import json
from pathlib import Path


OWNER = "Fonterra typed schema v1.1"
RAW = "FonterraSalesRaw"
EVENT_TABLE = "FonterraOrderEvents"
LINE_TABLE = "FonterraOrderLines"
REJECT_TABLE = "FonterraSalesRejected"

EVENT_FIELDS = [
    ("SchemaVersion", "string"), ("IsSynthetic", "bool"), ("CatalogAsOf", "datetime"),
    ("SimulationRunId", "guid"), ("EventId", "guid"), ("EventSequence", "int"),
    ("EventType", "string"), ("EventTime", "datetime"), ("ClockMode", "string"),
    ("OrderKey", "guid"), ("OrderNumber", "string"), ("OrderStatus", "string"),
    ("OrderDate", "datetime"), ("ExpectedDeliveryDate", "datetime"),
    ("DispatchDate", "datetime"), ("DeliveryDate", "datetime"),
    ("DispatchId", "string"), ("CancellationReason", "string"),
    ("CustomerKey", "long"), ("CustomerName", "string"),
    ("StoreKey", "long"), ("StoreName", "string"), ("WarehouseId", "string"),
    ("Brand", "string"), ("BrandScopeId", "string"), ("PortfolioStatus", "string"),
    ("Channel", "string"), ("MarketCode", "string"), ("Country", "string"), ("City", "string"),
    ("Latitude", "real"), ("Longitude", "real"),
    ("CurrencyCode", "string"), ("ReportingCurrencyCode", "string"), ("ExchangeRate", "decimal"),
    ("OrderNetAmount", "decimal"), ("OrderNetAmountNZD", "decimal"),
    ("SalesAmount", "decimal"), ("SalesAmountNZD", "decimal"),
    ("OrderCountDelta", "long"), ("TaxIncluded", "bool"), ("IsLate", "bool"),
]
LINE_FIELDS = [
    ("LineNumber", "int"), ("ProductKey", "long"), ("ProductCode", "string"),
    ("ProductName", "string"), ("Brand", "string"), ("BrandScopeId", "string"),
    ("PortfolioStatus", "string"), ("CategoryName", "string"),
    ("Channel", "string"), ("MarketCode", "string"),
    ("PackSize", "string"), ("QuantityUnit", "string"), ("StorageCondition", "string"),
    ("Quantity", "long"), ("UnitPrice", "decimal"), ("NetPrice", "decimal"), ("UnitCost", "decimal"),
    ("DiscountPercent", "int"), ("LineNetAmount", "decimal"), ("LineNetAmountNZD", "decimal"),
    ("CurrencyCode", "string"), ("ExchangeRate", "decimal"),
    ("BatchId", "string"), ("BrandSourceUrls", "dynamic"),
    ("OrderedQuantityDelta", "long"), ("DispatchedQuantityDelta", "long"),
    ("SoldQuantityDelta", "long"), ("SalesAmount", "decimal"), ("SalesAmountNZD", "decimal"),
]
LINE_CONTEXT_NAMES = {
    "SchemaVersion", "IsSynthetic", "CatalogAsOf", "SimulationRunId", "EventId",
    "EventSequence", "EventType", "EventTime", "ClockMode", "OrderKey", "OrderNumber",
    "OrderStatus", "OrderDate", "ExpectedDeliveryDate", "DispatchDate", "DeliveryDate",
    "DispatchId", "CustomerKey", "CustomerName", "StoreKey", "StoreName", "WarehouseId",
    "Country", "City", "Latitude", "Longitude", "ReportingCurrencyCode", "IsLate",
}
LINE_CONTEXT = [field for field in EVENT_FIELDS if field[0] in LINE_CONTEXT_NAMES]
EVENT_BASE_FIELDS = EVENT_FIELDS
DESTINATION_FIELDS = [
    ("DestinationId", "string"), ("DestinationName", "string"), ("DestinationType", "string"),
    ("DestinationCountryCode", "string"), ("DestinationCity", "string"), ("DestinationRegion", "string"),
    ("DestinationLatitude", "real"), ("DestinationLongitude", "real"), ("SupermarketChain", "string"),
    ("IsNZSupermarketDelivery", "bool"), ("IsDispatchedToNZSupermarket", "bool"),
]
EVENT_FIELDS = EVENT_BASE_FIELDS + DESTINATION_FIELDS
AUDIT_FIELDS = [("RawIngestedAt", "datetime"), ("ProcessedAt", "datetime")]
REJECT_FIELDS = [
    ("RejectionKey", "string"), ("SimulationRunId", "guid"), ("EventId", "guid"),
    ("EventTime", "datetime"), ("ValidationError", "string"),
    ("RawIngestedAt", "datetime"), ("ProcessedAt", "datetime"), ("Payload", "dynamic"),
]
UNIX_FIELDS = {"OrderDate", "ExpectedDeliveryDate", "DispatchDate", "DeliveryDate"}
TABLES = {
    EVENT_TABLE: EVENT_BASE_FIELDS + AUDIT_FIELDS + DESTINATION_FIELDS,
    LINE_TABLE: LINE_CONTEXT + LINE_FIELDS + AUDIT_FIELDS + DESTINATION_FIELDS,
    REJECT_TABLE: REJECT_FIELDS,
}

CLASSIFY = r"""
FonterraSalesRaw
| extend RawIngestedAt=datetime(null)
| extend _Lines=iff(gettype(Payload.lines) == "array" and array_length(Payload.lines) > 0, Payload.lines, dynamic([null]))
| mv-apply _Line=_Lines to typeof(dynamic) on (
    extend _Quantity=todecimal(tostring(_Line.Quantity)), _LineNumber=todecimal(tostring(_Line.LineNumber)),
           _Net=todecimal(tostring(_Line.NetPrice)), _Amount=todecimal(tostring(_Line.LineNetAmount)),
           _NZD=todecimal(tostring(_Line.LineNetAmountNZD)),
           _Sales=todecimal(tostring(_Line.SalesAmount)), _SalesNZD=todecimal(tostring(_Line.SalesAmountNZD))
    | extend _Bad=isnull(_Quantity) or isnull(tolong(_Quantity)) or _Quantity <= 0 or _Quantity != tolong(_Quantity)
        or isnull(_LineNumber) or isnull(toint(_LineNumber)) or _LineNumber < 1 or _LineNumber != toint(_LineNumber)
        or isnull(_Net) or _Net < 0 or isnull(_Amount) or _Amount != _Net * _Quantity
        or isnull(_NZD) or _NZD < 0 or isnull(_Sales) or isnull(_SalesNZD)
        or isnull(tolong(_Line.ProductKey)) or isempty(tostring(_Line.ProductCode))
        or isempty(tostring(_Line.CategoryName)) or isempty(tostring(_Line.QuantityUnit))
        or isnull(todecimal(tostring(_Line.UnitPrice))) or isnull(todecimal(tostring(_Line.UnitCost)))
        or isnull(todecimal(tostring(_Line.ExchangeRate))) or todecimal(tostring(_Line.ExchangeRate)) <= 0
        or isnull(toint(_Line.DiscountPercent))
        or isnull(tolong(_Line.OrderedQuantityDelta)) or isnull(tolong(_Line.DispatchedQuantityDelta))
        or isnull(tolong(_Line.SoldQuantityDelta))
        or tolong(_Line.OrderedQuantityDelta) != iff(tostring(Payload.EventType) == "ORDER_RECEIVED", tolong(_Quantity), long(0))
        or tolong(_Line.DispatchedQuantityDelta) != iff(tostring(Payload.EventType) == "ORDER_DISPATCHED", tolong(_Quantity), long(0))
        or tolong(_Line.SoldQuantityDelta) != iff(tostring(Payload.EventType) == "SALE_COMPLETED", tolong(_Quantity), long(0))
        or tostring(_Line.CurrencyCode) != tostring(Payload.CurrencyCode)
        or tostring(_Line.BrandScopeId) != tostring(Payload.BrandScopeId)
        or _Sales != iff(tostring(Payload.EventType) == "SALE_COMPLETED", _Amount, decimal(0))
        or _SalesNZD != iff(tostring(Payload.EventType) == "SALE_COMPLETED", _NZD, decimal(0))
    | summarize _BadLines=countif(_Bad), _LineCount=count(), _DistinctNumbers=count_distinct(_LineNumber),
                _NetTotal=sum(_Amount), _NZDTotal=sum(_NZD), _SalesTotal=sum(_Sales), _SalesNZDTotal=sum(_SalesNZD)
)
| extend ValidationError=case(
    coalesce(tobool(Payload.InfrastructureProbe), false), "Infrastructure probe excluded from business tables",
    tostring(Payload.SchemaVersion) !in ("1.0", "1.1"), "Unsupported or missing SchemaVersion",
    tostring(Payload.SchemaVersion) == "1.1" and (
        isempty(tostring(Payload.DestinationId)) or isempty(tostring(Payload.DestinationName))
        or tostring(Payload.DestinationType) !in ("Supermarket", "RetailOutlet", "FoodserviceCustomer", "Manufacturer")
        or isempty(tostring(Payload.DestinationCity)) or tostring(Payload.DestinationCountryCode) != tostring(Payload.MarketCode)
        or tostring(Payload.DestinationCity) != tostring(Payload.City)
        or isnull(toreal(Payload.Latitude)) or isnull(toreal(Payload.Longitude))
        or toreal(Payload.DestinationLatitude) != toreal(Payload.Latitude)
        or toreal(Payload.DestinationLongitude) != toreal(Payload.Longitude)
        or isnull(toreal(Payload.DestinationLatitude)) or abs(toreal(Payload.DestinationLatitude)) > 90
        or isnull(toreal(Payload.DestinationLongitude)) or abs(toreal(Payload.DestinationLongitude)) > 180
        or isnull(tobool(Payload.IsNZSupermarketDelivery)) or isnull(tobool(Payload.IsDispatchedToNZSupermarket))
        or tobool(Payload.IsNZSupermarketDelivery) != (tostring(Payload.DestinationType) == "Supermarket" and tostring(Payload.DestinationCountryCode) == "NZ")
        or tobool(Payload.IsDispatchedToNZSupermarket) != (tobool(Payload.IsNZSupermarketDelivery) and isnotnull(Payload.DispatchDate))
        or (tobool(Payload.IsNZSupermarketDelivery) and (
            isempty(tostring(Payload.SupermarketChain)) or isempty(tostring(Payload.DestinationRegion))
            or tostring(Payload.CurrencyCode) != "NZD" or tostring(Payload.Channel) != "Retail"))
        ), "Invalid delivery destination or NZ supermarket dispatch flag",
    isnull(toguid(Payload.EventId)) or isnull(toguid(Payload.SimulationRunId)) or isnull(toguid(Payload.OrderKey)), "Invalid event, run or order identifier",
    isnull(todatetime(Payload.EventTime)) or isnull(unixtime_seconds_todatetime(toreal(Payload.OrderDate)))
        or isnull(unixtime_seconds_todatetime(toreal(Payload.ExpectedDeliveryDate)))
        or isnull(todatetime(Payload.CatalogAsOf)), "Invalid required timestamp",
    (isnotnull(Payload.DispatchDate) and isnull(unixtime_seconds_todatetime(toreal(Payload.DispatchDate))))
        or (isnotnull(Payload.DeliveryDate) and isnull(unixtime_seconds_todatetime(toreal(Payload.DeliveryDate))))
        or (tostring(Payload.EventType) in ("ORDER_DISPATCHED", "ORDER_DELIVERED", "SALE_COMPLETED") and isnull(Payload.DispatchDate))
        or (tostring(Payload.EventType) in ("ORDER_DELIVERED", "SALE_COMPLETED") and isnull(Payload.DeliveryDate)), "Invalid actual dispatch or delivery timestamp",
    tostring(Payload.EventType) !in ("ORDER_RECEIVED", "ORDER_DISPATCHED", "ORDER_DELIVERED", "SALE_COMPLETED", "ORDER_CANCELLED"), "Unknown lifecycle event type",
    isnull(toint(Payload.EventSequence)) or toint(Payload.EventSequence) != case(
        tostring(Payload.EventType) == "ORDER_RECEIVED", 1,
        tostring(Payload.EventType) in ("ORDER_DISPATCHED", "ORDER_CANCELLED"), 2,
        tostring(Payload.EventType) == "ORDER_DELIVERED", 3, 4), "Invalid lifecycle sequence",
    tolong(Payload.OrderCountDelta) != iff(tostring(Payload.EventType) == "ORDER_RECEIVED", long(1), long(0)), "Invalid order-count delta",
    isempty(tostring(Payload.CurrencyCode)) or isempty(tostring(Payload.BrandScopeId))
        or isempty(tostring(Payload.ReportingCurrencyCode)), "Missing currency or brand scope",
    isnull(todecimal(tostring(Payload.ExchangeRate))) or todecimal(tostring(Payload.ExchangeRate)) <= 0
        or isnull(todecimal(tostring(Payload.OrderNetAmount))) or isnull(todecimal(tostring(Payload.OrderNetAmountNZD)))
        or isnull(todecimal(tostring(Payload.SalesAmount))) or isnull(todecimal(tostring(Payload.SalesAmountNZD)))
        or isnull(tolong(Payload.CustomerKey)) or isnull(tolong(Payload.StoreKey))
        or isnull(tolong(Payload.OrderCountDelta)) or isnull(tobool(Payload.IsSynthetic))
        or isnull(tobool(Payload.TaxIncluded)) or isnull(tobool(Payload.IsLate)), "Invalid required scalar value",
    isnull(array_length(Payload.lines)) or array_length(Payload.lines) == 0, "Missing or empty lines array",
    _BadLines > 0 or _LineCount != _DistinctNumbers, "Invalid line values, amounts or duplicate line numbers",
    _NetTotal != todecimal(tostring(Payload.OrderNetAmount)) or _NZDTotal != todecimal(tostring(Payload.OrderNetAmountNZD))
        or _SalesTotal != todecimal(tostring(Payload.SalesAmount)) or _SalesNZDTotal != todecimal(tostring(Payload.SalesAmountNZD)), "Order and line totals do not reconcile",
    "")
| project Payload, RawIngestedAt, ValidationError
""".strip()


def cast(name, kind, source="Payload"):
    field = f"{source}.{name}"
    if name in UNIX_FIELDS and source == "Payload":
        return f"unixtime_seconds_todatetime(toreal({field}))"
    if kind == "decimal":
        return f"todecimal(tostring({field}))"
    if kind == "dynamic":
        return field
    expression = f"to{kind}({field})" if kind != "string" else f"tostring({field})"
    if source == "Payload" and name in dict(DESTINATION_FIELDS):
        missing = '""' if kind == "string" else f"{kind}(null)"
        return f'iff(tostring(Payload.SchemaVersion) == "1.1", {expression}, {missing})'
    return expression


def projection(fields, source="Payload"):
    return [f"{name}={cast(name, kind, source)}" for name, kind in fields]


def project(expressions):
    return "| project\n    " + ",\n    ".join(expressions)


FUNCTIONS = {
    "FonterraClassifyRaw": CLASSIFY,
    "FonterraParseOrderEvents": (
        'FonterraClassifyRaw()\n| where isempty(ValidationError)\n'
        + project(projection(EVENT_BASE_FIELDS) + ["RawIngestedAt", "ProcessedAt=now()"]
                  + projection(DESTINATION_FIELDS))
    ),
    "FonterraParseOrderLines": (
        'FonterraClassifyRaw()\n| where isempty(ValidationError)\n| mv-expand Line=Payload.lines\n'
        + project(projection(LINE_CONTEXT) + projection(LINE_FIELDS, "Line")
                  + ["RawIngestedAt", "ProcessedAt=now()"] + projection(DESTINATION_FIELDS))
    ),
    "FonterraParseRejected": (
        'FonterraClassifyRaw()\n| where isnotempty(ValidationError)\n'
        + project([
            "RejectionKey=hash_sha256(tostring(Payload))",
            "SimulationRunId=toguid(Payload.SimulationRunId)", "EventId=toguid(Payload.EventId)",
            "EventTime=todatetime(Payload.EventTime)", "ValidationError",
            "RawIngestedAt", "ProcessedAt=now()", "Payload",
        ])
    ),
}
TRANSFORMS = {
    EVENT_TABLE: "FonterraParseOrderEvents",
    LINE_TABLE: "FonterraParseOrderLines",
    REJECT_TABLE: "FonterraParseRejected",
}
KEYS = {
    EVENT_TABLE: ["SimulationRunId", "EventId"],
    LINE_TABLE: ["SimulationRunId", "EventId", "LineNumber"],
    REJECT_TABLE: ["RejectionKey"],
}
VIEWS = {
    "FonterraOrderEventsUnique": (
        EVENT_TABLE, f"{EVENT_TABLE} | summarize arg_max(ProcessedAt, *) by SimulationRunId, EventId"
    ),
    "FonterraOrderLinesUnique": (
        LINE_TABLE, f"{LINE_TABLE} | summarize arg_max(ProcessedAt, *) by SimulationRunId, EventId, LineNumber"
    ),
    "FonterraOrdersCurrent": (
        EVENT_TABLE, f"{EVENT_TABLE} | summarize arg_max(EventSequence, *) by SimulationRunId, OrderKey"
    ),
}


def table_command(name):
    columns = ",\n    ".join(f"{column}:{kind}" for column, kind in TABLES[name])
    return f".create-merge table {name} (\n    {columns}\n)"


def function_command(name):
    return f".create-or-alter function with (folder='Fonterra/Typed', docstring='{OWNER}') {name}() {{\n{FUNCTIONS[name]}\n}}"


def view_command(name):
    source, query = VIEWS[name]
    return (
        f".create async ifnotexists materialized-view with (backfill=true, autoUpdateSchema=true, folder='Fonterra/Typed', "
        f"docString='{OWNER}') {name} on table {source} {{\n{query}\n}}"
    )


def update_policy(table):
    return [{
        "IsEnabled": True, "Source": RAW, "Query": f"{TRANSFORMS[table]}()",
        "IsTransactional": True, "PropagateIngestionProperties": False,
    }]


def policy_command(table):
    return f".alter table {table} policy update '{json.dumps(update_policy(table), separators=(',', ':'))}'"


def backfill_query(table):
    keys = ", ".join(KEYS[table])
    columns = ", ".join(name for name, _ in TABLES[table])
    return (
        f"{TRANSFORMS[table]}()\n| summarize arg_max(ProcessedAt, *) by {keys}\n"
        f"| join kind=leftanti ({table} | project {keys}) on {keys}\n| project {columns}"
    )


def render():
    parts = [
        "// Generated by python -m scripts.typed_sales_schema; do not edit independently.",
        "// Deploy using scripts.deploy_typed_sales: schema/policy preflight and async monitoring are required.",
        "// Source raw data and existing compatibility functions are not modified.",
    ]
    parts += [table_command(name) for name in TABLES]
    parts += [function_command(name) for name in FUNCTIONS]
    parts += [view_command(name) for name in VIEWS]
    parts += [policy_command(name) for name in TABLES]
    parts += [
        "// Backfill only absent immutable keys; concurrent live overlaps are removed by the Unique views.",
        *[f".set-or-append {name} <|\n{backfill_query(name)}" for name in TABLES],
    ]
    return "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "fabric" / "fonterra_typed.kql"
    path.write_text(render(), encoding="utf-8")
    print(f"Generated {path.name}")
