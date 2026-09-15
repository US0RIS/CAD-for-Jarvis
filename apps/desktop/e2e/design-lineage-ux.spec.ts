import { expect, test, type APIRequestContext } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

async function resetWithPi(request: APIRequestContext) {
  const reset = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset design-lineage UX workspace' },
  });
  expect(reset.ok()).toBeTruthy();
  const added = await request.post(`${engineUrl}/v2/components/compute.raspberry_pi_5_8gb/add`, { headers });
  expect(added.ok()).toBeTruthy();
}

test('design lineage is discoverable and supports branch, status, and canonical comparison workflows', async ({ page, request }) => {
  await resetWithPi(request);
  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });

  // Lineage management must be discoverable from the model browser rather than hidden
  // in an implementation-only engineering component.
  await page.getByTestId('manage-design-lineage').click();
  const lineage = page.getByTestId('design-lineage-panel');
  await expect(lineage).toBeVisible();
  await expect(lineage).toContainText('Physical verification can only come from revision-bound recorded evidence');

  const branchName = `ux-lineage-${Date.now()}`;
  await lineage.getByRole('textbox', { name: 'New branch name' }).fill(branchName);
  await lineage.getByTestId('create-design-branch').click();

  // Creating an experimental branch intentionally activates it so subsequent edits do
  // not mutate the known source branch.
  await expect(page.getByRole('combobox', { name: 'Active design branch' })).toHaveValue(branchName, { timeout: 15_000 });
  await expect(page.locator('.doc-tab small')).toHaveText(branchName);
  await expect(lineage).toContainText('Unverified');

  await lineage.getByRole('button', { name: 'Working', exact: true }).click();
  await expect(lineage.locator('.lineage-status')).toHaveText('Working');

  // Make a real canonical difference on the experimental branch, then prove the UI can
  // compare it against main without switching away from the active experiment.
  await page.locator('.object-row').first().click();
  await page.keyboard.press('Backspace');
  await expect(page.locator('.object-row')).toHaveCount(0, { timeout: 15_000 });

  const compareSelect = lineage.getByRole('combobox', { name: 'Compare active branch to' });
  await compareSelect.selectOption('main');
  await lineage.getByTestId('compare-design-branch').click();
  const diff = lineage.getByTestId('design-lineage-diff');
  await expect(diff).toBeVisible();
  await expect(diff).not.toContainText('0 canonical differences');
  await expect(diff).toContainText('main');

  const canonical = await request.get(`${engineUrl}/v2/project`, { headers });
  expect(canonical.ok()).toBeTruthy();
  const project = await canonical.json() as { active_branch: string; branches: Array<{ name: string; status: string }>; parts: unknown[] };
  expect(project.active_branch).toBe(branchName);
  expect(project.branches.find((branch) => branch.name === branchName)?.status).toBe('working');
  expect(project.parts).toHaveLength(0);

  // The source branch remains intact, which is the actual safety value of the lineage UX.
  const main = await request.post(`${engineUrl}/v2/branches/main/activate`, { headers });
  expect(main.ok()).toBeTruthy();
  expect(((await main.json()) as { parts: unknown[] }).parts).toHaveLength(1);
});
