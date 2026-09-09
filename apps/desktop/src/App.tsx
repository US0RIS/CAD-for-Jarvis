import { useEffect, useMemo, useState } from 'react';
import {
  Activity, BookOpen, Bot, Check, ChevronDown, Code2, FolderOpen, GitBranch, History, Play,
  Search, Send, Settings, ShieldCheck, Undo2, Redo2, X, CircleAlert,
} from 'lucide-react';
import {
  createJob, fetchComponents, fetchProject, fetchRuntime, subscribeEngineEvents,
  type ComponentPayload, type JobPayload, type ProjectPayload, type RuntimePayload,
} from './api/engine';
import { CodeWorkspace } from './components/CodeWorkspace';
import { Viewport } from './components/Viewport';

type RightTab = 'design' | 'components' | 'analysis';
type BottomTab = 'simulations' | 'notebook' | 'designs' | 'history' | 'code' | 'system';
type ChatEntry = { role: 'user' | 'agent'; text: string };

const bottomTabs: Array<{ id: BottomTab; label: string; icon: typeof Activity }> = [
  { id: 'simulations', label: 'SIMULATIONS', icon: Activity }, { id: 'notebook', label: 'NOTEBOOK', icon: BookOpen },
  { id: 'designs', label: 'DESIGNS', icon: GitBranch }, { id: 'history', label: 'HISTORY', icon: History },
  { id: 'code', label: 'CODE', icon: Code2 }, { id: 'system', label: 'SYSTEM', icon: Settings },
];

function BranchCard({ branch }: { branch: ProjectPayload['branches'][number] }) {
  const tone = branch.status === 'working' ? 'good' : branch.status === 'not_working' ? 'bad' : 'muted';
  return <button className={`branch-card ${tone} ${branch.active ? 'active-branch' : ''}`}>
    <span className="branch-title"><span className="status-dot"/>{branch.name}</span>
    <span className="branch-meta"><span>{branch.status.replace('_', ' ')}</span>{branch.protected ? <span className="protected"><ShieldCheck size={11}/>Protected</span> : <span>{branch.commit_count} commit{branch.commit_count === 1 ? '' : 's'}</span>}</span>
  </button>;
}

function ComponentCard({ item }: { item: ComponentPayload }) {
  return <article className="component-card" data-testid={`component-${item.id}`}>
    <div className="component-thumb photo">
      {item.image ? <img src={item.image.uri} alt={item.model} loading="lazy"/> : <div className="image-fallback">No image</div>}
    </div>
    <div className="component-copy">
      <div className="component-name-row"><strong>{item.model}</strong>{item.fit_score != null && <span className="match-score">{item.fit_score}% match</span>}</div>
      <div className="component-specs">{item.key_specs.map((s) => s.value).join('  ·  ')}</div>
      <div className="component-footer"><span>{item.price ? `${item.price.currency === 'USD' ? '$' : ''}${item.price.amount.toFixed(2)}` : 'Price unknown'}</span><span>·</span><span>{item.price?.supplier ?? item.manufacturer}</span><button className={item.added ? 'added-button' : 'add-button'}>{item.added ? <><Check size={12}/>Added</> : 'Add'}</button></div>
    </div>
  </article>;
}

function RuntimeBanner({ runtime, error }: { runtime: RuntimePayload | null; error: string | null }) {
  if (error) return <div className="runtime-banner error"><CircleAlert size={16}/><div><strong>Forge Engine needs attention</strong><span>{error}</span></div></div>;
  const ready = runtime?.engine === 'ready' && runtime?.ollama === 'ready';
  return <div className={`runtime-banner ${ready ? '' : 'warming'}`} data-testid="runtime-banner">
    {ready ? <Check size={15}/> : <span className="spinner"/>}
    <div><strong>{ready ? 'Local engineering copilot is online' : runtime?.ollama === 'failed' ? `${runtime.configured_model} is not installed` : runtime?.ollama === 'offline' ? 'Ollama is offline' : 'Starting local engineering copilot'}</strong><span>{ready ? 'All design data stays on your machine.' : `Configured model: ${runtime?.configured_model ?? 'qwen3:8b'}`}</span></div>
  </div>;
}

function BottomContent({ tab, project, workspaceId }: { tab: BottomTab; project: ProjectPayload | null; workspaceId: string | null }) {
  if (tab === 'code' && workspaceId) return <CodeWorkspace workspaceId={workspaceId}/>;
  if (tab === 'history') return <div className="history-panel">{project?.history.slice().reverse().map((item, i) => <div className="history-row" key={`${item.time}-${i}`}><span>{item.branch}</span><strong>{item.message}</strong><small>{item.actor}</small></div>)}</div>;
  if (tab === 'designs') return <div className="dock-placeholder"><strong>DESIGN BRANCHES</strong><span>{project?.branches.length ?? 0} branches · active {project?.active_branch ?? '—'}</span></div>;
  return <div className="dock-placeholder"><strong>{tab.toUpperCase()}</strong><span>This panel is part of the v2 contract; the vertical slice keeps it live without blocking the workspace.</span></div>;
}

export default function App() {
  const [rightTab, setRightTab] = useState<RightTab>('components');
  const [bottomTab, setBottomTab] = useState<BottomTab>('code');
  const [explode, setExplode] = useState(45);
  const [message, setMessage] = useState('');
  const [applyEdits, setApplyEdits] = useState(true);
  const [runtime, setRuntime] = useState<RuntimePayload | null>(null);
  const [project, setProject] = useState<ProjectPayload | null>(null);
  const [components, setComponents] = useState<ComponentPayload[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>('raspberry-pi');
  const [sceneReady, setSceneReady] = useState(false);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<JobPayload | null>(null);
  const [streamText, setStreamText] = useState('');
  const [chat, setChat] = useState<ChatEntry[]>([
    { role: 'user', text: 'Branch from the known-good design, swap in a 12V solenoid, and open the Raspberry Pi code workspace.' },
    { role: 'agent', text: 'The baseline stays protected. The vertical slice is ready to create a child branch, evaluate the 12V actuator choice, and keep the Raspberry Pi workspace versioned with it.' },
  ]);

  const selectedPart = useMemo(() => project?.parts.find((p) => p.id === selectedId) ?? null, [project, selectedId]);
  const workspaceId = selectedPart?.programmable_workspace_id ?? project?.parts.find((p) => p.programmable_workspace_id)?.programmable_workspace_id ?? null;

  async function refreshProject() {
    const [nextProject, nextComponents] = await Promise.all([fetchProject(), fetchComponents('')]);
    setProject(nextProject); setComponents(nextComponents.items);
  }

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [nextRuntime, nextProject, nextComponents] = await Promise.all([fetchRuntime(), fetchProject(), fetchComponents('')]);
        if (cancelled) return;
        setRuntime(nextRuntime); setProject(nextProject); setComponents(nextComponents.items); setStartupError(null);
      } catch (error) { if (!cancelled) setStartupError(error instanceof Error ? error.message : String(error)); }
    };
    void load();
    const timer = window.setInterval(() => void fetchRuntime().then(setRuntime).catch((error) => setStartupError(error instanceof Error ? error.message : String(error))), 2500);
    let stop: (() => void) | undefined;
    void subscribeEngineEvents((event) => {
      if (event.type === 'job.updated') {
        setActiveJob(event.job);
        if (event.job.state === 'completed') {
          const text = event.job.assistant_text.trim();
          if (text) setChat((items) => [...items, { role: 'agent', text }]);
          setStreamText('');
          void refreshProject();
        }
      } else if (event.type === 'job.token') setStreamText((value) => value + event.token);
      else if (event.type === 'project.updated') setProject(event.project);
    }).then((cleanup) => { stop = cleanup; }).catch(() => undefined);
    return () => { cancelled = true; window.clearInterval(timer); stop?.(); };
  }, []);

  async function send() {
    const text = message.trim();
    if (!text || (activeJob && !['completed', 'failed', 'cancelled'].includes(activeJob.state))) return;
    setChat((items) => [...items, { role: 'user', text }]); setMessage(''); setStreamText('');
    try {
      const job = await createJob({ kind: 'agent', text, branch: project?.active_branch, selected_object_id: selectedId, apply_edits: applyEdits });
      setActiveJob(job);
    } catch (error) {
      setChat((items) => [...items, { role: 'agent', text: `Could not start engineering job: ${error instanceof Error ? error.message : String(error)}` }]);
    }
  }

  const jobBusy = activeJob && !['completed', 'failed', 'cancelled'].includes(activeJob.state);

  return <main className="forge-shell">
    <aside className="copilot-rail">
      <header className="brand-block"><div className="brand-mark">A</div><div><h1>ForgeCAD</h1><span>AI Engineering Studio</span></div></header>
      <RuntimeBanner runtime={runtime} error={startupError}/>
      <div className="model-row"><Bot size={15}/><span>{runtime?.configured_model ?? 'qwen3:8b'}</span><ChevronDown size={14}/><span className="local-badge">LOCAL</span><Settings size={15}/></div>
      <section className="conversation" data-testid="conversation">
        {chat.map((entry, index) => <div className={`message ${entry.role === 'agent' ? 'agent' : ''}`} key={`${index}-${entry.text.slice(0, 20)}`}><div className={`avatar ${entry.role === 'agent' ? 'forge' : ''}`}>{entry.role === 'agent' ? 'A' : 'Y'}</div><div><div className="message-label">{entry.role === 'agent' ? 'ForgeCAD' : 'You'}</div><p>{entry.text}</p></div></div>)}
        {jobBusy && <div className="message agent live-message"><div className="avatar forge">A</div><div><div className="message-label">ForgeCAD · {activeJob?.state}</div><p>{streamText || activeJob?.message || 'Working…'}</p><div className="job-progress"><span style={{ width: `${Math.round((activeJob?.progress ?? 0) * 100)}%` }}/></div></div></div>}
      </section>
      <div className="quick-actions"><button>Explain selected part</button><button>Review design</button><button>Next test</button></div>
      <div className="composer"><textarea value={message} onChange={(e) => setMessage(e.target.value)} onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') void send(); }} placeholder="Describe your engineering task…"/><div className="composer-footer"><button className="clip">↗</button><label><input type="checkbox" checked={applyEdits} onChange={(e) => setApplyEdits(e.target.checked)}/>Apply edits</label><button className="send" data-testid="send-button" disabled={Boolean(jobBusy)} onClick={() => void send()} aria-label="Send engineering request"><Send size={18}/></button></div></div>
    </aside>

    <section className="workspace">
      <header className="project-toolbar"><div className="project-title">{project?.name ?? 'Loading project…'} <ChevronDown size={14}/></div><button className="branch-select"><GitBranch size={14}/>{project?.active_branch ?? '—'}<ChevronDown size={13}/></button><button className="icon-button"><Undo2 size={16}/></button><button className="icon-button"><Redo2 size={16}/></button><div className="toolbar-spacer"/><button className="toolbar-button">⇧ Import STEP</button><button className="toolbar-button"><FolderOpen size={15}/>Project</button><button className="dynamics-button"><Play size={15}/>Dynamics</button></header>
      <section className="lineage-strip"><span className="lineage-label">Design lineage⌄</span><div className="lineage-flow">{project?.branches.map((branch, index) => <div className="lineage-item" key={branch.name}><BranchCard branch={branch}/>{index < project.branches.length - 1 && <span className="lineage-arrow">→</span>}</div>)}</div><select><option>Design status: All</option></select><label className="verified-toggle"><input type="checkbox" defaultChecked/>Works in real life</label><button className="toolbar-button">Compare to working</button></section>
      <section className="main-stage">
        <div className="viewport-wrap">
          <Viewport explode={explode} onExplode={setExplode} onSelectionChange={setSelectedId} onReady={() => setSceneReady(true)} onError={(error) => setStartupError(error.message)}/>
          {selectedPart && <div className="selected-card"><button className="close" onClick={() => setSelectedId(null)}><X size={13}/></button><strong>{selectedPart.name}</strong><span className="selected-role">{selectedPart.role}</span><dl><dt>Mass</dt><dd>{selectedPart.mass_g} g</dd><dt>Material</dt><dd>{selectedPart.material}</dd><dt>Software</dt><dd>{selectedPart.programmable_workspace_id ? 'Attached workspace' : '—'}</dd></dl></div>}
          <div className={`scene-health ${sceneReady ? 'ready' : ''}`} data-testid="scene-health">{sceneReady ? '3D READY' : 'STARTING 3D'}</div>
        </div>
        <aside className="engineering-rail"><div className="rail-tabs">{(['design','components','analysis'] as RightTab[]).map((tab) => <button key={tab} className={rightTab === tab ? 'active' : ''} onClick={() => setRightTab(tab)}>{tab[0].toUpperCase()+tab.slice(1)}</button>)}</div>
          {rightTab === 'components' ? <div className="component-library"><h2>Real component library</h2><p>Actual parts from real suppliers. Buildable designs.</p><div className="search-box"><Search size={15}/><input defaultValue="solenoid" onChange={(e) => void fetchComponents(e.target.value).then((r) => setComponents(r.items))}/><button>☷</button></div><div className="filter-row"><button>Category All⌄</button><button>Voltage Any⌄</button><button>Supplier Any⌄</button></div><div className="results-meta"><span>{components.length} results</span><span>Sort: Relevance⌄</span></div>{components.map((item) => <ComponentCard key={item.id} item={item}/>)}<div className="campaign-card"><div className="campaign-title">⌬ <div><strong>Autonomous engineering campaign</strong><span>Let AI explore, simulate, and improve this design.</span></div></div><ul><li>Parameter optimizer (multi-objective)</li><li>Generate and test design variants</li><li>Validate against real-world constraints</li></ul><button onClick={() => void createJob({kind:'campaign', branch:project?.active_branch})}>Start engineering campaign →</button></div></div> : <div className="rail-empty"><strong>{rightTab === 'design' ? 'Design inspector' : 'Analysis workspace'}</strong><span>{rightTab === 'design' ? `${project?.parts.length ?? 0} physical parts · revision ${project?.revision ?? '—'}` : 'Async solver jobs mount here without blocking the viewport.'}</span></div>}
        </aside>
      </section>
      <section className="bottom-dock"><nav>{bottomTabs.map(({id,label,icon:Icon}) => <button data-testid={`tab-${id}`} key={id} className={bottomTab === id ? 'active' : ''} onClick={() => setBottomTab(id)}><Icon size={13}/>{label}</button>)}</nav><div className="dock-content"><BottomContent tab={bottomTab} project={project} workspaceId={workspaceId}/></div></section>
    </section>
  </main>;
}
