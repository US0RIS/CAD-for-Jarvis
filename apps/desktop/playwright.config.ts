import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Real measurements on Windows CI (see vertical-slice.spec.ts) show individual engine writes
  // taking minutes under this suite's process load, not seconds - a single add-component call
  // was measured at 236s. The sum of this suite's own per-assertion timeouts alone can approach
  // 900s in the worst case; give it real room rather than let the global timeout become the
  // thing that fails instead of a specific, diagnosable assertion. The job-level CI timeout
  // (currently 50 minutes) is the outer bound this still needs to fit under, twice over (one
  // retry).
  timeout: 900_000,
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
