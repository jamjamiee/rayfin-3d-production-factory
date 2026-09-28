import type { Line, Order, ProductionLine, Snapshot } from './contract';

const currency = new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD', minimumFractionDigits: 2 });
const nzTime = new Intl.DateTimeFormat('en-NZ', {
  timeZone: 'Pacific/Auckland', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
export const integer = (value: number) => value.toLocaleString('en-NZ');
export function money(value: string): string {
  // Decimal strings are rounded in integer cents; order money is not production accounting.
  const negative = value.startsWith('-');
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.');
  let cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
  if (Number(fraction[2] ?? 0) >= 5) cents += 1n;
  const parts = currency.formatToParts(negative ? -(cents / 100n) : cents / 100n);
  const result = parts.map((part) => part.type === 'fraction' ? (cents % 100n).toString().padStart(2, '0') : part.value).join('');
  return negative && cents > 0n && cents < 100n ? `-${result}` : result;
}
export const formatTime = (value: string | null) => value ? nzTime.format(new Date(value)) : 'Not recorded';
export function ageLabel(value: string | null, now: number): string {
  if (!value) return 'No events in window';
  const seconds = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
export function isQuiet(snapshot: Snapshot | null, now: number): boolean {
  return !snapshot?.totals.lastEventAt || now - Date.parse(snapshot.totals.lastEventAt) > 60_000;
}
export function latestLines(snapshot: Snapshot): Line[] {
  const events = new Map(snapshot.orders.map((order) => [order.id, order.eventId]));
  return snapshot.lines.filter((line) => events.get(line.orderId) === line.eventId);
}
export function laneSummary(lane: ProductionLine, orders: Order[], lines: Line[]) {
  const assigned = lines.filter((line) => line.productionLine === lane);
  const orderIds = new Set(assigned.map((line) => line.orderId));
  return {
    lineItems: assigned.length,
    orders: orders.filter((order) => orderIds.has(order.id)),
    awaiting: orders.filter((order) => orderIds.has(order.id) && order.status === 'Received').length,
  };
}
export interface Filters { search: string; chain: string; status: string; lane: string; city: string }
export const emptyFilters: Filters = { search: '', chain: '', status: '', lane: '', city: '' };
export function filterOrders(orders: Order[], lines: Line[], filters: Filters): Order[] {
  const laneIds = new Set(lines.filter((line) => line.productionLine === filters.lane).map((line) => line.orderId));
  const search = filters.search.toLocaleLowerCase('en-NZ').trim();
  return orders.filter((order) =>
    (!filters.chain || order.chain === filters.chain) &&
    (!filters.status || order.status === filters.status) &&
    (!filters.lane || laneIds.has(order.id)) &&
    (!filters.city || order.city === filters.city) &&
    (!search || [order.number, order.chain, order.brand, order.destination, order.city, order.region, order.id]
      .join(' ').toLocaleLowerCase('en-NZ').includes(search)),
  );
}
export function quantityGroups(lines: Line[]) {
  const groups = new Map<string, { key: string; product: string; pack: string; unit: string; quantity: number }>();
  for (const line of lines) {
    const key = JSON.stringify([line.productCode, line.product, line.unit, line.pack]);
    const existing = groups.get(key);
    if (existing) existing.quantity += line.quantity;
    else groups.set(key, { key, product: line.product, pack: line.pack, unit: line.unit, quantity: line.quantity });
  }
  return [...groups.values()];
}
