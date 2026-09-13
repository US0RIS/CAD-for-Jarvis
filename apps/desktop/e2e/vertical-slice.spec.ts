import { expect, test } from '@playwright/test';

test('ForgeCAD production workbench starts blank, exposes the full catalog with geometry thumbnails, round-trips .focad, renders components, moves parts, and prepares manufacturing', async ({ page, request }) => {
  // Each browser attempt gets a deterministic blank document. The engine process is
  // intentionally reused by CI, so a failed/retried browser test must not inherit CAD state.
  const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };
  const reset = await request.post('http://127.0.0.1:8765/v2/operations', {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset Windows browser acceptance workspace' },
  });
  expect(reset.ok()).toBeTruthy();

  // Verify the catalog contract before opening the renderer. This keeps API completeness
  // independent of any thumbnails that the visible catalog rows may generate afterward.
  const statsResponse = await request.get('http://127.0.0.1:8765/v2/component-registry/stats', { headers });
  expect(statsResponse.ok()).toBeTruthy();
  const stats = await statsResponse.json() as { total: number };
  expect(stats.total).toBeGreaterThanOrEqual(1400);
  const catalogResponse = await request.get('http://127.0.0.1:8765/v2/components?q=', { headers });
  expect(catalogResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json() as { items: Array<{ image?: { uri?: string } }> };
  expect(catalog.items.length).toBe(stats.total);
  expect(catalog.items.every((item) => item.image?.uri?.includes('/v2/component-images/'))).toBeTruthy();
  const gearResponse = await request.get('http://127.0.0.1:8765/v2/components?q=gear', { headers });
  expect(gearResponse.ok()).toBeTruthy();
  const gearSearch = await gearResponse.json() as { items: unknown[] };
  expect(gearSearch.items.length).toBeGreaterThan(30);

  // Thumbnail bytes are generated from the same canonical geometry as the 3D scene,
  // then cached. Exercise two materially different products before the browser consumes
  // those cached previews so the UI assertion is deterministic rather than timing-based.
  for (const componentId of ['shaft.12x500', 'compute.raspberry_pi_5_8gb']) {
    const thumbnailResponse = await request.get(`http://127.0.0.1:8765/v2/component-images/${componentId}`);
    expect(thumbnailResponse.ok()).toBeTruthy();
    expect(thumbnailResponse.headers()['content-type']).toContain('image/svg+xml');
    expect(thumbnailResponse.headers()['x-forgecad-thumbnail-source']).toBe('canonical-geometry');
    const thumbnailSvg = await thumbnailResponse.text();
    expect(thumbnailSvg).toContain('<polygon');
  }

  // .focad is a real portable interchange path, not only a renamed download. Export a
  // design through the production API and immediately import the exact bytes again.
  const exportResponse = await request.get('http://127.0.0.1:8765/v2/project/export', { headers });
  expect(exportResponse.ok()).toBeTruthy();
  expect(exportResponse.headers()['content-type']).toContain('application/vnd.forgecad.project+zip');
  expect(exportResponse.headers()['content-disposition']).toContain('.focad');
  const focadBytes = await exportResponse.body();
  expect(focadBytes.length).toBeGreaterThan(100);
  const importResponse = await request.post('http://127.0.0.1:8765/v2/project/import', {
    headers: { 'X-ForgeCAD-Session': 'test-session' },
    multipart: {
      file: { name: 'acceptance-roundtrip.focad', mimeType: 'application/vnd.forgecad.project+zip', buffer: focadBytes },
    },
  });
  expect(importResponse.ok()).toBeTruthy();

  await page.goto('/');

  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByTestId('runtime-banner')).toBeVisible();
  await expect(page.getByTestId('scene-canvas')).toBeVisible();
  await expect(page.getByTestId('open-focad')).toBeVisible();
  await expect(page.getByTestId('export-focad')).toBeVisible();
  await expect(page.getByText('Untitled Design').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('No geometry').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('0 objects').first()).toBeVisible();
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 20_000 });

  await page.getByRole('button', { name: 'Components', exact: true }).click();
  const search = page.getByPlaceholder('Search manufacturer, model, category…');
  await expect(search).toBeVisible();
  await expect(page.locator('.result-count')).toHaveText(`${stats.total} results`, { timeout: 30_000 });

  await search.fill('raspberry');
  const raspberry = page.getByTestId('component-compute.raspberry_pi_5_8gb');
  await expect(raspberry).toBeVisible({ timeout: 20_000 });
  await expect(raspberry.locator('img')).toHaveAttribute('src', /\/v2\/component-images\/compute\.raspberry_pi_5_8gb/, { timeout: 20_000 });
  await expect.poll(async () => raspberry.locator('img').evaluate((node) => (node as HTMLImageElement).naturalWidth), { timeout: 20_000 }).toBeGreaterThan(0);

  await search.fill('12mm precision shaft 500mm');
  const shaft = page.getByTestId('component-shaft.12x500');
  await expect(shaft).toBeVisible({ timeout: 20_000 });
  await expect(shaft.locator('img')).toHaveAttribute('src', /\/v2\/component-images\/shaft\.12x500/, { timeout: 20_000 });
  await expect.poll(async () => shaft.locator('img').evaluate((node) => (node as HTMLImageElement).naturalWidth), { timeout: 20_000 }).toBeGreaterThan(0);
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
    await page.mouse.move(cx + 34, cy + 2, { steps: 4 });
    await page.waitForTimeout(100);
    await page.mouse.down();
    await page.mouse.move(cx + 104, cy + 12, { steps: 16 });
    await page.mouse.up();
  }
  await expect.poll(() => transformOperationSeen, { timeout: 20_000 }).toBe(true);
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });
  await expect(page.locator('.selection-chip')).toBeVisible();

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

  // Manufacture is part of the workbench, not a detached exporter. Create one real
  // custom body through the typed operation surface, then verify the UI sees the P2S,
  // excludes no fabricated geometry, validates the body envelope, and exposes 3MF prep.
  const fabricated = await request.post('http://127.0.0.1:8765/v2/operations', {
    headers,
    data: {
      op: 'add',
      args: {
        name: 'Acceptance printable bracket',
        kind: 'box',
        params: { x: 42, y: 28, z: 5 },
        material: 'abs',
        semantic: { role: 'printable_bracket', tags: ['fabricated'], minimum_wall_mm: 2.4 },
      },
      reason: 'Manufacturing browser acceptance body',
    },
  });
  expect(fabricated.ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('toolbar-manufacture').click();
  await expect(page.getByTestId('manufacture-panel')).toBeVisible();
  await expect(page.getByText('Bambu Lab P2S').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Acceptance printable bracket')).toBeVisible();
  await expect(page.getByText('42.0 × 28.0 × 5.0 mm')).toBeVisible();
  await expect(page.getByText('FIT', { exact: true })).toBeVisible();
  const export3mfButton = page.getByRole('button', { name: 'Export geometry 3MF' });
  await expect(export3mfButton).toBeEnabled();

  const manufacturingStatus = await request.get('http://127.0.0.1:8765/v2/manufacturing/p2s', { headers });
  expect(manufacturingStatus.ok()).toBeTruthy();
  const manufacturing = await manufacturingStatus.json() as {
    fabricated_part_count: number;
    resource: { model: string };
    parts: Array<{ fits_build_volume: boolean; recommended_orientation?: string; orientation_analysis?: { evaluated_orientations: number } }>;
    plate_packing?: { plate_count: number };
  };
  expect(manufacturing.fabricated_part_count).toBe(1);
  expect(manufacturing.resource.model).toBe('P2S');
  expect(manufacturing.parts[0]?.fits_build_volume).toBeTruthy();
  expect(manufacturing.parts[0]?.orientation_analysis?.evaluated_orientations).toBe(24);
  expect(manufacturing.parts[0]?.recommended_orientation).toBeTruthy();
  expect(manufacturing.plate_packing?.plate_count).toBe(1);

  const geometry3mf = await request.post('http://127.0.0.1:8765/v2/manufacturing/p2s/export', {
    headers,
    data: { object_ids: [], tolerance_mm: 0.2 },
  });
  expect(geometry3mf.ok()).toBeTruthy();
  expect(geometry3mf.headers()['content-type']).toContain('model/3mf');
  expect(geometry3mf.headers()['x-forgecad-manufacturing-resource']).toBe('Bambu Lab P2S');
  expect(geometry3mf.headers()['x-forgecad-package-sha256']).toMatch(/^[0-9a-f]{64}$/);
  expect((await geometry3mf.body()).length).toBeGreaterThan(500);

  // The same export path used by a person must retain the exact package fingerprint so
  // physical observations can be tied back to the bytes that were actually printed.
  const downloadPromise = page.waitForEvent('download');
  await export3mfButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('P2S');
  const evidencePanel = page.getByTestId('manufacture-evidence');
  await expect(evidencePanel).toBeVisible({ timeout: 20_000 });
  await expect(evidencePanel.getByText(/SHA-256/)).toBeVisible();
  await evidencePanel.locator('textarea').fill('Acceptance prototype printed cleanly and fit the fixture.');
  await evidencePanel.getByRole('button', { name: 'Record successful print' }).click();
  await expect(page.getByText(/Physical prototype success recorded/)).toBeVisible({ timeout: 20_000 });

  const evidenceResponse = await request.get('http://127.0.0.1:8765/v2/evidence', { headers });
  expect(evidenceResponse.ok()).toBeTruthy();
  const evidence = await evidenceResponse.json() as { items: Array<{ kind: string; outcome?: string; package_sha256?: string; changes_design_status?: boolean }> };
  const printEvidence = evidence.items.find((item) => item.kind === 'manufacturing_evidence');
  expect(printEvidence?.outcome).toBe('success');
  expect(printEvidence?.package_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(printEvidence?.changes_design_status).toBe(false);

  // ForgeCAD 2.0's optimizer must be visible and usable from the CAD workbench rather
  // than existing only as a backend function. Use a deliberately permissive deflection
  // gate here so the fixture has at least one feasible branch, while retaining the
  // independent FoS gate and deterministic candidate ranking.
  await page.getByRole('button', { name: 'Analyze', exact: true }).click();
  const campaignConsole = page.getByTestId('campaign-console');
  await expect(campaignConsole).toBeVisible();
  await campaignConsole.locator('label').filter({ hasText: 'Max deflection' }).locator('input').fill('5');
  await campaignConsole.locator('label').filter({ hasText: 'Candidates' }).locator('input').fill('3');
  await page.getByTestId('run-campaign').click();
  const campaignResults = page.getByTestId('campaign-results');
  await expect(campaignResults).toBeVisible({ timeout: 90_000 });
  await expect(campaignResults.getByText('Best candidate selected')).toBeVisible();
  await expect(campaignResults.locator('.candidate-row')).toHaveCount(3);
  await expect(campaignResults.getByText('WINNER', { exact: true })).toBeVisible();
});