import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { snapshotSchema } from '../src/contract';
import { ageLabel, emptyFilters, filterOrders, formatTime, isQuiet, laneSummary, latestLines, money, quantityGroups } from '../src/data';
import { makeEmptySnapshot, makeSnapshot } from './fixtures';

describe('verified snapshot contract', () => {
  it('accepts explicit synthetic fixtures and empty responses', () => {
    expect(snapshotSchema.safeParse(makeSnapshot()).success).toBe(true);
    expect(snapshotSchema.safeParse(makeEmptySnapshot()).success).toBe(true);
  });
  it('rejects invalid timestamps, statuses, amounts, caps and missing totals', () => {
    const snapshot = makeSnapshot();
    expect(snapshotSchema.safeParse({ ...snapshot, generatedAt: 'yesterday' }).success).toBe(false);
    expect(snapshotSchema.safeParse({ ...snapshot, orders: [{ ...snapshot.orders[0], status: 'Producing' }] }).success).toBe(false);
    expect(snapshotSchema.safeParse({ ...snapshot, totals: { ...snapshot.totals, salesNZD: 'NaN' } }).success).toBe(false);
    expect(snapshotSchema.safeParse({ ...snapshot, lines: Array(601).fill(snapshot.lines[0]) }).success).toBe(false);
    expect(snapshotSchema.safeParse({ ...snapshot, totals: undefined }).success).toBe(false);
  });
  it.skipIf(!process.env.SNAPSHOT_VALIDATION_FILE)('accepts the supplied local read-only validation snapshot without exporting it', () => {
    const local = JSON.parse(readFileSync(process.env.SNAPSHOT_VALIDATION_FILE!, 'utf8'));
    expect(snapshotSchema.safeParse(local).success).toBe(true);
  });
});

describe('order-derived presentation, not production accounting', () => {
  const snapshot = makeSnapshot();
  it('only uses lines linked to the latest order event', () => {
    const staleLine = { ...snapshot.lines[0], id: 'old-line', eventId: 'old-event', quantity: 999999 };
    const unrelatedLine = { ...snapshot.lines[0], id: 'orphan-line', orderId: 'missing-order' };
    const actual = latestLines({ ...snapshot, lines: [...snapshot.lines, staleLine, unrelatedLine] });
    expect(actual).toHaveLength(snapshot.lines.length);
    expect(actual.some((line) => line.id === 'old-line')).toBe(false);
  });
  it('counts unique received orders per lane, not line quantities', () => {
    const duplicateProduct = { ...snapshot.lines[0], id: 'another-line' };
    const summary = laneSummary('dairy', snapshot.orders, [...snapshot.lines, duplicateProduct]);
    expect(summary.lineItems).toBe(3);
    expect(summary.orders).toHaveLength(2);
    expect(summary.awaiting).toBe(1);
  });
  it('keeps units, products and pack sizes in separate quantity groups', () => {
    const line = snapshot.lines[0];
    const groups = quantityGroups([
      line, { ...line, quantity: 3 }, { ...line, pack: '500 g', quantity: 2 },
      { ...line, unit: 'bags', quantity: 8 }, { ...line, productCode: 'other-product', product: 'Other', quantity: 5 },
    ]);
    expect(groups).toHaveLength(4);
    expect(groups[0].quantity).toBe(15);
  });
  it('combines chain, status, search, lane and city filters without changing totals', () => {
    expect(filterOrders(snapshot.orders, snapshot.lines, { ...emptyFilters, chain: 'New World', status: 'Received', search: 'anchor', lane: 'dairy', city: 'Auckland' })).toHaveLength(1);
    expect(filterOrders(snapshot.orders, snapshot.lines, { ...emptyFilters, search: 'missing' })).toHaveLength(0);
    expect(snapshot.totals.totalOrders).toBe(6);
  });
  it('formats NZ currency directly from decimal strings with precise cent rounding', () => {
    expect(money('1234.50')).toBe('$1,234.50');
    expect(money('1.005')).toBe('$1.01');
    expect(money('-0.09')).toBe('-$0.09');
    expect(money('9007199254740993.12')).toBe('$9,007,199,254,740,993.12');
    expect(money('0')).toBe('$0.00');
  });
  it('uses Auckland daylight-saving and standard time, independent of browser locale', () => {
    expect(formatTime('2026-09-12T07:00:00Z')).toContain('19:00:00');
    expect(formatTime('2026-12-12T07:00:00Z')).toContain('20:00:00');
    expect(formatTime(null)).toBe('Not recorded');
  });
  it('stays quiet without recent ingested events or empty windows', () => {
    const now = Date.parse(snapshot.generatedAt);
    expect(isQuiet(snapshot, now)).toBe(true);
    expect(isQuiet(makeEmptySnapshot(), now)).toBe(true);
    expect(isQuiet({ ...snapshot, totals: { ...snapshot.totals, lastEventAt: snapshot.generatedAt } }, now)).toBe(false);
    expect(ageLabel(snapshot.totals.lastEventAt, now)).toBe('2m ago');
    expect(ageLabel(null, now)).toBe('No events in window');
  });
});
