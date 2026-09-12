import { expect, test } from '@playwright/test';

test('ForgeCAD production workbench starts blank, exposes the full catalog, renders components, and moves parts', async ({ page, request }) => {
  // Each browser attempt gets a deterministic blank document. The engine process is
  // intentionally reused by CI, so a failed/retried browser test must not inherit CAD state.
  const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };
  const reset = await request.post('http://127.0.0.1:8765/v2/operations', {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset Windows browser acceptance workspace' },
  });
  expect(reset.ok()).toBeTruthy();

  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();
  await expect(page.getByText('Untitled Design').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No geometry').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('0 objects').first()).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 20_000 });

  // Regression for the release bug where the registry contained >1,000 parts but the
  // workbench/API silently exposed only the first 30. The unfiltered library must expose
  // every locally registered component, and the UI count must match the registry count.
  const statsResponse = await request.get('http://127.0.0.1:8765/v2/component-registry/stats', { headers });
  expect(statsResponse.ok()).toBeTruthy();
  const stats = await statsResponse.json() as { total: number };
  expect(stats.total).toBeGreaterThan(30);
  const catalogResponse = await request.get('http://127.0.0.1:8765/v2/components?q=', { headers });
  expect(catalogResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json() as { items: unknown[] };
  expect(catalog.items.length).toBe(stats.total);

  await page.getByRole('button', { name: 'Components', exact: true }).click();
  const search = page.getByPlaceholder('Search manufacturer, model, category…');
  await expect(search).toBeVisible();
  await expect(page.locator('.result-count')).toHaveText(`${stats.total} results`, { timeout: 30_000 });

  await search.fill('raspberry');
  const raspberry = page.getByTestId('component-compute.raspberry_pi_5_8gb');
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await search.fill('12mm precision shaft 500mm');
  const shaft = page.getByTestId('component-shaft.12x500');
  await expect(shaft).toBeVisible({ timeout: 20_000 });
  await expect(raspberry).toBeHidden();

  // Insert a simple centered shaft and make selection explicit. This verifies the same
  // object-selection path a user uses before manipulating a part.
  await shaft.getByRole('button', { name: 'Insert', exact: true }).click();
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });
  await page.locator('.object-row').first().click();
  await expect(page.locator('.selection-chip')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Object properties').first()).toBeVisible();

  let transformOperationSeen = false;
  page.on('request', (outgoing) => {
    if (!outgoing.url().endsWith('/v2/operations')) return;
    const body = outgoing.postData() ?? '';
    if (body.includes('"op":"transform"')) transformOperationSeen = true;
  });

  const canvas = page.getByTestId('scene-canvas');
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    // With the single shaft selected and Fit active, its transform origin projects at
    // the viewport center. Move across the X-axis handle to establish hover, then drag.
    await page.mouse.move(cx + 34, cy + 2, { steps: 4 });
    await page.waitForTimeout(100);
    await page.mouse.down();
    await page.mouse.move(cx + 104, cy + 12, { steps: 16 });
    await page.mouse.up();
  }
  await expect.poll(() => transformOperationSeen, { timeout: 20_000 }).toBe(true);
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });
  await expect(page.locator('.selection-chip')).toBeVisible();

  // Search remains live after a transform and can immediately target another SKU.
  await page.getByRole('button', { name: 'Components', exact: true }).click();
  await search.fill('raspberry');
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await raspberry.getByRole('button', { name: 'Insert', exact: true }).click();
  await expect(page.getByText('2 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  await page.getByRole('button', { name: 'Components', exact: true }).click();
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await raspberry.getByRole('button', { name: 'Insert another', exact: true }).click();
  await expect(page.getByText('3 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'New', exact: true }).click();
  await expect(page.getByText('Untitled Design').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No geometry').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('0 objects').first()).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 20_000 });
});