import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

async function resetWithPi(request: APIRequestContext) {
  const reset = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset minimum-window UX workspace' },
  });
  expect(reset.ok()).toBeTruthy();
  const added = await request.post(`${engineUrl}/v2/components/compute.raspberry_pi_5_8gb/add`, { headers });
  expect(added.ok()).toBeTruthy();
}

async function expectInsideViewport(page: Page, selector: string) {
  const overflow = await page.locator(selector).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: window.innerWidth,
      height: window.innerHeight,
    };
  });
  expect(overflow.left).toBeGreaterThanOrEqual(0);
  expect(overflow.right).toBeLessThanOrEqual(overflow.width + 0.5);
  expect(overflow.top).toBeGreaterThanOrEqual(0);
  expect(overflow.bottom).toBeLessThanOrEqual(overflow.height + 0.5);
}

test('packaged 1280x760 minimum keeps core shell and primary bottom workspaces usable', async ({ page, request }) => {
  await resetWithPi(request);
  await page.setViewportSize({ width: 1280, height: 760 });
  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });

  // The shell must not solve density by silently clipping essential chrome.
  await expectInsideViewport(page, '.app-bar');
  await expectInsideViewport(page, '.left-panel');
  await expectInsideViewport(page, '.right-panel');
  await expect(page.getByTestId('open-focad')).toBeVisible();
  await expect(page.getByTestId('export-focad')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Keyboard shortcuts' })).toBeVisible();
  const chromeFits = await page.locator('.app-bar').evaluate((bar) => {
    const children = Array.from(bar.children).filter((node) => (node as HTMLElement).offsetParent !== null);
    const bounds = bar.getBoundingClientRect();
    return children.every((node) => {
      const rect = node.getBoundingClientRect();
      return rect.left >= bounds.left - 0.5 && rect.right <= bounds.right + 0.5;
    });
  });
  expect(chromeFits).toBeTruthy();

  // Open the embedded IDE through the same object workflow a user follows.
  await page.locator('.object-row').first().click();
  await page.getByRole('button', { name: 'Properties', exact: true }).click();
  await page.getByRole('button', { name: 'Open embedded code' }).click();
  const code = page.locator('.code-panel');
  await expect(code).toBeVisible();
  const codeBox = await code.boundingBox();
  expect(codeBox?.height ?? 0).toBeGreaterThanOrEqual(249);
  await expectInsideViewport(page, '.code-panel');

  // The physical/deployed System inspector is also a real work surface rather than
  // a generic 238px tray at the desktop minimum.
  await page.getByTestId('tab-system').click();
  const system = page.getByTestId('world-system-panel');
  await expect(system).toBeVisible({ timeout: 15_000 });
  const systemBox = await system.boundingBox();
  expect(systemBox?.height ?? 0).toBeGreaterThanOrEqual(279);
  await expectInsideViewport(page, '[data-testid="world-system-panel"]');

  // No document-level horizontal overflow is allowed at the packaged minimum size.
  const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
});
