import { expect, test } from '@playwright/test';

test('ForgeCAD workbench starts clean and real component insertion updates the 3D scene', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  // CI starts with the deterministic engineering fixture so geometry, branches, and
  // embedded code remain covered independently from the production blank-start path.
  const slider = page.getByTestId('explode-slider');
  await expect(slider).toBeVisible();
  await slider.fill('70');
  await expect(page.getByTestId('explode-percent')).toHaveText('70%');
  await slider.fill('0');

  const piBranch = page.locator('.branch-card').filter({ hasText: 'pi-control-v2' }).first();
  await expect(piBranch).toBeVisible({ timeout: 30_000 });
  await piBranch.click();
  await expect(piBranch).toHaveAttribute('aria-pressed', 'true', { timeout: 30_000 });
  await page.getByTestId('tab-code').click();
  await expect(page.getByTestId('code-workspace')).toBeVisible();
  await expect(page.getByTestId('monaco-host')).toBeVisible();

  // Production behavior: a new document is genuinely empty instead of silently
  // opening the acceptance fixture or rendering sample hardware.
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'New', exact: true }).click();
  await expect(page.getByText('Untitled Design').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No geometry')).toBeVisible();
  await expect(page.getByText('0 objects').first()).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 20_000 });

  // Catalog insertion is a real design mutation. It must create a new object,
  // tessellate it, reload the viewport, and permit multiple instances of one SKU.
  await page.getByRole('button', { name: 'Components', exact: true }).click();
  const search = page.getByPlaceholder('Search manufacturer, model, category…');
  await expect(search).toBeVisible();
  await search.fill('raspberry');
  const raspberry = page.getByTestId('component-compute.raspberry_pi_5_8gb');
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  const insert = raspberry.getByRole('button', { name: /Insert/ });
  await insert.click();
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  await page.getByRole('button', { name: 'Components', exact: true }).click();
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await raspberry.getByRole('button', { name: /Insert another/ }).click();
  await expect(page.getByText('2 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  // AI is available as an engineering tool, not the visual center of the product.
  await page.getByRole('button', { name: 'Copilot', exact: true }).click();
  const composer = page.getByTestId('composer');
  await expect(composer).toBeVisible();
  await composer.locator('textarea').fill('List the two inserted components and do not edit the design.');
  await composer.getByText('Allow edits').click();
  await page.getByTestId('send-button').click();
  await expect(page.getByTestId('conversation')).toContainText('List the two inserted components');

  const box = await composer.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(viewport?.height ?? 992);
});
