# Fonterra real-time sales notebook

[**FonterraSalesEmulator.ipynb**](notebooks/FonterraSalesEmulator.ipynb) is a self-contained
Microsoft Fabric notebook for `rayfin-3d-production-factory`. It extends the concept of the
[Retail Sales Jumpstart](https://jumpstart.fabric.microsoft.com/catalog/retail-sales/) with
linked incoming customer orders, dispatch, delivery and completed-sale events.

**Run all now sends to the connected Eventstream and KQL database.** The notebook retrieves
custom endpoint credentials at runtime using the caller's Fabric identity; no keys need to
be copied into the notebook. Set `MODE = "preview"` for an offline simulation instead.
All data is synthetic; there is no connection
to Fonterra's sales, inventory, ERP or product systems. Fabric execution still consumes
notebook capacity, so stop the session when finished.

## Brand coverage and ownership

Fonterra [completed the Mainland Group sale to Lactalis on 31 March 2026](https://www.fonterra.com/nz/en/our-stories/media/fonterra-completes-sale-of-mainland-group-to-lactalis.html).
The catalogue is ownership-aware as of **12 September 2026**, not an assertion that the
historical consumer portfolio is still Fonterra-owned.

| Mode | Included brands/scopes |
|---|---|
| Always enabled: current Fonterra | Anchor Food Professionals (Singapore foodservice), NZMP, Nutiani, Anchor (Greater China consumer) |
| Notebook default: `INCLUDE_NZ_SUPERMARKET_ORDERS = True` | Adds NZ consumer comparison scopes: Anchor NZ, Mainland, Kapiti, Chesdale, Fresh 'n Fruity |
| Corporate catalogue only | Farm Source, excluded from dairy transactions because it is a farmer-services brand |
| `INCLUDE_DIVESTED_BRANDS = True` adds comparison scopes | Anchor outside Greater China, Anlene, Anmum, Mainland, Perfect Italiano, Kapiti, Western Star, Bega (licensed), Chesdale, Fernleaf, Fresh 'n Fruity, Ratthi |

This covers the names in Fonterra's [current global brand page](https://www.fonterra.com/nz/en/our-co-operative/our-brands.html)
and the [successor's 12-brand consumer directory](https://www.mainlanddairy.com/en/brands.html).
It is **not an exhaustive global trademark, sub-brand, territory or SKU register**.
AFP regional operators differ after divestment. Anchor has separate ownership scopes.
Bega is a licensed-brand comparison, not a claim of Fonterra trademark ownership.

The catalogue includes foodservice dairy, ingredient powders/concentrates/fats/proteins,
casein, lactose, specialty/probiotic ingredients, consumer nutrition, cheese, butter,
cream, spreads and yoghurt categories. Generic dairy-assortment placeholders are used
where a precise current product range is unverified. Packs, prices, FX, routing, stock
batch labels and customer/outlet identifiers are invented, not official product/facility data.
Farm Source services, historical Australian Dairies/Duck River, unverified De Winkel,
and individual NZMP product trademarks are not simulated as separate dairy brands.
Brand/category source links and caveats are embedded in the notebook and catalogue.

## First run

1. Open `FonterraSalesEmulator` in the named Fabric workspace, or import the `.ipynb`.
2. Keep `MODE = "eventstream"` and `CONNECTION_MODE = "fabric"`, select the desired
   brand-scope option, and run all cells. A native `%pip` bootstrap ensures the Event Hubs
   SDK is available; Fabric restarts Python after library changes before parameters are defined.
   This setup cell may contact PyPI even for preview.
3. Inspect the acknowledged-send summary and query the KQL raw table. Default: 60 order
   arrivals, at most 240 lifecycle events, and a 120-second wall-clock scheduling cap.
   `MODE = "preview"` advances a virtual clock and does not publish any data.

The first product in each order rotates through the enabled brand/category catalogue.
Other lines stay in the same brand scope and currency. Short runs can have incomplete
coverage; the notebook reports the observed/available product counts.

The lifecycle is `ORDER_RECEIVED -> ORDER_DISPATCHED -> ORDER_DELIVERED -> SALE_COMPLETED`,
or `ORDER_RECEIVED -> ORDER_CANCELLED`. A configurable percentage of deliveries is late.
Demo delays are compressed seconds, not actual supply-chain lead times.
This models incoming customer orders, not supplier purchase orders or goods receipts.
It does not model inventory reservations, split shipments, refunds, or independent
retail sell-through after a wholesale sale.

### NZ supermarket destinations

The notebook enables **23 illustrative products**: 16 current-portfolio products and 7 NZ
consumer-comparison products. Set `INCLUDE_NZ_SUPERMARKET_ORDERS = False` with
`INCLUDE_DIVESTED_BRANDS = False` for current-portfolio-only generation. The reusable
Python API retains both flags as false by default. The global comparison flag includes NZ
retail routes too; the NZ flag is a selective addition, not an exclusion of global comparisons.

NZ retail orders replenish invented outlets labelled New World, PAK'nSAVE, Woolworths,
Four Square, FreshChoice and SuperValue, across Auckland, Wellington, Christchurch,
Hamilton, Tauranga and Dunedin. Outlet IDs/names begin with `SIM`; coordinates are city
centres, not real branches. **No actual retailer supply relationship or outlet is asserted.**
NZ consumer products retain `DivestedComparison` ownership labels. Ingredient, nutrition
and foodservice customers retain their separate international destination types.

Schema 1.1 adds destination ID/name/type/country, city/region/coordinates, supermarket chain
and two flags to both typed event and line tables:

| Flag | Meaning |
|---|---|
| `IsNZSupermarketDelivery` | Planned destination is an NZ supermarket, including received or subsequently cancelled orders |
| `IsDispatchedToNZSupermarket` | Actual `DispatchDate` exists for an NZ supermarket destination; remains true on delivered/sold snapshots |

Quantities are synthetic 12-120 selling units per NZ replenishment line. Count dispatches
only at `EventType == "ORDER_DISPATCHED"` in the deduplicated views; do not count the
dispatch flag again at delivery/sale. `DestinationId` and supermarket `StoreKey` are stable
for the same simulated outlet. Existing non-NZ quantities and currencies are unchanged.

## Connected Eventstream and Eventhouse

| Component | Name |
|---|---|
| Workspace | `rayfin-3d-production-factory` |
| Notebook | `FonterraSalesEmulator` |
| Eventstream | `FonterraSalesStream` |
| Custom endpoint source | `FonterraSalesSource` |
| Eventhouse | `FonterraEventhouse` |
| KQL database | `FonterraSales` |
| Raw table | `FonterraSalesRaw` (`Payload:dynamic`, full JSON envelope) |

The notebook discovers the workspace and Eventstream by exact name, reads the topology to
find `FonterraSalesSource`, and retrieves its **Event Hubs-compatible** connection string
with the [Fabric source-connection API](https://learn.microsoft.com/en-us/rest/api/fabric/eventstream/topology/get-eventstream-source-connection).
It uses the built-in `sempy.fabric.FabricRestClient`. The caller requires **read and write**
permissions on the Eventstream. IDs and current keys are resolved on each run; credential
responses are neither logged nor saved. The notebook does not create infrastructure.

Explicit alternatives are `CONNECTION_MODE = "key_vault"` with `KEY_VAULT_URL` /
`KEY_VAULT_SECRET_NAME`, or `"environment"` with `FONTERRA_EVENTSTREAM_CONNECTION_STRING`.
A failed Fabric lookup does not silently fall back to another credential source.
Never commit or print connection strings.

Fabric supplies semantic-link-sempy; the notebook bootstraps the Event Hubs SDK and
`websocket-client`, required by the AMQP-over-WebSockets transport.
For notebook jobs, pass `_inlineInstallationEnabled = True` to allow the setup cell.
For production scheduling, prefer a Fabric Environment containing a pinned SDK dependency.
`ORDERS_PER_SECOND` is an arrival
rate, not total events/sec. Pending orders are capped, sends use AMQP-over-WebSockets,
and the SDK has bounded retries. Interrupt the cell and stop the Fabric session to stop costs.
A send already in progress can outlast the scheduling duration by its network timeout/retry budget.
Unfinished orders are explicitly reported; no forced completion or silent data dropping occurs.
Producer state is in-memory, so restarting creates a new simulation, not a durable resume.

### Downstream contract

The notebook documents every field. It keeps familiar `OrderKey`, Unix-second dates,
`CustomerKey`, `StoreKey` and nested `lines[]`, but **the original Jumpstart's mapping and
sales queries are not directly compatible with lifecycle events**.

- Deduplicate on `EventId` before aggregation or expanding lines; delivery is at least once.
- Use `EventSequence` per `OrderKey` for current status.
- `OrderNetAmount` repeats on every lifecycle event. Revenue is only `SALE_COMPLETED`;
  `SalesAmount` / `SalesAmountNZD` are zero for every other event type.
- After `mv-expand lines`, sum **line** sales amounts, not repeated order-level amounts.
- Group local sales by `CurrencyCode`, or sum reporting amounts in NZD. FX is fixed
  synthetic NZD/local currency; do not truncate `ExchangeRate` with `tolong`.
- Use decimal monetary types. Line conversions round to cents before order summation.
- Keep `BrandScopeId` and `PortfolioStatus` to separate current, divested and licensed scopes.
- Quantities are selling units (bag, pack, tin, etc.); do not mix them as physical volume.

To check ingestion in `FonterraSales`, run:

```kql
FonterraSalesRaw
| where todatetime(Payload.EventTime) > ago(1h)
| extend EventId = tostring(Payload.EventId), EventTime = todatetime(Payload.EventTime)
| summarize arg_max(EventTime, *) by EventId
| summarize Events = count() by EventType = tostring(Payload.EventType)
```

Filter by the notebook's printed `SimulationRunId` to isolate a particular run.
The Eventstream destination preserves the entire JSON envelope. The existing
`FonterraSalesEvents()` and `FonterraSalesLines()` compatibility functions remain unchanged.
For typed analytics, use the tables and materialized views below instead. Raw events have
7-day retention and 1-day hot cache; Eventstream
retention is 1 day with Low throughput. These resources continue to exist after a notebook
run stops, so stopping the notebook alone does not remove all streaming/storage costs.

Raw-route schema is in `fabric/fonterra.kql` and provisioning code in
`scripts/provision_streaming.py`. Dashboard and Activator setup can be added afterwards.
This is a demo generator, not a 24/7 production ingestion service or accounting model.

## Typed tables and automatic JSON flattening

New arrivals in `FonterraSalesRaw` automatically populate these physical tables through
transactional KQL update policies. Existing retained raw events have also been backfilled.
The notebook and Eventstream still write only to the raw table; no producer changes are needed.

| Object | Type and grain | Purpose |
|---|---|---|
| `FonterraOrderEvents` | Table: one row per lifecycle-event arrival, 55 columns | Typed order header, explicit destination/dispatch flags, ownership, dates and monetary snapshots |
| `FonterraOrderLines` | Table: one row per event/line arrival, 70 columns | Expanded product/category, destination, packaging, quantity, price, cost, revenue and stage-specific quantity deltas |
| `FonterraSalesRejected` | Table: one row per rejected arrival, 8 columns | Original payload and explicit validation reason; includes infrastructure probes |
| `FonterraOrderEventsUnique` | Materialized view: `(SimulationRunId, EventId)` | Retry-safe event analytics |
| `FonterraOrderLinesUnique` | Materialized view: `(SimulationRunId, EventId, LineNumber)` | Retry-safe product sales and dispatch analytics |
| `FonterraOrdersCurrent` | Materialized view: `(SimulationRunId, OrderKey)` | Latest order state by highest `EventSequence`, not arrival order |

Physical tables are append-only and may contain at-least-once delivery duplicates.
**Use the `Unique` views for totals.** Query views by name to include their live delta;
`materialized_view(...)` alone may omit rows not yet materialized.
Events are immutable by event ID. A new simulation should use a new run ID.
The latest-order view is a rolling operational view, not permanent ERP state.

GUID identifiers use `guid`; timestamps use `datetime` (Unix seconds are explicitly
converted); monetary values and FX use `decimal`; quantities/keys use integer types;
coordinates use `real`; flags use `bool`. Missing actual dispatch/delivery dates remain null.
KQL string columns represent missing optional text, such as cancellation reason, as empty strings.
`BrandSourceUrls` is intentionally retained as a small `dynamic` lineage array;
the order's `lines[]` is expanded into individual rows.

`ProcessedAt` is the transformation time, not the business event time.
`RawIngestedAt` is deliberately nullable/unpopulated: Kusto prohibits `ingestion_time()` in
transactional streaming update-policy queries. Query the unchanged raw table's
`ingestion_time()` by event/run ID if that source timestamp is needed. Streaming ingestion
has not been disabled to work around this restriction.

Validation accepts simulator schema versions **1.0 and 1.1**. Version 1.1 requires consistent
destination fields and NZ dispatch flags. Version 1.0 destination text remains empty and
destination coordinates/booleans remain null; historical destinations are never invented.
Missing IDs/timestamps,
unsupported versions, invalid/duplicate line numbers, nonpositive/fractional quantities,
inconsistent line/order amounts and invalid lifecycle deltas are routed to rejection.
An invalid line rejects the whole event so event/line tables remain consistent; no line
is silently discarded. Infrastructure probes are retained in rejection rather than business totals.
This validates the demo contract, not an enterprise product master or accounting system.

All new tables and views use 7-day retention and 1-day hot cache. Raw data and existing
helper functions are preserved. Backfill appends only absent keys; concurrent backfill/live
overlap remains safe in the deduplicated views. Data already expired from raw retention
cannot be recovered by backfill.

Example: sales by brand and category, in reporting currency NZD:

```kql
FonterraOrderLinesUnique
| where EventTime > ago(1d) and EventType == "SALE_COMPLETED"
| summarize SalesNZD=sum(SalesAmountNZD)
    by Brand, BrandScopeId, PortfolioStatus, CategoryName
| order by SalesNZD desc
```

`SalesAmount` in the line table is **line-level** revenue; order-level snapshot totals are
deliberately not copied into it. Quantities retain their selling-unit labels, so don't sum
bags, tins and cartons as though they are the same physical unit.

Full ordered schemas and transformations: `fabric/fonterra_typed.kql`.
Additional examples: `fabric/fonterra_queries.kql`.
Regenerate and deploy safely using name-based discovery:

```powershell
python -m scripts.typed_sales_schema
python -m scripts.deploy_typed_sales --workspace rayfin-3d-production-factory --database FonterraSales
python -m scripts.deploy_typed_sales --workspace rayfin-3d-production-factory --database FonterraSales --apply
```

The default command is read-only. Deployment preflights name/type/schema/policy conflicts,
validates projection column order before attaching update policies, and monitors asynchronous
materialized-view creation without blindly retrying creation. Different existing definitions
are preserved rather than overwritten; function changes during an unfinished initial setup
are allowed only for owned functions when none of the target update policies are installed.

For an existing v1 deployment, explicitly upgrade before publishing the schema-1.1 notebook:

```powershell
python -m scripts.deploy_typed_sales --workspace rayfin-3d-production-factory --database FonterraSales --upgrade-v1
python -m scripts.deploy_typed_sales --workspace rayfin-3d-production-factory --database FonterraSales --upgrade-v1 --apply
```

The immutable `fabric/fonterra_typed_v1_manifest.json` identifies the managed baseline.
The upgrade checks known function hashes and exact old/new schemas, enables materialized-view
schema propagation, pauses only the three managed typed update policies, appends destination
columns after the existing columns, replaces the owned transforms, validates projection order,
restores transactional policies, and backfills missed raw keys. Raw streaming stays enabled.
On interruption, the error includes recovery instructions: fix the cause and rerun the same
upgrade command; don't manually enable a policy with an incompatible schema. Normal deployment
and migration preserve data; neither command silently resets the demo.

## Development

`src/fonterra_simulator.py` is the source of truth. The build script embeds it into the
notebook, so the imported notebook needs no companion files. Regenerate after source edits:

```powershell
python .\scripts\build_notebook.py
python -m unittest discover -s .\tests -v
```

Core tests need only Python's standard library. Live publishing requires
`requirements-streaming.txt`. The repository contains no workspace IDs, secrets or
automatic infrastructure provisioning.