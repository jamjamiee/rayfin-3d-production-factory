import { expect, test } from '@playwright/test';
import { OrthographicCamera, Vector3 } from 'three';
import { makeEmptySnapshot, makeSnapshot } from '../fixtures';

test('genuine WebGL factory, quiet data, filters, accessible selection, dark and light themes', async ({ page }, testInfo) => {
  const snapshot = makeSnapshot(new Date().toISOString());
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.route('**/api/factory/snapshot', (route) => route.fulfill({ json: { ...snapshot, generatedAt: new Date().toISOString() } }));
  await page.goto('/?clawpilotTheme=light');
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
  await expect(page.getByTestId('factory-canvas')).toBeVisible();
  await expect(page.getByText('Stream quiet', { exact: true })).toBeVisible();
  await expect(page.getByText('Static · stream quiet', { exact: true })).toBeVisible();
  await expect(page.getByText(/Dock highlights show last recorded status—not current vehicle movement/)).toBeVisible();
  expect(await page.getByTestId('factory-canvas').evaluate((canvas: HTMLCanvasElement) => {
    const context = canvas.getContext('webgl2');
    return !!context && context.drawingBufferWidth > 0 && context.getParameter(context.VERSION).includes('WebGL');
  })).toBe(true);
  await page.getByRole('button', { name: 'Rotate camera right' }).click();
  await page.getByRole('button', { name: 'Zoom camera in' }).click();
  await page.getByRole('button', { name: 'Fit view' }).click();
  await page.getByRole('button', { name: /L02.*Cheese/ }).click();
  await expect(page.getByRole('button', { name: /Lane: Cheese/ })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByRole('combobox', { name: 'Supermarket chain' }).selectOption('New World');
  await expect(page.getByRole('table').getByRole('row')).toHaveCount(2);
  await page.getByRole('table').getByRole('button', { name: /NZ-TEST-001/ }).click();
  const detail = page.getByRole('region', { name: 'Details for NZ-TEST-001' });
  await expect(detail).toBeFocused();
  await expect(detail.getByText('Milk powder', { exact: true })).toBeVisible();
  await expect(detail.getByText('12 tubs', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Close order details' }).click();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByTestId('factory-canvas')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('factory-dark.png'), fullPage: true, scale: 'css' });
  await page.getByRole('button', { name: 'Switch to light theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.screenshot({ path: testInfo.outputPath('factory-light.png'), fullPage: true, scale: 'css' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(pageErrors).toEqual([]);
});

test('raycast lane and dock geometry select the same accessible detail panels', async ({ page }) => {
  await page.route('**/api/factory/snapshot', (route) => route.fulfill({ json: makeSnapshot(new Date().toISOString()) }));
  await page.goto('/?clawpilotTheme=light');
  const canvas = page.getByTestId('factory-canvas');
  await expect(canvas).toBeVisible();
  const size = await canvas.boundingBox();
  if (!size) throw new Error('Factory canvas has no measured size.');
  const aspect = size.width / size.height;
  const span = Math.max(15.6, 21.8 / aspect);
  const camera = new OrthographicCamera(-span * aspect, span * aspect, span, -span, 0.1, 200);
  camera.position.set(29, 29, 36);
  camera.lookAt(0, 0.5, 0);
  camera.updateMatrixWorld();
  const project = (x: number, y: number, z: number) => {
    const point = new Vector3(x, y, z).project(camera);
    return { x: (point.x + 1) * size.width / 2, y: (1 - point.y) * size.height / 2 };
  };
  await canvas.click({ position: project(-5.5, 3.9, -4.2) });
  await expect(page.getByRole('button', { name: /L01.*Dairy & milk/ })).toHaveAttribute('aria-pressed', 'true');
  await canvas.click({ position: project(-10.6, 0.9, 13.1) });
  await expect(page.getByRole('heading', { name: 'Auckland dock' })).toBeVisible();
  await expect(page.getByRole('button', { name: /01 Auckland 0 in transit/ })).toHaveAttribute('aria-pressed', 'true');
});

test('authentication, last-good stale retention, recovery and empty state', async ({ page }) => {
  let mode: 'auth' | 'good' | 'error' | 'empty' = 'auth';
  await page.route('**/api/factory/snapshot', (route) => {
    if (mode === 'auth') return route.fulfill({ status: 401, json: { error: { code: 'AUTH', message: 'Host sign-in required.' } } });
    if (mode === 'error') return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Source unavailable.' } } });
    return route.fulfill({ json: mode === 'empty' ? makeEmptySnapshot(new Date().toISOString()) : makeSnapshot(new Date().toISOString()) });
  });
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Authentication required');
  await expect(page.getByText('No snapshot available', { exact: true })).toBeVisible();
  mode = 'good';
  await page.getByRole('button', { name: 'Retry connection' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  mode = 'error';
  await expect(page.getByRole('alert')).toContainText('Showing last good data', { timeout: 10_000 });
  await expect(page.getByText('Stale snapshot', { exact: true })).toBeVisible();
  await expect(page.getByRole('table').getByRole('row')).toHaveCount(7);
  mode = 'empty';
  await page.getByRole('button', { name: 'Retry connection' }).click();
  await expect(page.getByText('No orders in this snapshot', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('WebGL unavailable fallback preserves a keyboard-operable ledger and reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
      if (type.includes('webgl')) return null;
      return original.apply(this, [type, ...args] as Parameters<typeof original>);
    } as typeof original;
  });
  await page.route('**/api/factory/snapshot', (route) => route.fulfill({ json: makeSnapshot(new Date().toISOString()) }));
  await page.goto('/');
  await expect(page.getByText('3D view unavailable', { exact: true })).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
  const lane = page.getByRole('button', { name: /L01.*Dairy & milk/ });
  await lane.focus();
  await page.keyboard.press('Enter');
  await expect(lane).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('table').getByRole('row')).toHaveCount(3);
  await expect(page.getByRole('button', { name: 'Pause motion' })).toBeDisabled();
});

test('truncation, genuine event IDs and static sold-order history', async ({ page }) => {
  const snapshot = makeSnapshot(new Date().toISOString());
  snapshot.orders.forEach((order) => { order.status = 'Sold'; });
  snapshot.lines.forEach((line) => { line.status = 'Sold'; });
  snapshot.totals = { ...snapshot.totals, totalOrders: 250, awaitingDispatch: 0, lastEventAt: snapshot.generatedAt };
  await page.route('**/api/factory/snapshot', (route) => route.fulfill({ json: snapshot }));
  await page.goto('/');
  await expect(page.getByText('Static · no received orders in loaded list')).toBeVisible();
  await expect(page.getByText(/Partial list: latest 6 of 250 orders/)).toBeVisible();
  await page.locator('.event-provenance summary').first().click();
  await expect(page.locator('.event-provenance').first()).toContainText('test-event-0');
  await page.getByRole('combobox', { name: 'Order status' }).selectOption('Received');
  await expect(page.getByText('No matching orders', { exact: true })).toBeVisible();
  await expect(page.getByText('250 orders in window', { exact: true })).toBeVisible();
});
