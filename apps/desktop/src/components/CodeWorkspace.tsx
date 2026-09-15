import { useEffect, useRef, useState } from 'react';
import { MessageSquareText, Save } from 'lucide-react';
import { fetchCodeFile, fetchWorkspace, saveCodeFile, type WorkspacePayload } from '../api/engine';

interface CodeWorkspaceProps {
  workspaceId: string;
  onAskCopilot?: (workspaceId: string, path: string) => void;
}

export function CodeWorkspace({ workspaceId, onAskCopilot }: CodeWorkspaceProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<import('monaco-editor').editor.IStandaloneCodeEditor | null>(null);
  const savedContentRef = useRef('');
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null);
  const [activePath, setActivePath] = useState('src/main.py');
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
      if (!value.files.includes(activePath) && value.files[0]) setActivePath(value.files[0]);
      setStatus(`Connected · ${value.target} · ${value.runtime}`);
    }).catch((error) => {
      if (active) setStatus(error instanceof Error ? error.message : String(error));
    });
    return () => { active = false; };
  }, [workspaceId]);

  async function persist(path: string, content: string): Promise<boolean> {
    setSaving(true);
    try {
      await saveCodeFile(workspaceId, path, content);
      savedContentRef.current = content;
      setDirty(false);
      setStatus(`Saved ${path} to design history`);
      return true;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    let disposed = false;
    let editor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null;
    let changeDisposable: { dispose(): void } | null = null;
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
        setDirty(editor?.getValue() !== savedContentRef.current);
      });
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        const content = editor?.getValue();
        if (content != null) void persist(activePath, content);
      });
    }).catch((error) => setStatus(error instanceof Error ? error.message : String(error)));
    return () => {
      disposed = true;
      changeDisposable?.dispose();
      editor?.dispose();
      if (editorRef.current === editor) editorRef.current = null;
    };
  }, [workspaceId, activePath]);

  async function save(): Promise<boolean> {
    const content = editorRef.current?.getValue();
    if (content == null) return true;
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
          <span>{activePath}{dirty ? ' · Unsaved' : ''}</span>
          <span className="editor-actions">
            <button className="editor-action primary" onClick={() => void save()} disabled={saving || !dirty}><Save size={13}/>{saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}</button>
            {onAskCopilot && <button className="editor-action" onClick={() => onAskCopilot(workspaceId, activePath)}><MessageSquareText size={13}/>Ask Copilot</button>}
          </span>
        </header>
        <div ref={hostRef} className="monaco-host" data-testid="monaco-host"/>
      </section>
      <aside className="run-output">
        <div className="run-title">Workspace status</div>
        <div>[+] {status}</div>
        <div>[+] Workspace files are versioned with the active design branch.</div>
        <div>[+] Execution controls appear only when a real device/runtime adapter is available.</div>
      </aside>
    </div>
  );
}
