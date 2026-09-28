import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testDir: './tests/fabric-browser',
  outputDir: './test-results-fabric',
  use: { ...base.use, baseURL: 'http://127.0.0.1:4182' },
  webServer: {
    command: 'npm run preview:fabric -- --port 4182 --strictPort',
    url: 'http://127.0.0.1:4182',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
