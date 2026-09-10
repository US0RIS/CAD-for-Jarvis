import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Windows CI runners (windows-2025, software-rendered WebGL, on-demand Vite
  // transpilation under React StrictMode double-mount) consistently need ~35-43s
  // just to reach the branch-lineage assertions in vertical-slice.spec.ts before
  // any of the slower, already-generously-timed steps further down (component
  // image loads, the LLM-driven branch-rename flow) even start. The previous
  // 45_000ms budget left those later steps with only a few seconds of slack,
  // so the run was reliably killed mid-test — most often while waiting on the
  // pi-control-v2 branch card, simply because that's whatever assertion was in
  // flight when the clock ran out. Locally (Linux, native rendering) the whole
  // flow completes in well under 45s, which is why this only ever showed up on
  // the Windows runner. Raise the ceiling so the realistic end-to-end duration
  // fits with real headroom instead of racing the clock on every run.
  timeout: 120_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: 'pnpm test:web',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1586, height: 992 } } }],
});
