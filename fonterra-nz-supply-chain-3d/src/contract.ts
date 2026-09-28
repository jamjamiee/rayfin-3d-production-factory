import { z } from 'zod';

const timestamp = z.iso.datetime({ offset: true });
const money = z.string().regex(/^-?\d+(\.\d+)?$/);
const count = z.number().int().nonnegative();
export const statuses = ['Received', 'Dispatched', 'Delivered', 'Sold', 'Cancelled'] as const;
export const productionLines = ['dairy', 'cheese', 'cultured', 'butter'] as const;
export const chains = ['New World', "PAK'nSAVE", 'Woolworths', 'Four Square', 'FreshChoice', 'SuperValue'] as const;
export const cities = ['Auckland', 'Wellington', 'Christchurch', 'Hamilton', 'Tauranga', 'Dunedin'] as const;
const status = z.enum(statuses);

export const orderSchema = z.object({
  id: z.string(), runId: z.string(), orderKey: z.string(), eventId: z.string(),
  sequence: count, number: z.string(), status, eventTime: timestamp, orderedAt: timestamp,
  dispatchedAt: timestamp.nullable(), deliveredAt: timestamp.nullable(), expectedAt: timestamp,
  brand: z.string(), brandScope: z.string(), portfolioStatus: z.string(), chain: z.string(),
  destinationId: z.string(), destination: z.string(), city: z.string(), region: z.string(),
  latitude: z.number().min(-90).max(90), longitude: z.number().min(-180).max(180),
  isDispatched: z.boolean(), isLate: z.boolean(), netNZD: money, salesNZD: money,
});
export const lineSchema = z.object({
  id: z.string(), orderId: z.string(), eventId: z.string(), number: count,
  productCode: z.string(), product: z.string(), category: z.string(), brand: z.string(),
  portfolioStatus: z.string(), quantity: z.number().nonnegative(), unit: z.string(),
  pack: z.string(), storage: z.string(), batchId: z.string(), status, netNZD: money,
  productionLine: z.enum(productionLines),
});
export const activitySchema = z.object({
  id: z.string(), orderId: z.string(), orderNumber: z.string(),
  eventType: z.enum(['ORDER_RECEIVED', 'ORDER_DISPATCHED', 'ORDER_DELIVERED', 'SALE_COMPLETED', 'ORDER_CANCELLED']),
  eventTime: timestamp, brand: z.string(), chain: z.string(), city: z.string(),
});
export const snapshotSchema = z.object({
  generatedAt: timestamp, windowHours: z.literal(24), maxOrders: z.literal(200),
  scope: z.literal('NZ supermarket deliveries'),
  productionSource: z.string(),
  orders: z.array(orderSchema).max(200),
  lines: z.array(lineSchema).max(600),
  activity: z.array(activitySchema),
  totals: z.object({
    totalOrders: count, awaitingDispatch: count, inTransit: count, delivered: count,
    cancelled: count, lateOrders: count, salesNZD: money, lastEventAt: timestamp.nullable(),
  }),
});

export type Snapshot = z.infer<typeof snapshotSchema>;
export type Order = z.infer<typeof orderSchema>;
export type Line = z.infer<typeof lineSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type ProductionLine = typeof productionLines[number];
export type Selection = { kind: 'lane'; id: ProductionLine } | { kind: 'dock'; id: string } | { kind: 'order'; id: string } | null;

export const lineNames: Record<ProductionLine, string> = {
  dairy: 'Dairy & milk', cheese: 'Cheese', cultured: 'Cultured', butter: 'Butter',
};
export const eventNames: Record<Activity['eventType'], string> = {
  ORDER_RECEIVED: 'Order received',
  ORDER_DISPATCHED: 'Dispatched',
  ORDER_DELIVERED: 'Delivered',
  SALE_COMPLETED: 'Sale completed',
  ORDER_CANCELLED: 'Cancelled',
};
