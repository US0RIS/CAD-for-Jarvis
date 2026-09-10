import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Windows CI runners (windows-2025, software-rendered WebGL, on-demand Vite
  // transpilation under React StrictMode double-mount) need far longer than the
  // original 45_000ms budget to get through vertical-slice.spec.ts. Confirmed
  // against two real CI attempts of this exact fix (run 34454913072): a cold
  // attempt (fresh Vite dev-server, nothing transpiled yet) ran the *entire*
  // 120_000ms budget without even reaching the pi-control-v2 branch-card
  // assertion, while the retry (Vite's on-demand transpile cache already warm
  // from attempt #1, same webServer process) got much further — it found and
  // clicked that branch card, past every earlier assertion — before again
  // running out of the same 120s budget waiting on the resulting state update.
  // So 120s under-covers even a warm run once you add the remaining, already
  // individually-timed steps (image loads, the LLM-driven branch-rename flow).
  // Locally (Linux, native rendering) the whole flow completes in ~1 minute,
  // which is why this only ever surfaces on the Windows runner. Give a cold
  // Windows run real headroom rather than inching the ceiling up per failure.
  timeout: 240_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    // 'retain-on-failure' still *records* continuously on every attempt (only the save is
    // conditional), which means constant CDP screenshot/frame capture against a live WebGL
    // canvas for the entire first attempt too. Under the software GL rasterizer this
    // Windows runner falls back to, that capture overhead compounds with the render loop's
    // own cost. Deferring recording to the retry keeps diagnostics for whichever attempt
    // actually ends up failing, without taxing every normal first attempt.
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
