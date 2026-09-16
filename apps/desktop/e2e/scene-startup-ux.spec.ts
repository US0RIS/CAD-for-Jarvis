import { expect, test, type APIRequestContext } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

async function resetWithPi(request: APIRequestContext) {
  const reset = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset scene-startup regression workspace' },
  });
  expect(reset.ok()).toBeTruthy();
  const added = await request.post(`${engineUrl}/v2/components/compute.raspberry_pi_5_8gb/add`, { headers });
  expect(added.ok()).toBeTruthy();
}

test('3D startup failure is visible and automatically recovers instead of hanging at STARTING 3D', async ({ page, request }) => {
  await resetWithPi(request);

  let sceneAttempts = 0;
  await page.route('**/v2/scene', async (route) => {
    sceneAttempts += 1;
    if (sceneAttempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Injected transient 3D startup failure' }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto('/');

  await expect(page.getByTestId('scene-startup-error')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('scene-startup-error')).toContainText('Injected transient 3D startup failure');
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 30_000 });
  await expect(page.getByTestId('scene-startup-error')).toHaveCount(0);
  expect(sceneAttempts).toBeGreaterThanOrEqual(2);
});

test('viewport does not request scene geometry before the canonical project revision exists', async ({ page, request }) => {
  await resetWithPi(request);

  let projectResolved = false;
  let prematureSceneRequest = false;
  let sceneRequests = 0;

  await page.route('**/v2/project', async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 250));
    projectResolved = true;
    await route.fulfill({ response });
  });
  await page.route('**/v2/scene', async (route) => {
    sceneRequests += 1;
    if (!projectResolved) prematureSceneRequest = true;
    await route.continue();
  });

  await page.goto('/');
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 30_000 });

  expect(prematureSceneRequest).toBeFalsy();
  expect(sceneRequests).toBe(1);
});
