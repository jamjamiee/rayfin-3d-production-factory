import { expect, test } from '@playwright/test';

test('Fabric build fails closed outside the portal without HTTP fallback or browser storage', async ({ page }) => {
  const apiCalls: string[] = [];
  const errors: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/') || url.hostname.endsWith('.kusto.fabric.microsoft.com') || url.hostname.endsWith('.kusto.windows.net')) apiCalls.push(url.pathname);
  });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/?clawpilotTheme=light');
  await expect(page.getByRole('alert')).toContainText('Open app in Fabric');
  await expect(page.getByRole('alert')).toContainText('Open this app inside the Fabric portal');
  await expect(page.getByText('No snapshot available', { exact: true })).toBeVisible();
  await expect(page.getByText('Static factory · awaiting data', { exact: true })).toBeVisible();
  await expect(page.getByTestId('factory-canvas')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open app in Fabric' })).toHaveAttribute('href', /appbackends\/8d68a675-6533-476f-94e6-e74e45c997a9/);
  await expect(page.getByRole('button', { name: 'Retry connection' })).toHaveCount(0);
  await expect(page.getByRole('alert')).not.toContainText('Authentication required');
  expect(apiCalls).toEqual([]);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test('Fabric build rejects an untrusted iframe parent before requesting authentication', async ({ page }) => {
  await page.route('**/test-untrusted-parent*', (route) => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><body><iframe title="Untrusted native test" src="/?clawpilotTheme=light"></iframe></body></html>',
  }));
  await page.goto('/test-untrusted-parent?access_token=test-only-secret');
  const frame = page.frameLocator('iframe');
  await expect(frame.getByRole('alert')).toContainText('Open app in Fabric');
  await expect(frame.getByRole('alert')).not.toContainText('Fabric host connection blocked');
  await expect(frame.getByRole('alert')).not.toContainText('test-only-secret');
  await expect(frame.getByRole('button', { name: 'Retry connection' })).toHaveCount(0);
  await expect(frame.getByText('No snapshot available', { exact: true })).toBeVisible();
});
