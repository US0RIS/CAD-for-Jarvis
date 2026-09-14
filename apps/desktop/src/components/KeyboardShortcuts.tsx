import { useEffect, useMemo, useState } from 'react';
import { Keyboard, X } from 'lucide-react';
import { executeOperation, fetchProject } from '../api/engine';

type Shortcut = { keys: string; action: string; group: 'Editing' | 'Viewport' | 'Navigation' | 'Project' };

const shortcuts: Shortcut[] = [
  { keys: 'Backspace / Delete', action: 'Delete selected object', group: 'Editing' },
  { keys: 'Esc', action: 'Deselect object / close shortcuts', group: 'Editing' },
  { keys: 'Ctrl/Cmd + Z', action: 'Undo', group: 'Editing' },
  { keys: 'Ctrl/Cmd + Shift + Z', action: 'Redo', group: 'Editing' },
  { keys: 'Ctrl/Cmd + Y', action: 'Redo', group: 'Editing' },
  { keys: 'G', action: 'Move tool', group: 'Viewport' },
  { keys: 'R', action: 'Rotate tool', group: 'Viewport' },
  { keys: 'S', action: 'Scale tool', group: 'Viewport' },
  { keys: 'F', action: 'Fit all geometry', group: 'Viewport' },
  { keys: '1', action: 'Front view', group: 'Viewport' },
  { keys: '2', action: 'Right view', group: 'Viewport' },
  { keys: '3', action: 'Top view', group: 'Viewport' },
  { keys: '4', action: 'Isometric view', group: 'Viewport' },
  { keys: '/', action: 'Isolate selected object', group: 'Viewport' },
  { keys: 'H', action: 'Hide selected object', group: 'Viewport' },
  { keys: 'Shift + H', action: 'Show all objects', group: 'Viewport' },
  { keys: 'O', action: 'Toggle auto-rotate', group: 'Viewport' },
  { keys: 'E', action: 'Toggle exploded view', group: 'Viewport' },
  { keys: 'Shift + E', action: 'Collapse exploded view', group: 'Viewport' },
  { keys: 'Ctrl/Cmd + 1', action: 'Properties panel', group: 'Navigation' },
  { keys: 'Ctrl/Cmd + 2', action: 'Components panel', group: 'Navigation' },
  { keys: 'Ctrl/Cmd + 3', action: 'Analyze panel', group: 'Navigation' },
  { keys: 'Ctrl/Cmd + 4', action: 'Manufacture panel', group: 'Navigation' },
  { keys: 'Alt + 1', action: 'History dock', group: 'Navigation' },
  { keys: 'Alt + 2', action: 'Code dock', group: 'Navigation' },
  { keys: 'Alt + 3', action: 'Simulation dock', group: 'Navigation' },
  { keys: 'Alt + 4', action: 'System / world dock', group: 'Navigation' },
  { keys: 'Ctrl/Cmd + K', action: 'Open Components and focus search', group: 'Navigation' },
  { keys: 'Ctrl/Cmd + J', action: 'Open Copilot and focus prompt', group: 'Navigation' },
  { keys: 'Ctrl/Cmd + N', action: 'New design', group: 'Project' },
  { keys: 'Ctrl/Cmd + O', action: 'Open .focad design', group: 'Project' },
  { keys: 'Ctrl/Cmd + S', action: 'Export .focad design', group: 'Project' },
  { keys: 'Ctrl/Cmd + Shift + O', action: 'Import STEP', group: 'Project' },
  { keys: 'Alt + D', action: 'Run Dynamics', group: 'Project' },
  { keys: '? / F1', action: 'Show keyboard shortcuts', group: 'Project' },
];

function editableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return true;
  return Boolean(target.closest('.monaco-editor,[contenteditable="true"]'));
}

function buttons(selector = 'button'): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>(selector));
}

function clickButtonByTitle(title: string): boolean {
  const button = buttons().find((candidate) => candidate.title === title && !candidate.disabled);
  if (!button) return false;
  button.click();
  return true;
}

function clickButtonByText(text: string, selector = 'button'): boolean {
  const button = buttons(selector).find((candidate) => candidate.textContent?.trim() === text && !candidate.disabled);
  if (!button) return false;
  button.click();
  return true;
}

function clickTestId(testId: string): boolean {
  const button = document.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`);
  if (!button || button.disabled) return false;
  button.click();
  return true;
}

function setExplode(value: number) {
  const slider = document.querySelector<HTMLInputElement>('[data-testid="explode-slider"]');
  if (!slider || slider.classList.contains('hidden-slider')) return;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  setter?.call(slider, String(value));
  slider.dispatchEvent(new Event('change', { bubbles: true }));
}

function currentExplode(): number {
  const slider = document.querySelector<HTMLInputElement>('[data-testid="explode-slider"]');
  return slider ? Number(slider.value || 0) : 0;
}

async function deleteSelectedObject() {
  const selectedRow = document.querySelector<HTMLElement>('.object-row.selected');
  if (!selectedRow) return false;

  const rows = Array.from(document.querySelectorAll<HTMLElement>('.object-row'));
  const selectedIndex = rows.indexOf(selectedRow);
  if (selectedIndex < 0) return false;

  const project = await fetchProject();
  const selected = project.parts[selectedIndex];
  if (!selected) return false;

  // Clear renderer selection first so no stale object id survives the mutation.
  document.querySelector<HTMLButtonElement>('.selection-chip button')?.click();
  await executeOperation('delete', { id: selected.id }, 'Delete selected object with keyboard');
  return true;
}

export function KeyboardShortcuts() {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const groups = useMemo(() => ['Editing', 'Viewport', 'Navigation', 'Project'] as const, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 1800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    const settings = document.querySelector<HTMLButtonElement>('button[title="Settings"]');
    const openSettings = () => setOpen(true);
    settings?.addEventListener('click', openSettings);
    return () => settings?.removeEventListener('click', openSettings);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key;
      const lower = key.toLowerCase();
      const mod = event.metaKey || event.ctrlKey;

      if (key === 'Escape') {
        if (open) {
          event.preventDefault();
          setOpen(false);
          return;
        }
        const clear = document.querySelector<HTMLButtonElement>('.selection-chip button');
        if (clear) {
          event.preventDefault();
          clear.click();
        }
        return;
      }

      if (editableTarget(event.target)) return;

      if (key === 'F1' || (key === '?' && event.shiftKey)) {
        event.preventDefault();
        setOpen(true);
        return;
      }

      if ((key === 'Backspace' || key === 'Delete') && !mod && !event.altKey) {
        event.preventDefault();
        void deleteSelectedObject()
          .then((deleted) => setNotice(deleted ? 'Object deleted · Ctrl/Cmd+Z to undo' : 'Select an object to delete'))
          .catch((error) => setNotice(error instanceof Error ? error.message : String(error)));
        return;
      }

      if (mod && lower === 'z') {
        event.preventDefault();
        clickButtonByTitle(event.shiftKey ? 'Redo' : 'Undo');
        return;
      }
      if (mod && lower === 'y') {
        event.preventDefault();
        clickButtonByTitle('Redo');
        return;
      }
      if (mod && lower === 'n') {
        event.preventDefault();
        clickButtonByText('New');
        return;
      }
      if (mod && lower === 'o' && event.shiftKey) {
        event.preventDefault();
        clickButtonByText('Import STEP');
        return;
      }
      if (mod && lower === 'o') {
        event.preventDefault();
        clickTestId('open-focad');
        return;
      }
      if (mod && lower === 's') {
        event.preventDefault();
        clickTestId('export-focad');
        return;
      }
      if (mod && lower === 'k') {
        event.preventDefault();
        clickButtonByText('Components', '.right-tabs button');
        window.setTimeout(() => document.querySelector<HTMLInputElement>('.search-control input')?.focus(), 0);
        return;
      }
      if (mod && lower === 'j') {
        event.preventDefault();
        clickButtonByText('Copilot', '.panel-tabs.compact button');
        window.setTimeout(() => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Copilot request"]')?.focus(), 0);
        return;
      }
      if (mod && ['1', '2', '3', '4'].includes(key)) {
        event.preventDefault();
        const tabs = ['Properties', 'Components', 'Analyze', 'Manufacture'] as const;
        const tab = tabs[Number(key) - 1];
        if (tab) clickButtonByText(tab, '.right-tabs button');
        return;
      }
      if (event.altKey && ['1', '2', '3', '4'].includes(key)) {
        event.preventDefault();
        const dockTabs = ['tab-history', 'tab-code', 'tab-simulations', 'tab-system'] as const;
        const dockTab = dockTabs[Number(key) - 1];
        if (dockTab) clickTestId(dockTab);
        return;
      }
      if (event.altKey && lower === 'd') {
        event.preventDefault();
        clickButtonByText('Dynamics');
        return;
      }

      if (mod || event.altKey) return;

      const simple: Record<string, () => void> = {
        g: () => { clickButtonByTitle('Move'); },
        r: () => { clickButtonByTitle('Rotate'); },
        s: () => { clickButtonByTitle('Scale'); },
        f: () => { clickButtonByTitle('Fit'); },
        '1': () => { clickButtonByTitle('Front'); },
        '2': () => { clickButtonByTitle('Right'); },
        '3': () => { clickButtonByTitle('Top'); },
        '4': () => { clickButtonByTitle('Isometric'); },
        '/': () => { clickButtonByTitle('Isolate'); },
        o: () => { clickButtonByTitle('Auto rotate'); },
      };

      if (lower === 'h') {
        event.preventDefault();
        clickButtonByTitle(event.shiftKey ? 'Show all' : 'Hide');
        return;
      }
      if (lower === 'e') {
        event.preventDefault();
        setExplode(event.shiftKey ? 0 : currentExplode() > 0 ? 0 : 65);
        return;
      }
      const command = simple[lower];
      if (command) {
        event.preventDefault();
        command();
      }
    };

    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open]);

  return <>
    {notice && <div className="shortcut-toast" role="status">{notice}</div>}
    {open && <div className="shortcut-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="shortcut-dialog" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" data-testid="keyboard-shortcuts-dialog">
        <header><div><Keyboard size={17}/><span><strong>Keyboard shortcuts</strong><small>ForgeCAD is designed to stay under your hands.</small></span></div><button onClick={() => setOpen(false)} aria-label="Close keyboard shortcuts"><X size={15}/></button></header>
        <div className="shortcut-grid">
          {groups.map((group) => <div className="shortcut-group" key={group}><h3>{group}</h3>{shortcuts.filter((shortcut) => shortcut.group === group).map((shortcut) => <div className="shortcut-row" key={`${group}-${shortcut.keys}`}><span>{shortcut.action}</span><kbd>{shortcut.keys}</kbd></div>)}</div>)}
        </div>
        <footer>Shortcuts are disabled while typing in text fields, search boxes, selects, or Monaco code editors.</footer>
      </section>
    </div>}
  </>;
}
