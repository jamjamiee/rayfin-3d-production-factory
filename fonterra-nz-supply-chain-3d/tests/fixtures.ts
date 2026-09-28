import type { Snapshot, Order, Line } from '../src/contract';

// Explicit test-only synthetic fixtures. Never imported by production code.
export function makeSnapshot(now = '2026-09-12T07:00:00.000Z'): Snapshot {
  const eventTime = new Date(Date.parse(now) - 120_000).toISOString();
  const orderedAt = new Date(Date.parse(now) - 3_600_000).toISOString();
  const makeOrder = (index: number, status: Order['status'], city: string, chain: string): Order => ({
    id: `test-run/test-order-${index}`, runId: 'test-run', orderKey: `test-order-${index}`, eventId: `test-event-${index}`,
    sequence: index + 1, number: `NZ-TEST-00${index + 1}`, status, eventTime, orderedAt,
    dispatchedAt: ['Dispatched', 'Delivered', 'Sold'].includes(status) ? eventTime : null,
    deliveredAt: ['Delivered', 'Sold'].includes(status) ? eventTime : null,
    expectedAt: new Date(Date.parse(now) + 3_600_000).toISOString(),
    brand: index % 2 ? 'Mainland' : 'Anchor', brandScope: 'NZ consumer comparison',
    portfolioStatus: 'Divested to Lactalis · 31 Mar 2026', chain, destinationId: `synthetic-destination-${index}`,
    destination: `Synthetic ${city} supermarket`, city, region: city,
    latitude: -36.85, longitude: 174.76, isDispatched: ['Dispatched', 'Delivered', 'Sold'].includes(status),
    isLate: false, netNZD: '1234.50', salesNZD: status === 'Sold' ? '1234.50' : '0.00',
  });
  const orders = [
    makeOrder(0, 'Received', 'Auckland', 'New World'),
    makeOrder(1, 'Dispatched', 'Wellington', "PAK'nSAVE"),
    makeOrder(2, 'Delivered', 'Christchurch', 'Woolworths'),
    makeOrder(3, 'Sold', 'Hamilton', 'Four Square'),
    makeOrder(4, 'Cancelled', 'Tauranga', 'FreshChoice'),
    makeOrder(5, 'Received', 'Dunedin', 'SuperValue'),
  ];
  const categories: Line['productionLine'][] = ['dairy', 'cheese', 'cultured', 'butter'];
  const products = ['Milk powder', 'Cheddar portions', 'Yoghurt tubs', 'Butter packs'];
  const lines = orders.map((order, index): Line => ({
    id: `${order.id}/line-1`, orderId: order.id, eventId: order.eventId, number: 1,
    productCode: `TEST-PRODUCT-${index}`, product: products[index % 4], category: categories[index % 4],
    brand: order.brand, portfolioStatus: order.portfolioStatus, quantity: 12 + index,
    unit: index % 2 ? 'packs' : 'tubs', pack: index % 2 ? '500 g' : '1 kg',
    storage: 'Chilled', batchId: `TEST-BATCH-${index}`, status: order.status, netNZD: order.netNZD,
    productionLine: categories[index % 4],
  }));
  return {
    generatedAt: now, windowHours: 24, maxOrders: 200, scope: 'NZ supermarket deliveries',
    productionSource: 'Illustrative category assignments; no manufacturing telemetry is recorded.',
    orders, lines,
    activity: orders.map((order) => ({
      id: order.eventId, orderId: order.id, orderNumber: order.number,
      eventType: ({ Received: 'ORDER_RECEIVED', Dispatched: 'ORDER_DISPATCHED', Delivered: 'ORDER_DELIVERED', Sold: 'SALE_COMPLETED', Cancelled: 'ORDER_CANCELLED' } as const)[order.status],
      eventTime, brand: order.brand, chain: order.chain, city: order.city,
    })),
    totals: { totalOrders: 6, awaitingDispatch: 2, inTransit: 1, delivered: 2, cancelled: 1, lateOrders: 0, salesNZD: '1234.50', lastEventAt: eventTime },
  };
}

export function makeEmptySnapshot(now?: string): Snapshot {
  return { ...makeSnapshot(now), orders: [], lines: [], activity: [],
    totals: { totalOrders: 0, awaitingDispatch: 0, inTransit: 0, delivered: 0, cancelled: 0, lateOrders: 0, salesNZD: '0.00', lastEventAt: null } };
}
