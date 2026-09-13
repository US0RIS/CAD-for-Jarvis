import { expect, test } from '@playwright/test';

test('ForgeCAD 3.0 exposes the canonical physical world in the desktop SYSTEM dock', async ({ page, request }) => {
  const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

  const reset = await request.post('http://127.0.0.1:8765/v2/operations', {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset ForgeCAD 3.0 world-browser acceptance workspace' },
  });
  expect(reset.ok()).toBeTruthy();

  const added = await request.post('http://127.0.0.1:8765/v2/components/compute.raspberry_pi_5_8gb/add', {
    headers,
  });
  expect(added.ok()).toBeTruthy();
  const addedPayload = await added.json() as { component: { instance_id?: string | null } };
  const piObjectId = addedPayload.component.instance_id;
  expect(piObjectId).toBeTruthy();

  const healthResponse = await request.get('http://127.0.0.1:8765/v3/health');
  expect(healthResponse.ok()).toBeTruthy();
  const health = await healthResponse.json() as {
    ok: boolean;
    api_version: string;
    engine_version: string;
    world: { entity_count: number; revision: number };
    project_sync: { ok: boolean; project_object_count?: number };
  };
  expect(health.ok).toBe(true);
  expect(health.api_version).toBe('3');
  expect(health.engine_version).toBe('3.0.0');
  expect(health.project_sync.ok).toBe(true);
  expect(health.project_sync.project_object_count).toBe(1);
  expect(health.world.entity_count).toBeGreaterThanOrEqual(3);

  const computeResponse = await request.get('http://127.0.0.1:8765/v3/world/entities?capability=compute.execute', { headers });
  expect(computeResponse.ok()).toBeTruthy();
  const compute = await computeResponse.json() as {
    items: Array<{
      id: string;
      source_links: Record<string, string>;
      capabilities: Array<{ name: string }>;
    }>;
  };
  const piEntity = compute.items.find((entity) => entity.source_links.forgecad_object_id === piObjectId);
  expect(piEntity).toBeTruthy();
  expect(piEntity?.source_links.component_ref).toBe('compute.raspberry_pi_5_8gb');
  expect(piEntity?.capabilities.some((capability) => capability.name === 'software.deploy')).toBe(true);

  const observation = await request.post('http://127.0.0.1:8765/v3/world/observations', {
    headers,
    data: {
      entity_id: piEntity?.id,
      key: 'cpu_temperature_c',
      value: 47.25,
      unit: 'degC',
      source: 'sensor',
      source_id: 'browser-acceptance:pi-temp',
      confidence: 0.99,
    },
  });
  expect(observation.ok()).toBeTruthy();

  const resolution = await request.get(
    `http://127.0.0.1:8765/v3/jarvis/resolve?q=${encodeURIComponent(piEntity?.id ?? '')}`,
    { headers },
  );
  expect(resolution.ok()).toBeTruthy();
  const resolved = await resolution.json() as { status: string; entity_id?: string | null; exact: boolean };
  expect(resolved.status).toBe('resolved');
  expect(resolved.entity_id).toBe(piEntity?.id);
  expect(resolved.exact).toBe(true);

  const eventsResponse = await request.get('http://127.0.0.1:8765/v3/world/events?limit=40', { headers });
  expect(eventsResponse.ok()).toBeTruthy();
  const events = await eventsResponse.json() as { revision: number; items: Array<{ type: string; entity_id?: string | null }> };
  expect(events.revision).toBeGreaterThan(0);
  expect(events.items.some((event) => event.type === 'observation.recorded' && event.entity_id === piEntity?.id)).toBe(true);

  const architecture = await request.post('http://127.0.0.1:8765/v2/design/architecture', {
    headers,
    data: { text: 'Inspect the Raspberry Pi in the current physical system.', use_model: false },
  });
  expect(architecture.ok()).toBeTruthy();
  const architecturePayload = await architecture.json() as {
    physical_world?: {
      entities: Array<{ entity_id: string; design_addressable: boolean; forgecad_object_id?: string | null }>;
      authority_rules: string[];
    };
  };
  expect(architecturePayload.physical_world).toBeTruthy();
  const plannerPi = architecturePayload.physical_world?.entities.find((entity) => entity.entity_id === piEntity?.id);
  expect(plannerPi?.design_addressable).toBe(true);
  expect(plannerPi?.forgecad_object_id).toBe(piObjectId);
  expect(architecturePayload.physical_world?.authority_rules.some((rule) => rule.includes('Only source_links.forgecad_object_id'))).toBe(true);

  await page.goto('/');
  await expect(page.getByText('ForgeCAD').first()).toBeVisible();
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  const piObject = page.locator('.object-row').filter({ hasText: /Raspberry Pi/i }).first();
  await expect(piObject).toBeVisible({ timeout: 20_000 });
  await piObject.click();

  await page.getByTestId('tab-system').click();
  const system = page.getByTestId('world-system-panel');
  await expect(system).toBeVisible({ timeout: 20_000 });
  await expect(system.getByText('PHYSICAL WORLD', { exact: true })).toBeVisible();
  await expect(system.getByText('Project sync', { exact: true })).toBeVisible();
  await expect(system.getByText('Current', { exact: true })).toBeVisible();
  await expect(page.getByTestId('world-entity-count')).not.toHaveText('0');

  const detail = page.getByTestId('world-entity-detail');
  await expect(detail.getByText('compute.execute', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(detail.getByText('software.deploy', { exact: true })).toBeVisible();
  await expect(detail.getByText('compute.raspberry_pi_5_8gb', { exact: true })).toBeVisible();
  await expect(detail.getByText(/cpu_temperature_c:/)).toBeVisible();
  await expect(detail.getByText(/47\.25 degC/)).toBeVisible();
  await expect(detail.getByText(/browser-acceptance:pi-temp/)).toBeVisible();
});
