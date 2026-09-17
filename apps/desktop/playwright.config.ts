import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // This is intentionally a full release vertical slice: catalog browsing, multiple
  // CAD mutations and scene rebuilds, manufacturing/evidence, tolerance analysis and
  // an autonomous campaign all run in one scenario. Keep the individual assertions'
  // strict 10–90 second limits, but do not let their cumulative legitimate runtime hit
  // a two-minute suite ceiling before the later release gates are exercised.
  timeout: 300_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },
  webServer: {
    command: 'pnpm test:web',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1586, height: 992 } } }],
});
