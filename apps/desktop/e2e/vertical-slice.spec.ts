import { expect, test } from '@playwright/test';

test('vertical slice stays interactive end to end', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY');

  const slider = page.getByTestId('explode-slider');
  await slider.fill('70');
  await expect(page.getByTestId('explode-percent')).toHaveText('70%');

  await page.getByTestId('tab-notebook').click();
  await expect(page.locator('.dock-content')).toContainText('NOTEBOOK');
  await page.getByTestId('tab-code').click();
  await expect(page.getByTestId('code-workspace')).toBeVisible();
  await expect(page.getByTestId('monaco-host')).toBeVisible();

  await expect(page.locator('.component-card img').first()).toBeVisible();

  const request = 'Swap in a 12V solenoid on a safe child branch and keep the baseline protected.';
  await page.locator('.composer textarea').fill(request);
  await page.getByTestId('send-button').click();
  await expect(page.getByTestId('conversation')).toContainText(request);
  await expect(page.getByText('solenoid-swap-2', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('conversation')).toContainText('safe experimental branch', { timeout: 20_000 });
});
