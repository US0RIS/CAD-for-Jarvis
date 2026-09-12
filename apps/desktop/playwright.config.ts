import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // This suite's own scene-health wait alone budgets up to 120s on slow CI hardware (real
  // BREP tessellation of dense component geometry), on top of the analysis step's 90s wait -
  // 120_000 stopped leaving room for the rest of the test once those grew.
  timeout: 240_000,
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
