import { expect, test } from '@playwright/test';

test('ForgeCAD production workbench starts blank, searches the expanded catalog, renders components, and moves parts', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();

  // Production startup must be genuinely blank: no acceptance fixture, sample assembly,
  // or pre-rendered component should appear in a fresh workspace.
  await expect(page.getByText('Untitled Design').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No geometry').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('0 objects').first()).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 20_000 });

  // Search must follow the newest query rather than being overwritten by a slower
  // startup request. This also proves the expanded standard-parts catalog is loaded.
  await page.getByRole('button', { name: 'Components', exact: true }).click();
  const search = page.getByPlaceholder('Search manufacturer, model, category…');
  await expect(search).toBeVisible();
  await search.fill('raspberry');
  const raspberry = page.getByTestId('component-compute.raspberry_pi_5_8gb');
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await search.fill('12mm precision shaft 500mm');
  const shaft = page.getByTestId('component-shaft.12x500');
  await expect(shaft).toBeVisible({ timeout: 20_000 });
  await expect(raspberry).toBeHidden();

  // A simple centered shaft is useful for a deterministic transform-gizmo test.
  await shaft.getByRole('button', { name: 'Insert', exact: true }).click();
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  let transformOperationSeen = false;
  page.on('request', (request) => {
    if (!request.url().endsWith('/v2/operations')) return;
    const body = request.postData() ?? '';
    if (body.includes('"op":"transform"')) transformOperationSeen = true;
  });

  const canvas = page.getByTestId('scene-canvas');
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + 60, cy + 18, { steps: 12 });
    await page.mouse.up();
  }
  await expect.poll(() => transformOperationSeen, { timeout: 20_000 }).toBe(true);
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  // Search remains live after a project mutation and can immediately target another SKU.
  await page.getByRole('button', { name: 'Components', exact: true }).click();
  await search.fill('raspberry');
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await raspberry.getByRole('button', { name: 'Insert', exact: true }).click();
  await expect(page.getByText('2 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  // A catalog SKU is not a one-shot demo card: the same real component can be inserted
  // again as a distinct assembly instance.
  await page.getByRole('button', { name: 'Components', exact: true }).click();
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await raspberry.getByRole('button', { name: 'Insert another', exact: true }).click();
  await expect(page.getByText('3 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  // New returns to a clean CAD document rather than restoring sample geometry.
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'New', exact: true }).click();
  await expect(page.getByText('Untitled Design').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No geometry').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('0 objects').first()).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 20_000 });
});