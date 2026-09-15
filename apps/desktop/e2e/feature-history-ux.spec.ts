import { expect, test, type APIRequestContext } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

async function resetWithFabricatedPart(request: APIRequestContext) {
  const reset = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset feature-history UX workspace' },
  });
  expect(reset.ok()).toBeTruthy();
  const created = await request.post(`${engineUrl}/v3.1/cad/parts`, {
    headers,
    data: {
      name: 'Feature Audit Block',
      kind: 'box',
      params: { x: 40, y: 30, z: 8 },
      material: 'aluminum_6061_t6',
      semantic: { role: 'fabricated_test_part' },
    },
  });
  expect(created.ok()).toBeTruthy();
  const project = await request.get(`${engineUrl}/v2/project`, { headers });
  expect(project.ok()).toBeTruthy();
  const snapshot = await project.json() as { parts: Array<{ id: string; name: string; component_ref?: string | null }> };
  const part = snapshot.parts.find((row) => row.name === 'Feature Audit Block');
  expect(part?.id).toBeTruthy();
  expect(part?.component_ref).toBeFalsy();
  return part!.id;
}

test('fabricated parts expose editable feature history and PATCH edits survive the desktop CORS boundary', async ({ page, request }) => {
  const partId = await resetWithFabricatedPart(request);
  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });
  await page.locator('.object-row').first().click();
  await page.getByRole('button', { name: 'Properties', exact: true }).click();

  const history = page.getByTestId('feature-history-panel');
  await expect(history).toBeVisible();
  await expect(page.getByText('PARAMETRIC CAD')).toBeVisible();
  await expect(history).toContainText('No features');

  await history.getByTestId('add-cad-feature').click();
  const featureRow = history.locator('[data-testid^="feature-row-"]').first();
  await expect(featureRow).toBeVisible({ timeout: 15_000 });
  await expect(featureRow).toContainText('Hole');

  await featureRow.getByTitle('Expand feature').click();
  const diameter = featureRow.getByRole('spinbutton', { name: 'Hole diameter' });
  await expect(diameter).toBeVisible();
  await diameter.fill('6');
  await diameter.press('Enter');

  // updateCadFeature uses PATCH from the renderer to Forge Engine. This assertion
  // catches both feature-editor regressions and an incomplete desktop CORS policy.
  await expect.poll(async () => {
    const response = await request.get(`${engineUrl}/v3.1/cad/objects/${encodeURIComponent(partId)}/features`, { headers });
    if (!response.ok()) return null;
    const body = await response.json() as { items: Array<{ diameter?: number }> };
    return body.items[0]?.diameter ?? null;
  }, { timeout: 15_000 }).toBe(6);

  // The feature mutation must also propagate into the v2 project revision so the 3D
  // scene refreshes from canonical state instead of leaving a stale visual body.
  const project = await request.get(`${engineUrl}/v2/project`, { headers });
  expect(project.ok()).toBeTruthy();
  const snapshot = await project.json() as { parts: Array<{ id: string }> };
  expect(snapshot.parts.some((part) => part.id === partId)).toBeTruthy();
});
