import { expect, test, type APIRequestContext } from '@playwright/test';

const engineUrl = 'http://127.0.0.1:8765';
const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

async function resetWithPi(request: APIRequestContext) {
  const reset = await request.post(`${engineUrl}/v2/operations`, {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset UX regression workspace' },
  });
  expect(reset.ok()).toBeTruthy();
  const added = await request.post(`${engineUrl}/v2/components/compute.raspberry_pi_5_8gb/add`, { headers });
  expect(added.ok()).toBeTruthy();
}

test('delete is optimistic, ID-based, and does not fetch the project just to resolve selection', async ({ page, request }) => {
  await resetWithPi(request);

  let projectReads = 0;
  let releaseDelete: (() => void) | null = null;
  const deleteGate = new Promise<void>((resolve) => { releaseDelete = resolve; });

  page.on('request', (networkRequest) => {
    if (networkRequest.method() === 'GET' && networkRequest.url().includes('/v2/project')) projectReads += 1;
  });
  await page.route('**/v2/operations', async (route) => {
    const body = route.request().postDataJSON() as { op?: string } | null;
    if (body?.op === 'delete') {
      await deleteGate;
      await route.continue();
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });
  const readsAfterStartup = projectReads;

  await page.locator('.object-row').first().click();
  await page.keyboard.press('Backspace');

  // The renderer must remove the object before the deliberately blocked backend request returns.
  await expect(page.locator('.object-row')).toHaveCount(0, { timeout: 750 });
  await expect(page.getByText('0 objects').first()).toBeVisible({ timeout: 750 });
  expect(projectReads).toBe(readsAfterStartup);

  releaseDelete?.();
  await expect(page.getByText(/Object deleted/)).toBeVisible({ timeout: 15_000 });

  const canonical = await request.get(`${engineUrl}/v2/project`, { headers });
  expect(canonical.ok()).toBeTruthy();
  expect((await canonical.json()).parts).toHaveLength(0);

  await page.keyboard.press('Control+z');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 15_000 });
});

test('Copilot uses normal chat keys: Shift+Enter makes a newline and Enter sends', async ({ page, request }) => {
  await resetWithPi(request);

  let submittedJobs = 0;
  await page.route('**/v2/runtime', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ engine: 'ready', scene: 'ready', ollama: 'ready', configured_model: 'ux-test-model', resolved_model: 'ux-test-model', api_version: '2' }),
    });
  });
  await page.route('**/v2/jobs', async (route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    submittedJobs += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: `ux-job-${submittedJobs}`,
        kind: 'agent',
        state: 'queued',
        created_at: new Date().toISOString(),
        progress: 0,
        message: 'Queued from UX regression',
        branch: 'main',
        selected_object_id: null,
        assistant_text: '',
        result: {},
        error: null,
      }),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Copilot', exact: true }).click();
  const prompt = page.getByRole('textbox', { name: 'Copilot request' });
  await prompt.fill('line one');
  await prompt.press('Shift+Enter');
  await prompt.type('line two');
  await expect(prompt).toHaveValue('line one\nline two');
  expect(submittedJobs).toBe(0);

  await prompt.press('Enter');
  await expect(page.locator('.message.user')).toContainText('line one');
  await expect(page.locator('.message.user')).toContainText('line two');
  await expect(prompt).toHaveValue('');
  expect(submittedJobs).toBe(1);
});

test('Copilot preserves the draft and explains the problem when the local model is unavailable', async ({ page, request }) => {
  await resetWithPi(request);
  let submittedJobs = 0;
  await page.route('**/v2/runtime', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ engine: 'ready', scene: 'ready', ollama: 'offline', configured_model: 'qwen3:8b', resolved_model: null, api_version: '2' }),
    });
  });
  page.on('request', (networkRequest) => {
    if (networkRequest.method() === 'POST' && networkRequest.url().endsWith('/v2/jobs')) submittedJobs += 1;
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Copilot', exact: true }).click();
  const prompt = page.getByRole('textbox', { name: 'Copilot request' });
  await prompt.fill('keep this exact draft');
  await prompt.press('Enter');

  await expect(prompt).toHaveValue('keep this exact draft');
  await expect(page.getByText(/Local AI is unavailable/).first()).toBeVisible();
  expect(submittedJobs).toBe(0);
});

test('an engineering job cannot overwrite a running Copilot job in the UI', async ({ page, request }) => {
  await resetWithPi(request);
  let submittedJobs = 0;

  await page.route('**/v2/runtime', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ engine: 'ready', scene: 'ready', ollama: 'ready', configured_model: 'ux-test-model', resolved_model: 'ux-test-model', api_version: '2' }),
    });
  });
  await page.route('**/v2/jobs', async (route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const input = route.request().postDataJSON() as { kind?: string };
    submittedJobs += 1;
    const kind = input.kind ?? 'simulation';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: `ux-${kind}-${submittedJobs}`,
        kind,
        state: 'queued',
        created_at: new Date(Date.now() + submittedJobs).toISOString(),
        progress: 0,
        message: `${kind} queued independently`,
        branch: 'main',
        selected_object_id: null,
        assistant_text: '',
        result: {},
        error: null,
      }),
    });
  });

  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });
  await page.getByRole('button', { name: 'Copilot', exact: true }).click();
  const prompt = page.getByRole('textbox', { name: 'Copilot request' });
  await prompt.fill('keep the agent busy');
  await prompt.press('Enter');
  await expect(page.getByTestId('agent-status')).toContainText('Request queued');
  await expect(page.getByTestId('send-button')).toBeDisabled();

  await page.getByRole('button', { name: 'Dynamics', exact: true }).click();
  await expect(page.getByTestId('simulation-job-status')).toContainText('Dynamics simulation');
  await expect(page.getByTestId('simulation-job-status')).toContainText('Queued');
  expect(submittedJobs).toBe(2);

  await page.getByRole('button', { name: 'Copilot', exact: true }).click();
  await expect(page.getByTestId('agent-status')).toContainText('Request queued');
  await expect(page.getByTestId('send-button')).toBeDisabled();
});

test('a branch switch waits for the in-flight code save and preserves the edited branch', async ({ page, request }) => {
  test.setTimeout(120_000);
  await resetWithPi(request);

  const initial = await request.get(`${engineUrl}/v2/project`, { headers });
  expect(initial.ok()).toBeTruthy();
  const initialProject = await initial.json() as { parts: Array<{ id: string }> };
  const workspaceId = initialProject.parts[0]?.id;
  expect(workspaceId).toBeTruthy();

  const branch = await request.post(`${engineUrl}/v2/branches`, {
    headers,
    data: { name: 'guard-sibling', reason: 'UX regression sibling before editor change' },
  });
  expect(branch.ok()).toBeTruthy();
  const main = await request.post(`${engineUrl}/v2/branches/main/activate`, { headers });
  expect(main.ok()).toBeTruthy();

  let releaseSave: (() => void) | null = null;
  let markSaveStarted: (() => void) | null = null;
  const saveGate = new Promise<void>((resolve) => { releaseSave = resolve; });
  const saveStarted = new Promise<void>((resolve) => { markSaveStarted = resolve; });
  let codeWrites = 0;
  let siblingActivations = 0;

  await page.route('**/v2/code/workspaces/**', async (route) => {
    if (route.request().method() !== 'PUT') { await route.continue(); return; }
    codeWrites += 1;
    markSaveStarted?.();
    await saveGate;
    await route.continue();
  });
  page.on('request', (networkRequest) => {
    if (networkRequest.method() === 'POST' && networkRequest.url().includes('/v2/branches/guard-sibling/activate')) siblingActivations += 1;
  });

  await page.goto('/');
  await expect(page.locator('.object-row')).toHaveCount(1, { timeout: 30_000 });
  await page.locator('.object-row').first().click();
  await page.getByTestId('tab-code').click();
  await expect(page.getByTestId('code-workspace')).toBeVisible();
  const mainFile = page.locator('.tree-file').filter({ hasText: 'main.py' });
  await expect(mainFile).toBeVisible({ timeout: 30_000 });
  await mainFile.click();
  await expect(page.locator('.editor-toolbar')).toContainText('main.py');

  const editorInput = page.locator('.monaco-editor textarea.inputarea').first();
  await editorInput.waitFor({ state: 'attached', timeout: 30_000 });
  await editorInput.focus();
  await page.keyboard.press('Control+End');
  const marker = `# guard-regression-${Date.now()}`;
  await page.keyboard.insertText(`\n${marker}`);
  await expect(page.locator('.editor-toolbar')).toContainText('Unsaved');

  // Let autosave begin, but hold its response open. The canonical branch switch must
  // not be sent until this exact editor write has finished.
  await saveStarted;
  await page.locator('.branch-picker select').selectOption('guard-sibling');
  await page.waitForTimeout(150);
  expect(siblingActivations).toBe(0);
  expect(codeWrites).toBe(1);

  releaseSave?.();
  await expect(page.locator('.doc-tab small')).toHaveText('guard-sibling', { timeout: 15_000 });
  expect(siblingActivations).toBe(1);
  expect(codeWrites).toBe(1);

  await page.locator('.branch-picker select').selectOption('main');
  await expect(page.locator('.doc-tab small')).toHaveText('main', { timeout: 15_000 });
  const saved = await request.get(`${engineUrl}/v2/code/workspaces/${encodeURIComponent(String(workspaceId))}/files/main.py`, { headers });
  expect(saved.ok()).toBeTruthy();
  const savedFile = await saved.json() as { content: string };
  expect(savedFile.content).toContain(marker);
});
