import { expect, test, type APIRequestContext } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

async function resetWithPi(request: APIRequestContext) {
  const reset = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset advanced engineering UX workspace' },
  });
  expect(reset.ok()).toBeTruthy();
  const added = await request.post(`${engineUrl}/v2/components/compute.raspberry_pi_5_8gb/add`, { headers });
  expect(added.ok()).toBeTruthy();
}

test('Analyze exposes release-level assembly, physical evidence, solver, and lineage state without overstating verification', async ({ page, request }) => {
  await resetWithPi(request);

  const healthResponse = await request.get(`${engineUrl}/v6/health`, { headers });
  expect(healthResponse.ok()).toBeTruthy();
  const health = await healthResponse.json() as {
    release_stage: string;
    validation_truth: { real_hardware_validation_complete: boolean };
    external_solvers: { count: number; available_count: number };
  };
  expect(health.validation_truth.real_hardware_validation_complete).toBe(false);

  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Analyze', exact: true }).click();

  const inspector = page.getByTestId('advanced-engineering-status');
  await expect(inspector).toBeVisible({ timeout: 20_000 });
  await expect(inspector.getByTestId('assembly-integrity-status')).toBeVisible();
  await expect(inspector.getByTestId('physical-evidence-status')).toContainText('NOT GLOBALLY VALIDATED');
  await expect(inspector.getByTestId('solver-runtime-status')).toContainText(`${health.external_solvers.available_count}/${health.external_solvers.count} AVAILABLE`);
  await expect(inspector.getByTestId('engineering-lineage-status')).toContainText(health.release_stage.replaceAll('_', ' '));
  await expect(inspector).toContainText('never upgrades a branch label, solver result, synthetic CI fixture, or fabrication-package hash into physical verification');

  // Purchased hardware remains inspection-only even while Analyze exposes deeper v6 state.
  await expect(page.getByText('PARAMETRIC CAD')).toHaveCount(0);
  await expect(page.getByTestId('feature-history-panel')).toHaveCount(0);
});
