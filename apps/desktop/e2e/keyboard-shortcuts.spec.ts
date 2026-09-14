import { expect, test } from '@playwright/test';

test('ForgeCAD keyboard workflow supports deletion, undo, tools, panels, and typing guards', async ({ page, request }) => {
  const headers = { 'X-ForgeCAD-Session': 'test-session', 'Content-Type': 'application/json' };

  const reset = await request.post('http://127.0.0.1:8765/v2/operations', {
    headers,
    data: { op: 'new_project', args: {}, reason: 'Reset shortcut acceptance workspace' },
  });
  expect(reset.ok()).toBeTruthy();

  const added = await request.post('http://127.0.0.1:8765/v2/components/compute.raspberry_pi_5_8gb/add', { headers });
  expect(added.ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('scene-health')).toHaveText('3D READY', { timeout: 90_000 });

  const object = page.locator('.object-row').first();
  await object.click();
  await expect(object).toHaveClass(/selected/);

  // Deletion is the primary requested interaction: select an object and press Backspace.
  await page.keyboard.press('Backspace');
  await expect(page.getByText('0 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.object-row')).toHaveCount(0);
  await expect(page.getByText(/Object deleted/)).toBeVisible();

  // Normal CAD undo restores the exact deletion.
  await page.keyboard.press('Control+z');
  await expect(page.getByText('1 objects').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.object-row')).toHaveCount(1);

  // Tool shortcuts operate without requiring toolbar clicks.
  await page.keyboard.press('r');
  await expect(page.getByRole('button', { name: 'Rotate' })).toHaveClass(/active/);
  await page.keyboard.press('s');
  await expect(page.getByRole('button', { name: 'Scale' })).toHaveClass(/active/);
  await page.keyboard.press('g');
  await expect(page.getByRole('button', { name: 'Move' })).toHaveClass(/active/);

  // Right-panel and bottom-dock shortcuts are direct and discoverable.
  await page.keyboard.press('Control+2');
  await expect(page.locator('.right-tabs button').filter({ hasText: 'Components' })).toHaveClass(/active/);
  await page.keyboard.press('Control+3');
  await expect(page.locator('.right-tabs button').filter({ hasText: 'Analyze' })).toHaveClass(/active/);
  await page.keyboard.press('Alt+1');
  await expect(page.getByTestId('tab-history')).toHaveClass(/active/);

  // Ctrl+K goes straight to component search; typing there must never fire CAD shortcuts.
  await page.keyboard.press('Control+k');
  const search = page.locator('.search-control input');
  await expect(search).toBeFocused();
  await search.fill('sensor');
  await page.keyboard.press('Backspace');
  await expect(search).toHaveValue('senso');
  await expect(page.locator('.object-row')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Move' })).toHaveClass(/active/);

  // Ctrl+J opens Copilot and places the caret in its prompt.
  await search.blur();
  await page.keyboard.press('Control+j');
  await expect(page.getByRole('button', { name: 'Copilot' })).toHaveClass(/active/);
  await expect(page.getByRole('textbox', { name: 'Copilot request' })).toBeFocused();

  // F1 exposes the complete shortcut reference and Escape closes it.
  await page.getByRole('textbox', { name: 'Copilot request' }).blur();
  await page.keyboard.press('F1');
  await expect(page.getByTestId('keyboard-shortcuts-dialog')).toBeVisible();
  await expect(page.getByText('Delete selected object')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('keyboard-shortcuts-dialog')).toHaveCount(0);
});
