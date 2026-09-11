import { expect, test } from '@playwright/test';

test('vertical slice stays interactive and contained end to end', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY');

  // An installed project must open assembled, never in a surprise exploded state.
  const slider = page.getByTestId('explode-slider');
  await expect(page.getByTestId('explode-percent')).toHaveText('0%');
  await slider.fill('70');
  await expect(page.getByTestId('explode-percent')).toHaveText('70%');
  await slider.fill('0');

  // Branch cards are real controls rather than decorative UI. Use text content rather
  // than the computed accessible name because branch metadata can change the latter.
  const piBranch = page.locator('.branch-card').filter({ hasText: 'pi-control-v2' }).first();
  await expect(piBranch).toBeVisible({ timeout: 20_000 });
  await piBranch.click();
  await expect(piBranch).toHaveAttribute('aria-pressed', 'true', { timeout: 20_000 });

  await page.getByTestId('tab-notebook').click();
  await expect(page.locator('.dock-content')).toContainText('NOTEBOOK');
  await page.getByTestId('tab-code').click();
  await expect(page.getByTestId('code-workspace')).toBeVisible();
  await expect(page.getByTestId('monaco-host')).toBeVisible();

  // Every visible component card must have a renderable local image, including fallback imagery.
  const images = page.locator('.component-card img');
  await expect(images).toHaveCount(3);
  await expect.poll(async () => images.evaluateAll((nodes) => nodes.every((node) => {
    const image = node as HTMLImageElement;
    return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
  })), { timeout: 20_000 }).toBe(true);

  const firstAdd = page.locator('.component-card .add-button').first();
  await firstAdd.click();
  await expect(page.getByTestId('component-jf-0530b-12v')).toContainText('Added');

  const request = 'Swap in a 12V solenoid on a safe child branch and keep the baseline protected.';
  await page.locator('.composer textarea').fill(request);
  await page.getByTestId('send-button').click();
  await expect(page.getByTestId('conversation')).toContainText(request);
  await expect(page.locator('.branch-card').filter({ hasText: 'solenoid-swap-2' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('conversation')).toContainText('safe experimental branch', { timeout: 20_000 });

  // Long/streamed chat can scroll internally, but it must never displace the composer off-screen.
  const composer = page.getByTestId('composer');
  await expect(composer).toBeVisible();
  const box = await composer.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(viewport?.height ?? 992);
});
