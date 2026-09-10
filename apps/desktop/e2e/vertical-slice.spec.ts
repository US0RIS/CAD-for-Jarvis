import { expect, test } from '@playwright/test';

test('vertical slice stays interactive and contained end to end', async ({ page }) => {
  // Temporary diagnostics: the Windows CI run of this spec has failed for several
  // pushes in a row with the branch-lineage data never appearing, in ways that
  // don't fit a timing explanation and survived a CORS/Private-Network-Access
  // fix. The Playwright HTML report (screenshots/traces) isn't reachable from
  // this environment, so surface what actually happens on the wire and in the
  // page directly into the CI text log instead.
  page.on('console', (msg) => console.log(`[browser console:${msg.type()}]`, msg.text()));
  page.on('pageerror', (err) => console.log('[browser pageerror]', err.stack ?? String(err)));
  page.on('requestfailed', (req) => console.log('[browser requestfailed]', req.url(), req.failure()?.errorText));
  page.on('response', (res) => {
    if (res.url().endsWith('/v2/project')) {
      res.text().then((body) => console.log('[project body]', body.slice(0, 4000))).catch((err) => console.log('[project body read failed]', String(err)));
    }
    if (res.url().includes('/v2/') || res.url().includes(':8765')) {
      console.log('[browser response]', res.status(), res.url());
    }
  });

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

  // Dump the actual DOM state right before the assertion that keeps failing on CI, so a
  // failure shows exactly what was (or wasn't) there instead of just "not found".
  const domSnapshot = await page.evaluate(() => ({
    branchCardCount: document.querySelectorAll('.branch-card').length,
    branchCardTexts: [...document.querySelectorAll('.branch-card')].map((el) => el.textContent),
    lineageFlowHtml: document.querySelector('.lineage-flow')?.outerHTML?.slice(0, 1500) ?? '<lineage-flow not found>',
  }));
  console.log('[dom snapshot before branch-card check]', JSON.stringify(domSnapshot));

  // Branch cards are real controls rather than decorative UI. Use text content rather
  // than the computed accessible name because branch metadata can change the latter.
  const piBranch = page.locator('.branch-card').filter({ hasText: 'pi-control-v2' }).first();
  await expect(piBranch).toBeVisible();
  await piBranch.click();
  await expect(piBranch).toHaveAttribute('aria-pressed', 'true');

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
  // Scope to the lineage strip, not a bare page-wide text match: once this branch
  // becomes active, its name also appears in the toolbar's branch-select button,
  // which would otherwise make this locator ambiguous (strict-mode violation).
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
