import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Play, Save } from 'lucide-react';
import { fetchCodeFile, fetchWorkspace, saveCodeFile, type WorkspacePayload } from '../api/engine';

interface CodeWorkspaceProps {
  workspaceId: string;
}

export function CodeWorkspace({ workspaceId }: CodeWorkspaceProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<import('monaco-editor').editor.IStandaloneCodeEditor | null>(null);
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null);
  const [activePath, setActivePath] = useState('src/main.py');
  const [status, setStatus] = useState('Connecting to device workspace…');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void fetchWorkspace(workspaceId).then((value) => {
      setWorkspace(value);
      if (!value.files.includes(activePath) && value.files[0]) setActivePath(value.files[0]);
      setStatus(`Connected · ${value.target} · ${value.runtime}`);
    }).catch((error) => setStatus(error instanceof Error ? error.message : String(error)));
  }, [workspaceId]);

  useEffect(() => {
    let disposed = false;
    let editor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null;
    void Promise.all([import('monaco-editor'), fetchCodeFile(workspaceId, activePath)]).then(([monaco, file]) => {
      if (disposed || !hostRef.current) return;
      editorRef.current?.dispose();
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
    }).catch((error) => setStatus(error instanceof Error ? error.message : String(error)));
    return () => {
      disposed = true;
      editor?.dispose();
      if (editorRef.current === editor) editorRef.current = null;
    };
  }, [workspaceId, activePath]);

  async function save() {
    const content = editorRef.current?.getValue();
    if (content == null) return;
    setSaving(true);
    try {
      await saveCodeFile(workspaceId, activePath, content);
      setStatus(`Saved ${activePath} to design history`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="code-panel" data-testid="code-workspace">
      <aside className="file-tree">
        <div className="workspace-title"><span className="live-dot"/> {workspace?.target ?? 'Programmable component'}</div>
        <div className="tree-caption">{workspace?.runtime ?? 'Loading runtime…'}</div>
        {(workspace?.files ?? []).map((path) => (
          <button key={path} className={`tree-file ${activePath === path ? 'active' : ''}`} onClick={() => setActivePath(path)}>{path}</button>
        ))}
      </aside>
      <section className="editor-area">
        <header className="editor-toolbar">
          <span>{activePath}</span>
          <span className="editor-actions">
            <button className="editor-action primary" onClick={() => void save()} disabled={saving}><Save size={13}/>{saving ? 'Saving…' : 'Save'}</button>
            <button className="editor-action"><CheckCircle2 size={13}/>Check</button>
            <button className="editor-action">Ask Qwen</button>
            <button className="editor-action">Branch Code</button>
          </span>
        </header>
        <div ref={hostRef} className="monaco-host" data-testid="monaco-host"/>
      </section>
      <aside className="run-output">
        <div className="run-title">Run / Output</div>
        <div>[+] {status}</div>
        <div>[+] Workspace is versioned with the active design branch.</div>
        <button><Play size={12}/>Run</button>
      </aside>
    </div>
  );
}
