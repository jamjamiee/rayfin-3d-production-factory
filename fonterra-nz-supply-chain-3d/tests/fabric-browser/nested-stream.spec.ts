import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { makeEmptySnapshot, makeSnapshot } from '../fixtures';
import type { Snapshot } from '../../src/contract';

const PORTAL = 'https://app.fabric.microsoft.com';
const EXTENSION = 'https://extension.test';
const APP = 'https://native-app.test';

function transport(snapshot: Snapshot, sequence: number) {
  const { orders, lines, activity, ...metadata } = snapshot;
  const row = (Kind: string, RowKey: string, payload: unknown) => ({
    Kind, RowKey, PayloadJson: JSON.stringify(payload), SnapshotId: `test-cohort-${sequence}`,
  });
  return { results: [{ tables: [{ rows: [
    row('meta', 'meta', { ...metadata, __rowCounts: { orders: orders.length, lines: lines.length, activity: activity.length } }),
    ...orders.map((order) => row('order', `order:${order.id}`, order)),
    ...lines.map((line) => row('line', `line:${line.id}`, line)),
    ...activity.map((event) => row('activity', `activity:${event.id}`, event)),
  ] }] }] };
}

// All pages, authentication and data below are intercepted synthetic fixtures.
// No request in this test may reach a real Fabric service.
test('nested native SDK handoff displays streamed orders and updated line items', async ({ page }) => {
  const html = readFileSync('dist-fabric\\index.html', 'utf8');
  let challenge = '';
  let handoffs = 0;
  let exchanges = 0;
  let queries = 0;
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.exposeFunction('testHandoff', (payload: { callbackUrl: string; codeChallenge: string; codeChallengeMethod: string }) => {
    expect(payload.callbackUrl).toBe(APP);
    expect(payload.codeChallengeMethod).toBe('S256');
    challenge = payload.codeChallenge;
    handoffs++;
  });
  await page.exposeFunction('testQuery', (payload: { workspaceId: string; modelId: string; query: string }) => {
    expect(exchanges).toBe(1);
    expect(payload).toEqual({
      workspaceId: 'd93a2e35-f91d-4e31-a905-d0c503821af7',
      modelId: 'bde0a59e-f906-4876-aa15-5baaef99df12',
      query: 'EVALUATE FactorySnapshotRows',
    });
    const snapshot = queries === 0 ? makeEmptySnapshot(new Date().toISOString()) : makeSnapshot(new Date().toISOString());
    if (queries >= 2) {
      const original = snapshot.orders[0];
      const added = { ...original, id: 'test-run/streamed-order', orderKey: 'streamed-order', eventId: 'streamed-event', number: 'NZ-STREAM-007' };
      snapshot.orders.push(added);
      snapshot.lines[0].quantity = 24;
      snapshot.lines.push({ ...snapshot.lines[0], id: `${added.id}/line-1`, orderId: added.id, eventId: added.eventId });
      snapshot.totals.totalOrders++;
      snapshot.totals.awaitingDispatch++;
    }
    return transport(snapshot, queries++);
  });
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === PORTAL) {
      return route.fulfill({ contentType: 'text/html', body: `<html><title>TEST ONLY portal harness</title><body style="margin:0"><iframe title="Test extension" style="width:100%;height:100vh;border:0" src="${EXTENSION}/"></iframe></body></html>` });
    }
    if (url.origin === EXTENSION) {
      return route.fulfill({ contentType: 'text/html', body: `<html><body style="margin:0">
        <iframe title="Test native app" style="width:100%;height:100vh;border:0" src="${APP}/?fabricEmbedded=true"></iframe>
        <script>
          const child = document.querySelector('iframe');
          addEventListener('message', async event => {
            if (event.source !== child.contentWindow || event.origin !== '${APP}') return;
            const request = event.data;
            if (request.channel === 'fabric-auth' && request.kind === 'auth.requestHandoff') {
              await window.testHandoff(request.payload);
              event.source.postMessage({channel: request.channel, version: 1, kind: 'response',
                requestId: request.requestId, success: true,
                result: {handoffCode: 'synthetic-single-use-code', state: request.payload.state}}, '${APP}');
            } else if (request.channel === 'fabric-app-data-semantic-model' && request.method === 'semanticModel.executeDaxJson') {
              const data = await window.testQuery(request.payload);
              event.source.postMessage({channel: request.channel, requestId: request.requestId,
                result: {data}}, '${APP}');
            }
          });
        </script></body></html>` });
    }
    if (url.origin === APP) return route.fulfill({ contentType: 'text/html', body: html });
    if (url.hostname.endsWith('.pbidedicated.windows.net')) {
      expect(url.pathname).toContain('/workspaces/d93a2e35-f91d-4e31-a905-d0c503821af7/appbackends/8d68a675-6533-476f-94e6-e74e45c997a9/');
      const headers = { 'access-control-allow-origin': APP, 'access-control-allow-credentials': 'true',
        'access-control-allow-headers': route.request().headers()['access-control-request-headers'] ?? 'content-type',
        'access-control-allow-methods': 'POST, GET, OPTIONS' };
      if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
      if (url.pathname.endsWith('/api/auth/v1/signout')) return route.fulfill({ status: 200, headers, json: {} });
      if (url.pathname.endsWith('/api/auth/v1/token')) {
        const request = route.request().postDataJSON();
        expect(request).toMatchObject({ grantType: 'authorization_code', codeType: 'fabric_handoff',
          verificationCode: 'synthetic-single-use-code', redirectUri: APP });
        expect(createHash('sha256').update(request.codeVerifier).digest('base64url')).toBe(challenge);
        exchanges++;
        const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
        const payload = Buffer.from(JSON.stringify({ sub: 'test-only-user', email: 'test@example.invalid', exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url');
        return route.fulfill({ headers, json: { accessToken: `${header}.${payload}.test-only`, expiresIn: 3600, tokenType: 'Bearer' } });
      }
    }
    await route.abort();
    throw new Error(`Unexpected external request in isolated test: ${url.origin}${url.pathname}`);
  });
  await page.goto(`${PORTAL}/test-only-native-bridge`);
  const app = page.frameLocator('iframe').frameLocator('iframe');
  await expect(app.getByText('No orders in this snapshot')).toBeVisible({ timeout: 15000 });
  await expect(app.getByText('6 orders loaded. 6 latest-event line items.')).toBeVisible({ timeout: 15000 });
  await app.getByRole('table').getByRole('button', { name: 'NZ-TEST-001', exact: true }).click();
  await expect(app.getByText('7 orders loaded. 7 latest-event line items.')).toBeVisible({ timeout: 15000 });
  await expect(app.getByRole('button', { name: 'NZ-STREAM-007', exact: true })).toBeVisible();
  await expect(app.getByRole('region', { name: 'Details for NZ-TEST-001' }).getByText('24 tubs')).toBeVisible();
  await expect(app.getByRole('alert')).toHaveCount(0);
  expect(handoffs).toBe(1);
  expect(exchanges).toBe(1);
  expect(errors).toEqual([]);
  const child = page.frames().find((frame) => new URL(frame.url()).origin === APP);
  expect(child).toBeDefined();
  expect(await child!.evaluate(() => ({
    local: Object.fromEntries(Object.entries(localStorage)),
    session: Object.fromEntries(Object.entries(sessionStorage)),
  }))).toEqual({ local: {}, session: { fabricEmbedded: 'true' } });
});
