import { expect, test, type APIRequestContext } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

type ProjectSnapshot = {
  parts: Array<{ id: string; name: string }>;
};

async function operation(request: APIRequestContext, op: string, args: Record<string, unknown>, reason: string) {
  const response = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op, args, reason },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return await response.json() as { project: ProjectSnapshot };
}

async function addBox(request: APIRequestContext, name: string, position: [number, number, number]) {
  const result = await operation(request, 'add', {
    name,
    kind: 'box',
    params: { x: 6, y: 6, z: 6 },
    material: 'aluminum_6061_t6',
    transform: { position, rotation_deg: [0, 0, 0], scale: [1, 1, 1] },
  }, `Create ${name} simulation fixture`);
  const part = result.project.parts.find((row) => row.name === name);
  expect(part, `Expected ${name} to exist after add`).toBeTruthy();
  return part!.id;
}

async function setupMechanism(request: APIRequestContext) {
  await operation(request, 'new_project', {}, 'Reset 6.1 simulation browser fixture');
  const baseId = await addBox(request, 'Simulation Base', [0, 0, 0]);
  const armId = await addBox(request, 'Simulation Arm', [10, 0, 0]);
  const payloadId = await addBox(request, 'Simulation Payload', [20, 0, 0]);

  await operation(request, 'add_joint', {
    id: 'browser-hinge',
    name: 'Browser Hinge',
    type: 'revolute',
    parent_id: baseId,
    child_id: armId,
    origin_mm: [0, 0, 0],
    axis: [0, 0, 1],
    lower_deg: -180,
    upper_deg: 180,
    home_deg: 0,
  }, 'Create browser hinge');
  await operation(request, 'add_joint', {
    id: 'browser-payload-fixed',
    name: 'Browser Payload Mount',
    type: 'fixed',
    parent_id: armId,
    child_id: payloadId,
    origin_mm: [10, 0, 0],
    axis: [0, 0, 1],
  }, 'Create fixed payload mount');

  return { baseId, armId, payloadId };
}

test('6.1 Analyze simulates a joint sweep, propagates the payload, emits viewport playback, and leaves canonical pose unchanged', async ({ page, request }) => {
  const { armId, payloadId } = await setupMechanism(request);

  const graphResponse = await request.get(`${engineUrl}/v6/simulation/assembly/graph`, { headers });
  expect(graphResponse.ok()).toBeTruthy();
  const graph = await graphResponse.json() as { ok: boolean; joint_count: number };
  expect(graph.ok).toBe(true);
  expect(graph.joint_count).toBe(2);

  const sceneBeforeResponse = await request.get(`${engineUrl}/v2/scene`, { headers });
  expect(sceneBeforeResponse.ok()).toBeTruthy();
  const sceneBefore = await sceneBeforeResponse.json() as {
    parts: Array<{ id: string; base_transform: { position: number[]; rotation_deg: number[] } }>;
  };
  const beforePayload = sceneBefore.parts.find((part) => part.id === payloadId);
  expect(beforePayload).toBeTruthy();
  expect(beforePayload!.base_transform.position[0]).toBeCloseTo(20, 5);
  expect(beforePayload!.base_transform.position[1]).toBeCloseTo(0, 5);

  await page.goto('/');
  await expect(page.getByText('Simulation Base', { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: 'Analyze', exact: true }).click();

  const workspace = page.getByTestId('simulation-workspace');
  await expect(workspace).toBeVisible({ timeout: 20_000 });
  await expect(workspace).toContainText('One canonical assembly state drives constrained motion');
  const hinge = page.getByTestId('simulation-joint-browser-hinge');
  await expect(hinge).toBeVisible();
  await expect(hinge).toContainText('Browser Hinge');

  await page.evaluate(() => {
    const target = window as typeof window & { __forgecadSimulationPreview?: unknown };
    target.__forgecadSimulationPreview = null;
    window.addEventListener('forgecad:simulation-preview', (event) => {
      target.__forgecadSimulationPreview = (event as CustomEvent).detail;
    }, { once: true });
  });

  await page.getByLabel('Browser Hinge Angle').fill('90');
  await page.getByLabel('Sweep duration').fill('0.25');
  await page.getByLabel('Sweep samples').fill('5');
  await hinge.getByRole('button', { name: 'Simulate sweep' }).click();

  await page.waitForFunction(() => Boolean((window as typeof window & { __forgecadSimulationPreview?: unknown }).__forgecadSimulationPreview), null, { timeout: 30_000 });
  const preview = await page.evaluate(() => (window as typeof window & {
    __forgecadSimulationPreview?: { frames?: Array<{ transforms?: Record<string, { position?: number[] }> }> };
  }).__forgecadSimulationPreview);
  expect(preview?.frames).toHaveLength(5);
  const lastFrame = preview!.frames![4]!;
  expect(lastFrame.transforms?.[armId]?.position?.[0]).toBeCloseTo(0, 4);
  expect(lastFrame.transforms?.[armId]?.position?.[1]).toBeCloseTo(10, 4);
  expect(lastFrame.transforms?.[payloadId]?.position?.[0]).toBeCloseTo(0, 4);
  expect(lastFrame.transforms?.[payloadId]?.position?.[1]).toBeCloseTo(20, 4);

  await expect(page.getByTestId('simulation-results')).toContainText('multibody_motion');
  await expect(page.getByTestId('simulation-results')).toContainText('CURRENT');

  // A sweep is a simulation preview, not a design edit. The canonical scene remains
  // at the original pose after playback finishes.
  const sceneAfterResponse = await request.get(`${engineUrl}/v2/scene`, { headers });
  expect(sceneAfterResponse.ok()).toBeTruthy();
  const sceneAfter = await sceneAfterResponse.json() as typeof sceneBefore;
  const afterPayload = sceneAfter.parts.find((part) => part.id === payloadId);
  expect(afterPayload).toBeTruthy();
  expect(afterPayload!.base_transform.position[0]).toBeCloseTo(20, 5);
  expect(afterPayload!.base_transform.position[1]).toBeCloseTo(0, 5);
});
