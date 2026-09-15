import { useEffect, useRef, useState } from 'react';
import { MessageSquareText, Save } from 'lucide-react';
import {
  fetchCodeFile,
  fetchWorkspace,
  registerProjectMutationGuard,
  saveCodeFile,
  type WorkspacePayload,
} from '../api/engine';

interface CodeWorkspaceProps {
  workspaceId: string;
  onAskCopilot?: (workspaceId: string, path: string) => void;
}

const AUTOSAVE_DELAY_MS = 700;

export function CodeWorkspace({ workspaceId, onAskCopilot }: CodeWorkspaceProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<import('monaco-editor').editor.IStandaloneCodeEditor | null>(null);
  const savedContentRef = useRef('');
  const saveSerialRef = useRef(0);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const lastQueuedRef = useRef<{ workspaceId: string; path: string; content: string } | null>(null);
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null);
  const [activePath, setActivePath] = useState('');
  const [status, setStatus] = useState('Connecting to device workspace…');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    let active = true;
    setWorkspace(null);
    setStatus('Connecting to device workspace…');
    void fetchWorkspace(workspaceId).then((value) => {
      if (!active) return;
      setWorkspace(value);
      setActivePath((current) => value.files.includes(current) ? current : value.files[0] ?? '');
      setStatus(`Connected · ${value.target} · ${value.runtime}`);
    }).catch((error) => {
      if (active) setStatus(error instanceof Error ? error.message : String(error));
    });
    return () => { active = false; };
  }, [workspaceId]);

  function enqueueSave(path: string, content: string): Promise<void> {
    const predecessor = saveQueueRef.current.catch(() => undefined);
    const task = predecessor.then(async () => {
      await saveCodeFile(workspaceId, path, content);
    });
    saveQueueRef.current = task;
    lastQueuedRef.current = { workspaceId, path, content };
    void task.finally(() => {
      const latest = lastQueuedRef.current;
      if (latest?.workspaceId === workspaceId && latest.path === path && latest.content === content) lastQueuedRef.current = null;
    }).catch(() => undefined);
    return task;
  }

  async function persist(path: string, content: string): Promise<boolean> {
    const serial = ++saveSerialRef.current;
    setSaving(true);
    try {
      await enqueueSave(path, content);
      if (serial !== saveSerialRef.current) return true;
      savedContentRef.current = content;
      const latest = editorRef.current?.getValue();
      setDirty(latest != null && latest !== content);
      setStatus(`Saved ${path} to design history`);
      return true;
    } catch (error) {
      if (serial === saveSerialRef.current) setStatus(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      if (serial === saveSerialRef.current) setSaving(false);
    }
  }

  useEffect(() => {
    if (!activePath) return;
    return registerProjectMutationGuard(async () => {
      const current = editorRef.current?.getValue();
      if (current != null && current !== savedContentRef.current) {
        const ok = await persist(activePath, current);
        if (!ok) throw new Error(`Could not save ${activePath} before changing project state.`);
        return;
      }
      await saveQueueRef.current;
    });
  }, [workspaceId, activePath]);

  useEffect(() => {
    if (!activePath || workspace?.id !== workspaceId) return;
    let disposed = false;
    let editor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null;
    let changeDisposable: { dispose(): void } | null = null;
    let autosaveTimer: number | null = null;

    const clearAutosave = () => {
      if (autosaveTimer != null) window.clearTimeout(autosaveTimer);
      autosaveTimer = null;
    };

    void Promise.all([import('monaco-editor'), fetchCodeFile(workspaceId, activePath)]).then(([monaco, file]) => {
      if (disposed || !hostRef.current) return;
      editorRef.current?.dispose();
      savedContentRef.current = file.content;
      setDirty(false);
      editor = monaco.editor.create(hostRef.current, {
        value: file.content,
        language: activePath.endsWith('.json') ? 'json' : activePath.endsWith('.md') ? 'markdown' : 'python',
        theme: 'vs-dark',
        automaticLayout: true,
        minimap: { enabled: false },
        fontSize: 13,
        lineHeight: 20,
        padding: { top: 12 },
        smoothScrolling: true,
        scrollBeyondLastLine: false,
        renderLineHighlight: 'line',
      });
      editorRef.current = editor;
      changeDisposable = editor.onDidChangeModelContent(() => {
        const content = editor?.getValue() ?? '';
        const changed = content !== savedContentRef.current;
        setDirty(changed);
        clearAutosave();
        if (changed) {
          autosaveTimer = window.setTimeout(() => {
            autosaveTimer = null;
            const current = editor?.getValue();
            if (current != null && current !== savedContentRef.current) void persist(activePath, current);
          }, AUTOSAVE_DELAY_MS);
        }
      });
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        clearAutosave();
        const content = editor?.getValue();
        if (content != null) void persist(activePath, content);
      });
    }).catch((error) => setStatus(error instanceof Error ? error.message : String(error)));
    return () => {
      disposed = true;
      clearAutosave();
      const content = editor?.getValue();
      const queued = lastQueuedRef.current;
      const sameAlreadyQueued = queued?.workspaceId === workspaceId && queued.path === activePath && queued.content === content;
      if (content != null && content !== savedContentRef.current && !sameAlreadyQueued) void enqueueSave(activePath, content).catch(() => undefined);
      changeDisposable?.dispose();
      editor?.dispose();
      if (editorRef.current === editor) editorRef.current = null;
    };
  }, [workspaceId, activePath, workspace?.id]);

  async function save(): Promise<boolean> {
    const content = editorRef.current?.getValue();
    if (content == null || !activePath) return true;
    return persist(activePath, content);
  }

  async function selectFile(path: string) {
    if (path === activePath) return;
    if (dirty && !(await save())) return;
    setActivePath(path);
  }

  return (
    <div className="code-panel" data-testid="code-workspace">
      <aside className="file-tree">
        <div className="workspace-title"><span className="live-dot"/> {workspace?.target ?? 'Programmable component'}</div>
        <div className="tree-caption">{workspace?.runtime ?? 'Loading runtime…'}</div>
        {(workspace?.files ?? []).map((path) => (
          <button key={path} className={`tree-file ${activePath === path ? 'active' : ''}`} onClick={() => void selectFile(path)}>{path}</button>
        ))}
      </aside>
      <section className="editor-area">
        <header className="editor-toolbar">
          <span>{activePath || 'No file selected'}{dirty ? ' · Unsaved' : ''}</span>
          <span className="editor-actions">
            <button className="editor-action primary" onClick={() => void save()} disabled={saving || !dirty || !activePath}><Save size={13}/>{saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}</button>
            {onAskCopilot && activePath && <button className="editor-action" onClick={() => onAskCopilot(workspaceId, activePath)}><MessageSquareText size={13}/>Ask Copilot</button>}
          </span>
        </header>
        <div ref={hostRef} className="monaco-host" data-testid="monaco-host"/>
      </section>
      <aside className="run-output">
        <div className="run-title">Workspace status</div>
        <div>[+] {status}</div>
        <div>[+] Changes autosave after {AUTOSAVE_DELAY_MS} ms of idle time and are serialized into active-branch design history.</div>
        <div>[+] Project/branch replacement waits for pending editor saves before changing canonical state.</div>
        <div>[+] Execution controls appear only when a real device/runtime adapter is available.</div>
      </aside>
    </div>
  );
}