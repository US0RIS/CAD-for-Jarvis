import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Windows CI needs real headroom here: confirmed against real runs that even a "warm"
  // attempt can take well over 120s once you add on-demand Vite transpilation, React
  // StrictMode's double-mount, and general Windows runner overhead on top of this spec's
  // own already-generously-timed steps (image loads, the LLM-driven branch-rename flow).
  timeout: 240_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    // 'retain-on-failure' still *records* continuously on every attempt (only the save is
    // conditional), which means constant CDP screenshot/frame capture against a live WebGL
    // canvas for the entire first attempt too. Deferring recording to the retry keeps
    // diagnostics for whichever attempt actually fails without taxing every normal run.
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
