import { expect, test } from '@playwright/test';

test('full ForgeCAD engineering workbench stays interactive end to end', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 60_000 });

  // The canonical OpenCascade scene opens assembled and the viewport remains interactive.
  const slider = page.getByTestId('explode-slider');
  await expect(page.getByTestId('explode-percent')).toHaveText('0%');
  await slider.fill('70');
  await expect(page.getByTestId('explode-percent')).toHaveText('70%');
  await slider.fill('0');

  // Design history is real state, not decorative labels.
  const piBranch = page.locator('.branch-card').filter({ hasText: 'pi-control-v2' }).first();
  await expect(piBranch).toBeVisible({ timeout: 30_000 });
  await piBranch.click();
  await expect(piBranch).toHaveAttribute('aria-pressed', 'true', { timeout: 30_000 });

  // The real Raspberry Pi 5 carries its embedded workspace with the design branch.
  await page.getByTestId('tab-code').click();
  await expect(page.getByTestId('code-workspace')).toBeVisible();
  await expect(page.getByTestId('monaco-host')).toBeVisible();

  // The local component catalog is the full engineering registry and is constraint-filterable.
  const search = page.getByPlaceholder('Search 238+ real components');
  await expect(search).toBeVisible();
  await search.fill('raspberry');
  await expect(page.getByTestId('component-compute.raspberry_pi_5_8gb')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/catalog/).first()).toBeVisible();
  await search.fill('stepper');
  const firstAdd = page.locator('.component-card .add-button').first();
  await expect(firstAdd).toBeVisible({ timeout: 20_000 });
  await expect(firstAdd).toBeEnabled();
  await firstAdd.click();
  await expect(page.locator('.component-card .add-button').first()).toContainText('Added', { timeout: 20_000 });

  // Design workbench exposes project bundles, STEP import, BOM, branch status and real diffs.
  await page.getByRole('button', { name: 'Design', exact: true }).click();
  await expect(page.getByTestId('design-inspector')).toBeVisible();
  await expect(page.getByTestId('import-step')).toBeVisible();
  await expect(page.getByText('Portable project + CAD import')).toBeVisible();
  await expect(page.getByText('Bill of materials')).toBeVisible();
  await page.getByRole('button', { name: /Compare to working branch/ }).click();
  await expect(page.getByTestId('design-inspector')).toContainText('changes', { timeout: 20_000 });

  // Analysis is an actual engineering job: structural/modal/thermal/manufacturing/system checks.
  await page.getByRole('button', { name: 'Analysis', exact: true }).click();
  await expect(page.getByTestId('analysis-workspace')).toBeVisible();
  await expect(page.getByTestId('analysis-workspace')).toContainText('Real component registry');
  await page.getByRole('button', { name: 'Run engineering screen' }).click();
  await expect(page.getByTestId('analysis-workspace')).toContainText('simulation: completed', { timeout: 90_000 });
  await expect(page.getByTestId('analysis-workspace')).toContainText('structural', { timeout: 20_000 });

  // AI edits fork safely from a design branch and use the canonical typed operation layer.
  const request = 'Swap in a 12V solenoid on a safe child branch and keep the baseline protected.';
  await page.locator('.composer textarea').fill(request);
  await page.getByTestId('send-button').click();
  await expect(page.getByTestId('conversation')).toContainText(request);
  await expect(page.locator('.branch-card').filter({ hasText: 'solenoid-swap-2' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('conversation')).toContainText('safe experimental branch', { timeout: 30_000 });

  const composer = page.getByTestId('composer');
  await expect(composer).toBeVisible();
  const box = await composer.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(viewport?.height ?? 992);
});
