import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Real measurements on Windows CI (see vertical-slice.spec.ts) show individual engine calls
  // taking minutes under this suite's process load, not seconds - add-component and branch
  // activation both go through core.execute()/persist() under the same global LOCK doing
  // synchronous, AV-scanned disk I/O, and both have now individually exceeded their own prior
  // margins (add-component's 300s ceiling was itself observed exceeded, hence its timeout now
  // matches activate_branch's already-justified 900s). The sum of this suite's own per-assertion
  // timeouts is now ~53 minutes in the worst observed case; 60 minutes gives that real room
  // without racing it, still inside the job-level CI timeout (raised to 90 minutes alongside
  // this) minus setup.
  timeout: 3_600_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  // Retries don't help the failure mode actually seen here: every attempt runs against the same
  // long-lived, equally-contended backend process on the same runner, so a retry pays the same
  // CPU-starvation cost again rather than avoiding it - and can inherit confusing mutated state
  // from the failed attempt (a component search that already shows "Added" because the first
  // attempt got that far before failing somewhere else). With retries:1, a single slow-but-real
  // attempt plus a doomed-to-repeat retry risks exceeding the job timeout outright. A genuinely
  // transient, non-contention failure just fails once here instead of being masked by a retry.
  retries: 0,
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
