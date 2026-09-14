import { expect, test } from '@playwright/test';

test('ForgeCAD 3.1 exposes engineering graph, Product Lab, and physical evidence in SYSTEM', async ({ page, request }) => {
  const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

  const reset = await request.post('http://127.0.0.1:8765/v2/operations', {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset ForgeCAD 3.1 browser acceptance workspace' },
  });
  expect(reset.ok()).toBeTruthy();

  const created = await request.post('http://127.0.0.1:8765/v3.1/cad/parts', {
    headers,
    data: {
      name: 'Product Lab Wrist Housing',
      kind: 'box',
      params: { x: 72, y: 42, z: 14 },
      material: 'aluminum_6061_t6',
      semantic: { role: 'wearable_housing', manufacturing_process: 'cnc' },
    },
  });
  expect(created.ok()).toBeTruthy();
  const createdPayload = await created.json() as { project: { objects: Array<{ id: string; name: string }> } };
  const part = createdPayload.project.objects.find((row) => row.name === 'Product Lab Wrist Housing');
  expect(part).toBeTruthy();

  const feature = await request.post(`http://127.0.0.1:8765/v3.1/cad/objects/${part?.id}/features`, {
    headers,
    data: { type: 'slot', name: 'Strap Slot', parameters: { length: 24, width: 5, depth: 14 } },
  });
  expect(feature.ok()).toBeTruthy();

  const profile = await request.put('http://127.0.0.1:8765/v3.1/product-profile', {
    headers,
    data: {
      mode: 'product_lab',
      name: 'Wearable acceptance product',
      envelope_mm: [120, 80, 50],
      max_mass_g: 500,
      human_contact: true,
      wearable: true,
      stored_energy_limit_j: 50,
      max_surface_temperature_c: 43,
      preferred_processes: ['cnc', 'fdm'],
    },
  });
  expect(profile.ok()).toBeTruthy();

  const inspection = await request.post('http://127.0.0.1:8765/v3.1/physical/inspections', {
    headers,
    data: {
      object_id: part?.id,
      metric: 'x_mm',
      observed: 72.8,
      expected: 72,
      unit: 'mm',
      tolerance: 0.2,
      instrument: 'browser-acceptance-caliper',
      confidence: 0.99,
    },
  });
  expect(inspection.ok()).toBeTruthy();

  const healthResponse = await request.get('http://127.0.0.1:8765/v3.1/health');
  expect(healthResponse.ok()).toBeTruthy();
  const health = await healthResponse.json() as {
    ok: boolean;
    api_version: string;
    engine_version: string;
    engineering_graph: { ready: boolean; node_count: number; dirty_node_count: number; graph_revision: string };
    profile: { mode: string };
  };
  expect(health.ok).toBe(true);
  expect(health.api_version).toBe('3.1');
  expect(health.engine_version).toBe('3.1.0');
  expect(health.engineering_graph.ready).toBe(true);
  expect(health.engineering_graph.node_count).toBeGreaterThanOrEqual(5);
  expect(health.engineering_graph.dirty_node_count).toBeGreaterThan(0);
  expect(health.profile.mode).toBe('product_lab');

  const nodeResponse = await request.get(`http://127.0.0.1:8765/v3.1/graph/nodes/cad:${part?.id}`, { headers });
  expect(nodeResponse.ok()).toBeTruthy();
  const node = await nodeResponse.json() as {
    node: { dirty: boolean; dirty_reasons: string[] };
    evidence: Array<{ kind: string; status: string }>;
  };
  expect(node.node.dirty).toBe(true);
  expect(node.node.dirty_reasons.some((reason) => reason.includes('physical inspection deviation'))).toBe(true);
  expect(node.evidence.some((row) => row.kind === 'physical_inspection' && row.status === 'fail')).toBe(true);

  const jarvisResponse = await request.get('http://127.0.0.1:8765/v3.1/jarvis/context', { headers });
  expect(jarvisResponse.ok()).toBeTruthy();
  const jarvis = await jarvisResponse.json() as { engine_version: string; engineering_graph_revision: string; profile: { mode: string }; nodes: Array<{ id: string }> };
  expect(jarvis.engine_version).toBe('3.1.0');
  expect(jarvis.engineering_graph_revision).toBeTruthy();
  expect(jarvis.profile.mode).toBe('product_lab');
  expect(jarvis.nodes.some((row) => row.id === `cad:${part?.id}`)).toBe(true);

  await page.goto('/');
  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  const objectRow = page.locator('.object-row').filter({ hasText: /Product Lab Wrist Housing/i }).first();
  await expect(objectRow).toBeVisible({ timeout: 20_000 });
  await objectRow.click();

  // Avoid unrelated component-thumbnail rendering before measuring SYSTEM readiness.
  await page.locator('.right-tabs button').filter({ hasText: /^Properties$/ }).click();
  await page.getByTestId('tab-system').click();

  const system = page.getByTestId('world-system-panel');
  await expect(system).toBeVisible({ timeout: 20_000 });
  const graph = page.getByTestId('engineering-graph-status');
  await expect(graph).toBeVisible({ timeout: 30_000 });
  await expect(graph.getByText('ENGINEERING GRAPH', { exact: true })).toBeVisible();
  await expect(graph.getByText('Current', { exact: true })).toBeVisible({ timeout: 30_000 });

  const productLab = page.getByTestId('product-lab-profile');
  await expect(productLab.getByRole('button', { name: 'Product Lab', exact: true })).toBeVisible();
  await expect(productLab.getByText(/Compact-product engineering profile/)).toBeVisible();

  const selected = page.getByTestId('engineering-selected-context');
  await expect(selected.getByText('Product Lab Wrist Housing', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(selected.getByText('DIRTY', { exact: true })).toBeVisible();
  await expect(selected.getByText(/physical inspection deviation: x_mm/)).toBeVisible();
});
