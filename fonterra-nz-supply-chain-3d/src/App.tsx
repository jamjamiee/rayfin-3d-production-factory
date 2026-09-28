import { useEffect, useMemo, useRef, useState } from 'react';
import { cities, chains, eventNames, lineNames, productionLines, statuses, type Line, type Order, type Selection } from './contract';
import { ageLabel, emptyFilters, filterOrders, formatTime, integer, isQuiet, laneSummary, latestLines, money, quantityGroups, type Filters } from './data';
import { FactoryScene, SceneBoundary } from './FactoryScene';
import { useSnapshot } from './useSnapshot';

const NOTEBOOK_URL = 'https://app.fabric.microsoft.com/groups/d93a2e35-f91d-4e31-a905-d0c503821af7/synapsenotebooks/0ebb7813-8536-412e-9b57-8fba5cdae76c';
const APP_URL = 'https://app.fabric.microsoft.com/groups/d93a2e35-f91d-4e31-a905-d0c503821af7/appbackends/8d68a675-6533-476f-94e6-e74e45c997a9?ctid=ccc797fd-cf82-4d98-ab6a-f600581bb12a';

function StatusBadge({ status }: { status: Order['status'] }) {
  return <span className={`status-badge status-${status.toLowerCase()}`}><i aria-hidden="true" />{status}</span>;
}
function Timestamp({ value }: { value: string | null }) {
  return value ? <time dateTime={value} title={`${value} · Pacific/Auckland`}>{formatTime(value)}</time> : <span className="muted">Not recorded</span>;
}
function useReducedMotion() {
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return reduced;
}

function OrderDetails({ order, lines, onClose }: { order: Order; lines: Line[]; onClose: () => void }) {
  const detailRef = useRef<HTMLElement>(null);
  useEffect(() => { detailRef.current?.focus(); }, [order.id]);
  return <section ref={detailRef} tabIndex={-1} className="order-detail" aria-label={`Details for ${order.number}`}>
    <div className="section-title">
      <div><p className="eyebrow">Order inspection</p><h3>{order.number}</h3></div>
      <button onClick={onClose} aria-label="Close order details" className="icon-button">×</button>
    </div>
    <div className="detail-summary">
      <StatusBadge status={order.status} />
      <span className="portfolio-tag">{order.portfolioStatus}</span>
      {order.isLate && <span className="late-flag">Late order</span>}
    </div>
    <h4>{order.chain} <span className="muted">/</span> {order.city}</h4>
    <p className="muted">{order.destination} · {order.region}</p>
    <p className="small-note">Synthetic destination; no real outlet, customer or plant relationship is asserted.</p>
    <dl className="detail-facts">
      <div><dt>Brand</dt><dd>{order.brand}</dd></div>
      <div><dt>Brand scope</dt><dd>{order.brandScope}</dd></div>
      <div><dt>Order net · NZD</dt><dd>{money(order.netNZD)}</dd></div>
      <div><dt>Sales · NZD</dt><dd>{money(order.salesNZD)}</dd></div>
    </dl>
    <div className="timeline" aria-label="Recorded order timestamps">
      <div><span className="timeline-dot" /><p>Received<Timestamp value={order.orderedAt} /></p></div>
      <div><span className={`timeline-dot ${!order.dispatchedAt ? 'not-recorded' : ''}`} /><p>Dispatched<Timestamp value={order.dispatchedAt} /></p></div>
      <div><span className={`timeline-dot ${!order.deliveredAt ? 'not-recorded' : ''}`} /><p>Delivered<Timestamp value={order.deliveredAt} /></p></div>
      <div><span className="timeline-dot not-recorded" /><p>Expected delivery<Timestamp value={order.expectedAt} /></p></div>
    </div>
    <div className="detail-lines-title"><h4>Latest-event line items</h4><span className="count-badge">{lines.length}</span></div>
    <p className="small-note">Only rows matching the selected order’s latest event. The response is capped at 600 line items; no missing quantities are inferred.</p>
    {lines.length === 0 ? <p className="empty-inline">No line items in this snapshot for this order.</p> :
      <div className="line-items">{lines.map((line) => <article className="line-item" key={line.id}>
        <div className="line-item-heading"><span className="mono">#{line.number} · {line.productCode}</span><strong>{money(line.netNZD)}</strong></div>
        <h5>{line.product}</h5>
        <div className="quantity">{integer(line.quantity)} {line.unit} <span>· {line.pack}</span></div>
        <div className="line-meta"><span>{line.storage}</span><span>{lineNames[line.productionLine]} · illustrative</span></div>
        <p className="small-note">{line.brand} · {line.portfolioStatus}</p>
        <p className="small-note mono">Batch {line.batchId}</p>
      </article>)}</div>}
    <details className="provenance">
      <summary>Data provenance & identifiers</summary>
      <dl>
        <dt>Order ID (run / order)</dt><dd>{order.id}</dd>
        <dt>Latest event ID</dt><dd>{order.eventId}</dd>
        <dt>Sequence</dt><dd>{order.sequence}</dd>
        <dt>Latest event time</dt><dd><Timestamp value={order.eventTime} /></dd>
        <dt>Destination coordinates (synthetic)</dt><dd>{order.latitude}, {order.longitude}</dd>
      </dl>
    </details>
  </section>;
}

export function App() {
  const { snapshot, error, refreshing, now, stale, lastSuccessAt, retry } = useSnapshot();
  const [selection, setSelection] = useState<Selection>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light');
  const [paused, setPaused] = useState(false);
  const [showAllEvents, setShowAllEvents] = useState(false);
  const reducedMotion = useReducedMotion();
  const lines = useMemo(() => snapshot ? latestLines(snapshot) : [], [snapshot]);
  const orders = snapshot?.orders ?? [];
  const quiet = isQuiet(snapshot, now);
  const activeOrders = orders.filter((order) => order.status === 'Received').length;
  const animate = !!snapshot && !error && !stale && !quiet && !paused && !reducedMotion && activeOrders > 0;
  const filteredOrders = useMemo(() => filterOrders(snapshot?.orders ?? [], lines, filters), [snapshot, lines, filters]);
  const selectedOrder = selection?.kind === 'order' ? orders.find((order) => order.id === selection.id) : undefined;
  const selectedLines = selectedOrder ? lines.filter((line) => line.orderId === selectedOrder.id) : [];
  const truncated = !!snapshot && snapshot.totals.totalOrders > orders.length;
  const lineCapped = !!snapshot && snapshot.lines.length >= 600;
  const anyFilter = Object.values(filters).some(Boolean);
  const activity = useMemo(() => [...new Map((snapshot?.activity ?? []).map((event) => [event.id, event])).values()]
    .sort((a, b) => Date.parse(b.eventTime) - Date.parse(a.eventTime)), [snapshot]);

  function select(value: Selection) {
    setSelection(value);
    if (!value) setFilters((previous) => ({ ...previous, lane: '', city: '' }));
    if (value?.kind === 'lane') setFilters((previous) => ({ ...previous, lane: value.id, city: '' }));
    if (value?.kind === 'dock') setFilters((previous) => ({ ...previous, city: value.id, lane: '' }));
  }
  function resetFilters() { setFilters(emptyFilters); if (selection?.kind !== 'order') setSelection(null); }
  function changeFilter(key: keyof Filters, value: string) { setFilters((current) => ({ ...current, [key]: value })); }
  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    setTheme(next);
  }
  const streamLabel = !snapshot ? (error ? 'Connection unavailable' : 'Connecting to Fabric') : stale ? 'Stale snapshot' : quiet ? 'Stream quiet' : 'Recent order events';

  return <>
    <a href="#orders" className="skip-link">Skip to order ledger</a>
    <header className="app-header">
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 36 36"><path d="M4 26V14l9 5V9l9 5V4l10 6v20H4Z" /><path d="M10 25h2m5 0h2m5 0h2" /></svg></span>
        <div><div className="header-eyebrow">Fonterra <span>/</span> New Zealand</div><h1>Supply Chain <span>3D</span></h1></div>
        <span className="environment-tag">SYNTHETIC OPERATIONS</span>
      </div>
      <div className="header-actions">
        <a className="notebook-link" href={NOTEBOOK_URL} target="_blank" rel="noreferrer">Source notebook <span aria-hidden="true">↗</span></a>
        <button className="theme-button" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? '☼' : '◐'}</button>
        <span className="platform-badge">FABRIC <span>×</span> RAYFIN</span>
      </div>
    </header>

    <main>
      <div className="context-bar">
        <p><strong>Synthetic portfolio comparison.</strong> NZ consumer brands were divested to Lactalis on 31 March 2026. Portfolio labels are retained; no real customer, outlet or plant relationship is asserted.</p>
        <span className="context-id">NZ / 24H</span>
      </div>
      <section className="workspace-heading" aria-label="Workspace status">
        <div><p className="eyebrow"><span className="accent-rule" />Factory intelligence / order-driven view</p><h2>From category to destination.</h2></div>
        <div className="connection-block">
          <div className={`connection-status ${stale || error ? 'is-warning' : quiet ? 'is-quiet' : 'is-recent'}`} role="status">
            <span className="connection-dot" />{streamLabel}
          </div>
          <span className="mono small-note">{snapshot ? `Last event ${ageLabel(snapshot.totals.lastEventAt, now)}` : 'Read-only snapshot · 5s polling'}</span>
        </div>
      </section>

      {error && <div className="notice error-notice" role="alert">
        <div><strong>{error.kind === 'host' ? 'Open app in Fabric' : error.kind === 'auth' ? 'Authentication required' : error.kind === 'contract' ? 'Snapshot format error' : 'Snapshot unavailable'}</strong>
          <p>{error.message} {snapshot ? 'Showing last good data, marked stale. No data is being invented.' : 'No fallback orders are loaded.'}
            {error.kind === 'auth' ? ' Sign in through the host application or ask its administrator to restore access.' : ''}</p></div>
        {error.kind === 'host'
          ? <a href={APP_URL} target="_blank" rel="noopener noreferrer">Open app in Fabric</a>
          : <button onClick={retry} disabled={refreshing}>{refreshing ? 'Retrying…' : 'Retry connection'}</button>}
      </div>}
      {stale && !error && <div className="notice stale-notice" role="status"><strong>Snapshot is stale.</strong> The server’s snapshot is over 30 seconds old. Values below are last known data; illustrative motion is paused.</div>}

      <section className="metrics" aria-label="24-hour window metrics">
        {[
          { label: 'Awaiting dispatch', value: snapshot && integer(snapshot.totals.awaitingDispatch), note: 'Received orders', icon: '01' },
          { label: 'In transit', value: snapshot && integer(snapshot.totals.inTransit), note: 'Recorded dispatches', icon: '02' },
          { label: 'Delivered', value: snapshot && integer(snapshot.totals.delivered), note: 'Delivered / sold orders', icon: '03' },
          { label: 'Sales · NZD', value: snapshot && money(snapshot.totals.salesNZD), note: 'Recorded sales, not production', icon: '$' },
        ].map((metric) => <article className="metric" key={metric.label}>
          <div className="metric-label">{metric.label}<span className="metric-icon">{metric.icon}</span></div>
          <strong className={metric.value ? '' : 'metric-pending'}>{metric.value ?? '—'}</strong>
          <span className="metric-note">{stale ? 'STALE · ' : ''}{metric.note}</span>
        </article>)}
        <article className="metric event-metric">
          <div className="metric-label">Latest event<span className="metric-icon">↳</span></div>
          <strong>{snapshot ? ageLabel(snapshot.totals.lastEventAt, now) : '—'}</strong>
          <span className="metric-note">{snapshot?.totals.lastEventAt ? <Timestamp value={snapshot.totals.lastEventAt} /> : 'Waiting for ingested events'}</span>
        </article>
      </section>

      <div className="main-grid">
        <section className="factory-panel panel" aria-labelledby="factory-title">
          <div className="panel-heading">
            <div><p className="eyebrow">01 / Operational schematic</p><h3 id="factory-title">The factory floor</h3></div>
            <span className="outline-tag">ILLUSTRATIVE · NOT TELEMETRY</span>
          </div>
          <div className="factory-disclaimer"><span aria-hidden="true">ⓘ</span><p>Illustrative category assignments; no manufacturing telemetry is recorded. Geometry, conveyors and trucks are schematic—not measured machine activity or actual units produced.</p></div>
          <SceneBoundary><FactoryScene orders={orders} lines={lines} selection={selection} onSelect={select} motion={animate} theme={theme} /></SceneBoundary>
          <div className="motion-strip">
            <span><span className={`motion-indicator ${animate ? 'moving' : ''}`} />{!snapshot ? 'Static factory · awaiting data' : stale ? 'Static · snapshot stale' : quiet ? 'Static · stream quiet' : reducedMotion ? 'Static · reduced motion' : paused ? 'Illustrative motion paused' : activeOrders === 0 ? 'Static · no received orders in loaded list' : 'Illustrative motion · received-order assignments only'}</span>
            <button onClick={() => setPaused(!paused)} disabled={reducedMotion} aria-pressed={paused}>{paused ? 'Enable motion' : 'Pause motion'}</button>
          </div>
          <div className="lanes" aria-label="Illustrative processing lanes">
            {productionLines.map((lane, index) => {
              const summary = laneSummary(lane, orders, lines);
              const chosen = selection?.kind === 'lane' && selection.id === lane;
              return <button key={lane} className={`lane-card ${chosen ? 'selected' : ''}`} aria-pressed={chosen} onClick={() => select(chosen ? null : { kind: 'lane', id: lane })}>
                <span className="lane-number">L0{index + 1}<span className="lane-symbol" aria-hidden="true">{['▥', '▧', '▤', '▨'][index]}</span></span>
                <strong>{lineNames[lane]}</strong>
                <span>{snapshot ? integer(summary.lineItems) : '—'} <span>line items</span></span>
                <small>{snapshot ? summary.awaiting : '—'} received orders · illustrative</small>
              </button>;
            })}
          </div>
          <div className="dispatch-heading"><p className="eyebrow">Dispatch docks / synthetic destinations</p><span>Counts from loaded orders</span></div>
          <div className="dock-list" aria-label="Dispatch destination docks">
            {cities.map((city, index) => {
              const chosen = selection?.kind === 'dock' && selection.id === city;
              const total = orders.filter((order) => order.city === city && order.status === 'Dispatched').length;
              return <button key={city} className={`dock-button ${chosen ? 'selected' : ''}`} aria-pressed={chosen} onClick={() => select(chosen ? null : { kind: 'dock', id: city })}>
                <span className="mono">{String(index + 1).padStart(2, '0')}</span><strong>{city}</strong><span>{snapshot ? total : '—'} in transit</span>
              </button>;
            })}
          </div>
          <p className="panel-footnote">Dock highlights show last recorded status—not current vehicle movement. Unfinished orders can remain when the notebook stops. Category and dock counts use only the loaded order list, not the full 24h window. Quantities are never combined across incompatible products, units or packs.</p>
        </section>

        <aside className="right-rail" aria-label="Selection and event details">
          <section className="panel selection-panel">
            {selectedOrder ? <OrderDetails order={selectedOrder} lines={selectedLines} onClose={() => setSelection(null)} /> : <>
              <div className="panel-heading"><div><p className="eyebrow">02 / Inspection desk</p><h3>{selection?.kind === 'lane' ? lineNames[selection.id] : selection?.kind === 'dock' ? `${selection.id} dock` : 'Order intelligence'}</h3></div><span className="selection-glyph" aria-hidden="true">⌖</span></div>
              <div className="inspection-body">
                {selection?.kind === 'order' ? <div className="empty-inline">This order is no longer in the latest 200-order list. Select a currently loaded order to inspect its latest event.</div> : selection?.kind === 'lane' ? <>
                  <span className="outline-tag">ILLUSTRATIVE ASSIGNMENT</span>
                  <p>Orders are assigned here by product category. This does not report machine state, production throughput or completion.</p>
                  <div className="inspector-counts"><div><strong>{laneSummary(selection.id, orders, lines).orders.length}</strong><span>loaded orders</span></div><div><strong>{laneSummary(selection.id, orders, lines).lineItems}</strong><span>line items</span></div></div>
                  <ul className="quantity-groups">{quantityGroups(lines.filter((line) => line.productionLine === selection.id)).map((group) => <li key={group.key}><span>{group.product}<small>{group.pack}</small></span><strong>{integer(group.quantity)} {group.unit}</strong></li>)}</ul>
                  <p className="small-note">Ledger below is filtered to this lane. Select an order to see timestamps and portfolio labels.</p>
                </> : selection?.kind === 'dock' ? <>
                  <span className="outline-tag">SCHEMATIC DESTINATION</span>
                  <p>A visual grouping of synthetic {selection.id} orders by last recorded status. Not a physical Fonterra dock, a live truck location or evidence of ongoing delivery.</p>
                  <div className="inspector-counts"><div><strong>{orders.filter((order) => order.city === selection.id).length}</strong><span>loaded orders</span></div><div><strong>{orders.filter((order) => order.city === selection.id && order.status === 'Dispatched').length}</strong><span>in transit</span></div></div>
                  <p className="small-note">Ledger below is filtered to this destination.</p>
                </> : <>
                  <div className="inspector-illustration" aria-hidden="true"><span>▱</span><span>▱</span><span>▱</span><i /></div>
                  <h4>Every movement starts with an order.</h4>
                  <p>Select a category lane, destination dock or an order to inspect the ingested facts behind the schematic.</p>
                  <div className="data-key"><span className="data-key-line" /><p><strong>Recorded</strong>Order lifecycle, sales, destinations</p><span className="data-key-line illustrative" /><p><strong>Illustrative</strong>Factory layout, line assignments, motion</p></div>
                </>}
              </div>
            </>}
          </section>

          <section className="panel activity-panel" aria-labelledby="activity-title">
            <div className="panel-heading"><div><p className="eyebrow">03 / Event journal</p><h3 id="activity-title">Recorded activity</h3></div><span className="count-badge">{snapshot ? activity.length : '—'}</span></div>
            <p className="activity-caption">Actual ingested event IDs · newest first{stale ? ' · STALE' : ''}</p>
            {!snapshot ? <p className="empty-inline">{error ? 'Event service unavailable.' : 'Loading recorded events…'}</p> : activity.length === 0 ? <p className="empty-inline">No recorded events in this response.</p> : <ol className="activity-list">
              {(showAllEvents ? activity : activity.slice(0, 8)).map((event) => <li key={event.id}>
                <span className={`event-dot event-${event.eventType.toLowerCase()}`} aria-hidden="true" />
                <div><div className="event-head"><strong>{eventNames[event.eventType]}</strong><span>{ageLabel(event.eventTime, now)}</span></div>
                  <button className="text-button" onClick={() => select({ kind: 'order', id: event.orderId })}>{event.orderNumber}</button><span className="event-destination"> · {event.chain} / {event.city}</span>
                  <div className="event-time"><Timestamp value={event.eventTime} /></div>
                  <details className="event-provenance"><summary>Event ID</summary><span className="mono">{event.id}</span></details>
                </div>
              </li>)}
            </ol>}
            {activity.length > 8 && <button className="events-toggle" onClick={() => setShowAllEvents(!showAllEvents)}>{showAllEvents ? 'Show latest 8 events' : `Show all ${activity.length} loaded events`}</button>}
            <div className="journal-footer"><span className="connection-dot" />{quiet ? 'Stream quiet · history remains available' : '5-second read-only polling'}<small>No generated events or background producer</small></div>
          </section>
        </aside>

        <section id="orders" className="panel order-panel" aria-labelledby="orders-title" tabIndex={-1}>
          <div className="panel-heading">
            <div><p className="eyebrow">04 / Order ledger</p><h3 id="orders-title">NZ supermarket deliveries <span className="count-badge">{snapshot ? filteredOrders.length : '—'}</span></h3></div>
            <div className="ledger-window"><strong>Rolling 24 hours</strong><span>{snapshot ? `${integer(snapshot.totals.totalOrders)} orders in window` : 'Awaiting source data'}</span></div>
          </div>
          <div className="filters">
            <label className="search-field"><span className="sr-only">Search orders</span><span aria-hidden="true">⌕</span><input type="search" placeholder="Search order, brand, destination…" value={filters.search} onChange={(event) => changeFilter('search', event.target.value)} /></label>
            <label><span className="sr-only">Supermarket chain</span><select value={filters.chain} onChange={(event) => changeFilter('chain', event.target.value)}><option value="">All chains</option>{[...new Set([...chains, ...orders.map((order) => order.chain)])].map((chain) => <option key={chain}>{chain}</option>)}</select></label>
            <label><span className="sr-only">Order status</span><select value={filters.status} onChange={(event) => changeFilter('status', event.target.value)}><option value="">All statuses</option>{statuses.map((status) => <option key={status}>{status}</option>)}</select></label>
            <button onClick={resetFilters} disabled={!anyFilter}>Clear filters</button>
          </div>
          {(filters.lane || filters.city) && <div className="active-filters">
            {filters.lane && <button onClick={() => { changeFilter('lane', ''); setSelection(null); }}>Lane: {lineNames[filters.lane as keyof typeof lineNames]} <span aria-hidden="true">×</span></button>}
            {filters.city && <button onClick={() => { changeFilter('city', ''); setSelection(null); }}>Destination: {filters.city} <span aria-hidden="true">×</span></button>}
          </div>}
          {snapshot && <div className={`list-scope ${truncated || lineCapped ? 'is-truncated' : ''}`} role="status">
            <span>{truncated ? `Partial list: latest ${orders.length} of ${integer(snapshot.totals.totalOrders)} orders.` : `${orders.length} orders loaded.`} {lines.length} latest-event line items{lineCapped ? ' (600-line response cap reached)' : ''}.</span>
            <span>Filters affect loaded list only · totals above remain full window</span>
          </div>}
          {!snapshot ? <div className="table-empty" role="status"><span className="table-empty-symbol" aria-hidden="true">▤</span><h4>{error ? 'No snapshot available' : 'Connecting the order ledger…'}</h4><p>{error ? 'Restore the endpoint connection to display real ingested orders.' : 'Reading FonterraSales in FonterraEventhouse. No sample data is substituted.'}</p></div> :
            orders.length === 0 ? <div className="table-empty"><span className="table-empty-symbol" aria-hidden="true">▤</span><h4>No orders in this snapshot</h4><p>The source may be quiet or the 24-hour window empty. The factory stays static. New ingested orders will appear on the next successful poll.</p></div> :
              filteredOrders.length === 0 ? <div className="table-empty"><h4>No matching orders</h4><p>Try another chain, status or search term. Filters only search the loaded list.</p><button onClick={resetFilters}>Reset filters</button></div> :
                <div className="table-scroll" role="region" aria-label="Order ledger table, scroll horizontally on small screens" tabIndex={0}>
                  <table>
                    <thead><tr><th scope="col">Order / brand</th><th scope="col">Chain / destination</th><th scope="col">Status</th><th scope="col">Expected · NZ time</th><th scope="col" className="numeric">Net · NZD</th><th scope="col">Portfolio</th></tr></thead>
                    <tbody>{filteredOrders.map((order) => <tr key={order.id} className={selectedOrder?.id === order.id ? 'selected-row' : ''}>
                      <td><button className="order-button" onClick={() => select({ kind: 'order', id: order.id })} aria-pressed={selectedOrder?.id === order.id}>{order.number} <span aria-hidden="true">↗</span></button><small>{order.brand}</small></td>
                      <td><strong className="chain-name">{order.chain}</strong><small>{order.city} · {order.destination}</small></td>
                      <td><StatusBadge status={order.status} />{order.isLate && <small className="late-flag">Late order</small>}</td>
                      <td className="time-cell"><Timestamp value={order.expectedAt} /></td>
                      <td className="numeric mono">{money(order.netNZD)}</td>
                      <td><span className="portfolio-tag">{order.portfolioStatus}</span></td>
                    </tr>)}</tbody>
                  </table>
                </div>}
          <div className="ledger-footer"><span>Latest snapshot per run + order · no lifecycle double-counting</span><span>{snapshot ? `${integer(snapshot.totals.cancelled)} cancelled · ${integer(snapshot.totals.lateOrders)} late in 24h` : '—'}</span></div>
        </section>
      </div>

      <footer className="app-footer">
        <div><span className="footer-mark">F / NZ</span><span><strong>FonterraSales</strong> / FonterraEventhouse<br /><span className="small-note">Synthetic data, genuinely ingested · no manufacturing telemetry</span></span></div>
        <p>All times Pacific/Auckland · amounts NZD<br />{snapshot ? <>Snapshot <Timestamp value={snapshot.generatedAt} />{lastSuccessAt && <span> · fetched {ageLabel(new Date(lastSuccessAt).toISOString(), now)}</span>}</> : 'No successful snapshot yet'}</p>
      </footer>
    </main>
  </>;
}
