import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Activity, BookOpen, Bot, Check, ChevronDown, Code2, FolderOpen, GitBranch, History, Play,
  Search, Send, Settings, ShieldCheck, Undo2, Redo2, X, CircleAlert,
} from 'lucide-react';
import {
  activateBranch, addComponent, createJob, fetchComponents, fetchJob, fetchProject, fetchRuntime,
  subscribeEngineEvents, type ComponentPayload, type JobPayload, type ProjectPayload, type RuntimePayload,
} from './api/engine';
import { CodeWorkspace } from './components/CodeWorkspace';
import { Viewport } from './components/Viewport';

type RightTab = 'design' | 'components' | 'analysis';
type BottomTab = 'simulations' | 'notebook' | 'designs' | 'history' | 'code' | 'system';
type ChatEntry = { role: 'user' | 'agent'; text: string };
type DesignStatusFilter = 'all' | 'working' | 'not_working' | 'unverified';

const terminalStates = new Set<JobPayload['state']>(['completed', 'failed', 'cancelled']);

const bottomTabs: Array<{ id: BottomTab; label: string; icon: typeof Activity }> = [
  { id: 'simulations', label: 'SIMULATIONS', icon: Activity },
  { id: 'notebook', label: 'NOTEBOOK', icon: BookOpen },
  { id: 'designs', label: 'DESIGNS', icon: GitBranch },
  { id: 'history', label: 'HISTORY', icon: History },
  { id: 'code', label: 'CODE', icon: Code2 },
  { id: 'system', label: 'SYSTEM', icon: Settings },
];

function MarkdownMessage({ text, live = false }: { text: string; live?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > 900;
  return <div className={`markdown-shell ${long && !expanded ? 'collapsed' : ''} ${live ? 'live' : ''}`}>
    <div className="message-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
    {long && <button className="message-expander" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Collapse response' : 'Show full response'}</button>}
  </div>;
}

function BranchCard({ branch, onActivate }: { branch: ProjectPayload['branches'][number]; onActivate: (name: string) => void }) {
  const tone = branch.status === 'working' ? 'good' : branch.status === 'not_working' ? 'bad' : 'muted';
  return <button
    className={`branch-card ${tone} ${branch.active ? 'active-branch' : ''}`}
    onClick={() => onActivate(branch.name)}
    aria-pressed={branch.active}
    title={branch.active ? 'Active design branch' : `Switch to ${branch.name}`}
  >
    <span className="branch-title"><span className="status-dot"/>{branch.name}</span>
    <span className="branch-meta"><span>{branch.status.replace('_', ' ')}</span>{branch.protected ? <span className="protected"><ShieldCheck size={11}/>Protected</span> : <span>{branch.commit_count} commit{branch.commit_count === 1 ? '' : 's'}</span>}</span>
  </button>;
}

function ComponentImage({ item }: { item: ComponentPayload }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [item.image?.uri]);
  if (!item.image || failed) return <div className="image-fallback"><span>{item.category.toUpperCase()}</span><small>Image unavailable</small></div>;
  return <img src={item.image.uri} alt={`${item.manufacturer} ${item.model}`} loading="eager" onError={() => setFailed(true)}/>;
}

function ComponentCard({ item, adding, onAdd }: { item: ComponentPayload; adding: boolean; onAdd: (id: string) => void }) {
  return <article className="component-card" data-testid={`component-${item.id}`}>
    <div className="component-thumb photo"><ComponentImage item={item}/></div>
    <div className="component-copy">
      <div className="component-name-row"><strong>{item.model}</strong>{item.fit_score != null && <span className="match-score">{item.fit_score}% match</span>}</div>
      <div className="component-specs">{item.key_specs.map((spec) => spec.value).join('  ·  ')}</div>
      <div className="component-footer">
        <span>{item.price ? `${item.price.currency === 'USD' ? '$' : ''}${item.price.amount.toFixed(2)}` : 'Price unknown'}</span><span>·</span><span>{item.price?.supplier ?? item.manufacturer}</span>
        <button className={item.added ? 'added-button' : 'add-button'} disabled={item.added || adding} onClick={() => onAdd(item.id)}>
          {item.added ? <><Check size={12}/>Added</> : adding ? 'Adding…' : 'Add'}
        </button>
      </div>
    </div>
  </article>;
}

function RuntimeBanner({ runtime, error }: { runtime: RuntimePayload | null; error: string | null }) {
  if (error) return <div className="runtime-banner error"><CircleAlert size={16}/><div><strong>Forge Engine needs attention</strong><span>{error}</span></div></div>;
  const ready = runtime?.engine === 'ready' && runtime?.ollama === 'ready';
  const unavailable = runtime?.ollama === 'failed' || runtime?.ollama === 'offline';
  return <div className={`runtime-banner ${ready ? '' : unavailable ? 'error' : 'warming'}`} data-testid="runtime-banner">
    {ready ? <Check size={15}/> : unavailable ? <CircleAlert size={15}/> : <span className="spinner"/>}
    <div>
      <strong>{ready ? 'Local engineering copilot is online' : runtime?.ollama === 'failed' ? `${runtime.configured_model} is not installed` : runtime?.ollama === 'offline' ? 'Ollama is offline' : 'Starting local engineering copilot'}</strong>
      <span>{ready ? 'All design data stays on your machine.' : `Configured model: ${runtime?.configured_model ?? 'local model'}`}</span>
    </div>
  </div>;
}

function BottomContent({ tab, project, workspaceId, runtime, activeJob }: {
  tab: BottomTab;
  project: ProjectPayload | null;
  workspaceId: string | null;
  runtime: RuntimePayload | null;
  activeJob: JobPayload | null;
}) {
  if (tab === 'code' && workspaceId) return <CodeWorkspace workspaceId={workspaceId}/>;
  if (tab === 'history') return <div className="history-panel">{project?.history.slice().reverse().map((item, index) => <div className="history-row" key={`${item.time}-${index}`}><span>{item.branch}</span><strong>{item.message}</strong><small>{item.actor}</small></div>)}</div>;
  if (tab === 'designs') return <div className="dock-placeholder"><strong>DESIGN BRANCHES</strong><span>{project?.branches.length ?? 0} branches · active {project?.active_branch ?? '—'} · working baseline remains protected</span></div>;
  if (tab === 'simulations') return <div className="dock-placeholder"><strong>SIMULATIONS</strong><span>{activeJob?.kind === 'simulation' ? `${activeJob.state}: ${activeJob.message ?? ''}` : 'Start Dynamics to queue a non-blocking simulation job.'}</span></div>;
  if (tab === 'system') return <div className="dock-placeholder"><strong>SYSTEM</strong><span>Engine {runtime?.engine ?? 'starting'} · Ollama {runtime?.ollama ?? 'checking'} · {runtime?.configured_model ?? 'local model'}</span></div>;
  return <div className="dock-placeholder"><strong>{tab.toUpperCase()}</strong><span>This panel stays mounted without taking control away from the 3D workspace.</span></div>;
}

export default function App() {
  const [rightTab, setRightTab] = useState<RightTab>('components');
  const [bottomTab, setBottomTab] = useState<BottomTab>('code');
  const [explode, setExplode] = useState(0);
  const [message, setMessage] = useState('');
  const [applyEdits, setApplyEdits] = useState(true);
  const [runtime, setRuntime] = useState<RuntimePayload | null>(null);
  const [project, setProject] = useState<ProjectPayload | null>(null);
  const [components, setComponents] = useState<ComponentPayload[]>([]);
  const [componentQuery, setComponentQuery] = useState('');
  const [addingComponentId, setAddingComponentId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>('raspberry-pi');
  const [sceneReady, setSceneReady] = useState(false);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<JobPayload | null>(null);
  const [streamText, setStreamText] = useState('');
  const [designStatusFilter, setDesignStatusFilter] = useState<DesignStatusFilter>('all');
  const [chat, setChat] = useState<ChatEntry[]>([
    { role: 'agent', text: 'Ready. The physically verified **baseline** is protected. Describe a change and I’ll work on a child branch unless you turn **Apply edits** off.' },
  ]);
  const handledJobs = useRef(new Set<string>());
  const conversationRef = useRef<HTMLElement | null>(null);
  const followConversation = useRef(true);

  const selectedPart = useMemo(() => project?.parts.find((part) => part.id === selectedId) ?? null, [project, selectedId]);
  const workspaceId = selectedPart?.programmable_workspace_id ?? project?.parts.find((part) => part.programmable_workspace_id)?.programmable_workspace_id ?? null;
  const activeBranch = useMemo(() => project?.branches.find((branch) => branch.active) ?? null, [project]);
  const visibleBranches = useMemo(() => project?.branches.filter((branch) => designStatusFilter === 'all' || branch.status === designStatusFilter) ?? [], [project, designStatusFilter]);
  const jobBusy = Boolean(activeJob && !terminalStates.has(activeJob.state));

  const refreshProject = useCallback(async () => {
    const [nextProject, nextComponents] = await Promise.all([fetchProject(), fetchComponents(componentQuery)]);
    setProject(nextProject);
    setComponents(nextComponents.items);
  }, [componentQuery]);

  const acceptJobSnapshot = useCallback((job: JobPayload) => {
    setActiveJob(job);
    if (!terminalStates.has(job.state) || handledJobs.current.has(job.id)) return;
    handledJobs.current.add(job.id);
    if (job.state === 'completed') {
      const text = job.assistant_text.trim();
      if (text) setChat((items) => [...items, { role: 'agent', text }]);
    } else if (job.state === 'failed') {
      setChat((items) => [...items, { role: 'agent', text: `**Engineering job failed:** ${job.error?.message ?? job.message ?? 'Unknown local-engine error'}` }]);
    }
    setStreamText('');
    void refreshProject();
  }, [refreshProject]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [nextRuntime, nextProject, nextComponents] = await Promise.all([fetchRuntime(), fetchProject(), fetchComponents('')]);
        if (cancelled) return;
        setRuntime(nextRuntime);
        setProject(nextProject);
        setComponents(nextComponents.items);
        setStartupError(null);
      } catch (error) {
        if (!cancelled) setStartupError(error instanceof Error ? error.message : String(error));
      }
    };
    void load();
    const runtimeTimer = window.setInterval(() => {
      void fetchRuntime().then((nextRuntime) => { setRuntime(nextRuntime); setStartupError(null); }).catch((error) => setStartupError(error instanceof Error ? error.message : String(error)));
    }, 2500);
    let stop: (() => void) | undefined;
    void subscribeEngineEvents((event) => {
      if (event.type === 'job.updated') acceptJobSnapshot(event.job);
      else if (event.type === 'job.token') setStreamText((value) => value + event.token);
      else if (event.type === 'project.updated') setProject(event.project);
    }).then((cleanup) => { stop = cleanup; }).catch(() => undefined);
    return () => { cancelled = true; window.clearInterval(runtimeTimer); stop?.(); };
  }, [acceptJobSnapshot]);

  useEffect(() => {
    if (!activeJob || terminalStates.has(activeJob.state)) return;
    const jobId = activeJob.id;
    const poll = window.setInterval(() => void fetchJob(jobId).then(acceptJobSnapshot).catch(() => undefined), 900);
    return () => window.clearInterval(poll);
  }, [activeJob?.id, activeJob?.state, acceptJobSnapshot]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchComponents(componentQuery).then((result) => setComponents(result.items)).catch(() => undefined);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [componentQuery]);

  useEffect(() => {
    const node = conversationRef.current;
    if (node && followConversation.current) node.scrollTop = node.scrollHeight;
  }, [chat, streamText, activeJob?.state]);

  const runAgent = useCallback(async (text: string, edits: boolean) => {
    const trimmed = text.trim();
    if (!trimmed || jobBusy) return;
    setChat((items) => [...items, { role: 'user', text: trimmed }]);
    setMessage('');
    setStreamText('');
    try {
      const input = {
        kind: 'agent' as const,
        text: trimmed,
        selected_object_id: selectedId,
        apply_edits: edits,
        ...(project?.active_branch ? { branch: project.active_branch } : {}),
      };
      const job = await createJob(input);
      setActiveJob(job);
    } catch (error) {
      setChat((items) => [...items, { role: 'agent', text: `**Could not start engineering job:** ${error instanceof Error ? error.message : String(error)}` }]);
    }
  }, [jobBusy, project?.active_branch, selectedId]);

  async function switchBranch(name: string) {
    try {
      const next = await activateBranch(name);
      setProject(next);
      setExplode(0);
    } catch (error) {
      setStartupError(error instanceof Error ? error.message : String(error));
    }
  }

  async function addLibraryComponent(id: string) {
    setAddingComponentId(id);
    try {
      const result = await addComponent(id);
      setProject(result.project);
      setComponents((items) => items.map((item) => item.id === id ? { ...item, added: true } : item));
    } catch (error) {
      setStartupError(error instanceof Error ? error.message : String(error));
    } finally {
      setAddingComponentId(null);
    }
  }

  async function startSimulation() {
    setBottomTab('simulations');
    try {
      const job = await createJob({ kind: 'simulation', ...(project?.active_branch ? { branch: project.active_branch } : {}) });
      setActiveJob(job);
    } catch (error) {
      setStartupError(error instanceof Error ? error.message : String(error));
    }
  }

  async function startCampaign() {
    try {
      const job = await createJob({ kind: 'campaign', ...(project?.active_branch ? { branch: project.active_branch } : {}) });
      setActiveJob(job);
      setBottomTab('designs');
    } catch (error) {
      setStartupError(error instanceof Error ? error.message : String(error));
    }
  }

  return <main className="forge-shell">
    <aside className="copilot-rail">
      <header className="brand-block"><div className="brand-mark">A</div><div><h1>ForgeCAD</h1><span>AI Engineering Studio</span></div></header>
      <RuntimeBanner runtime={runtime} error={startupError}/>
      <div className="model-row"><Bot size={15}/><span>{runtime?.configured_model ?? 'local model'}</span><ChevronDown size={14}/><span className="local-badge">LOCAL</span><Settings size={15}/></div>
      <section
        className="conversation"
        data-testid="conversation"
        ref={conversationRef}
        onScroll={(event) => {
          const node = event.currentTarget;
          followConversation.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
        }}
      >
        {chat.map((entry, index) => <div className={`message ${entry.role === 'agent' ? 'agent' : ''}`} key={`${index}-${entry.text.slice(0, 20)}`}>
          <div className={`avatar ${entry.role === 'agent' ? 'forge' : ''}`}>{entry.role === 'agent' ? 'A' : 'Y'}</div>
          <div className="message-body"><div className="message-label">{entry.role === 'agent' ? 'ForgeCAD' : 'You'}</div>{entry.role === 'agent' ? <MarkdownMessage text={entry.text}/> : <p className="user-text">{entry.text}</p>}</div>
        </div>)}
        {jobBusy && <div className="message agent live-message"><div className="avatar forge">A</div><div className="message-body"><div className="message-label">ForgeCAD · {activeJob?.state}</div><MarkdownMessage text={streamText || activeJob?.message || 'Working…'} live/><div className="job-progress"><span style={{ width: `${Math.round((activeJob?.progress ?? 0) * 100)}%` }}/></div></div></div>}
      </section>
      <div className="quick-actions">
        <button disabled={jobBusy} onClick={() => void runAgent(`Explain the selected part${selectedPart ? ` (${selectedPart.name})` : ''}, its interfaces, and the one most important engineering risk.`, false)}>Explain selected part</button>
        <button disabled={jobBusy} onClick={() => void runAgent('Review the active design. Give me the three most important engineering risks and the next verification step.', false)}>Review design</button>
        <button disabled={jobBusy} onClick={() => void runAgent('What is the single highest-value physical or simulation test I should run next, and what result would count as a pass?', false)}>Next test</button>
      </div>
      <div className="composer" data-testid="composer"><textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') void runAgent(message, applyEdits); }} placeholder="Describe your engineering task…"/><div className="composer-footer"><button className="clip" disabled title="Attachments are not enabled in this slice">↗</button><label><input type="checkbox" checked={applyEdits} onChange={(event) => setApplyEdits(event.target.checked)}/>Apply edits</label><button className="send" data-testid="send-button" disabled={jobBusy || !message.trim()} onClick={() => void runAgent(message, applyEdits)} aria-label="Send engineering request"><Send size={18}/></button></div></div>
    </aside>

    <section className="workspace">
      <header className="project-toolbar">
        <div className="project-title">{project?.name ?? 'Loading project…'} <ChevronDown size={14}/></div>
        <button className="branch-select" onClick={() => setBottomTab('designs')}><GitBranch size={14}/>{project?.active_branch ?? '—'}<ChevronDown size={13}/></button>
        <button className="icon-button" disabled title="Undo will be enabled when command history lands"><Undo2 size={16}/></button>
        <button className="icon-button" disabled title="Redo will be enabled when command history lands"><Redo2 size={16}/></button>
        <div className="toolbar-spacer"/>
        <button className="toolbar-button" disabled title="STEP import is not implemented in this vertical slice">⇧ Import STEP</button>
        <button className="toolbar-button" onClick={() => setBottomTab('designs')}><FolderOpen size={15}/>Project</button>
        <button className="dynamics-button" onClick={() => void startSimulation()}><Play size={15}/>Dynamics</button>
      </header>

      <section className="lineage-strip">
        <span className="lineage-label">Design lineage⌄</span>
        <div className="lineage-flow">{visibleBranches.map((branch, index) => <div className="lineage-item" key={branch.name}><BranchCard branch={branch} onActivate={(name) => void switchBranch(name)}/>{index < visibleBranches.length - 1 && <span className="lineage-arrow">→</span>}</div>)}</div>
        <select value={designStatusFilter} onChange={(event) => setDesignStatusFilter(event.target.value as DesignStatusFilter)} aria-label="Design status filter"><option value="all">Design status: All</option><option value="working">Working</option><option value="not_working">Not working</option><option value="unverified">Unverified</option></select>
        <label className="verified-toggle" title="Physical verification status comes from the active branch"><input type="checkbox" checked={Boolean(activeBranch?.physical_verified)} readOnly/>Works in real life</label>
        <button className="toolbar-button" onClick={() => { setRightTab('design'); setBottomTab('designs'); }}>Compare to working</button>
      </section>

      <section className="main-stage">
        <div className="viewport-wrap">
          <Viewport explode={explode} onExplode={setExplode} onSelectionChange={setSelectedId} onReady={() => setSceneReady(true)} onError={(error) => setStartupError(error.message)}/>
          {selectedPart && <div className="selected-card"><button className="close" onClick={() => setSelectedId(null)}><X size={13}/></button><strong>{selectedPart.name}</strong><span className="selected-role">{selectedPart.role}</span><dl><dt>Mass</dt><dd>{selectedPart.mass_g} g</dd><dt>Material</dt><dd>{selectedPart.material}</dd><dt>Software</dt><dd>{selectedPart.programmable_workspace_id ? 'Attached workspace' : '—'}</dd></dl></div>}
          <div className={`scene-health ${sceneReady ? 'ready' : ''}`} data-testid="scene-health">{sceneReady ? '3D READY' : 'STARTING 3D'}</div>
        </div>

        <aside className="engineering-rail">
          <div className="rail-tabs">{(['design', 'components', 'analysis'] as RightTab[]).map((tab) => <button key={tab} className={rightTab === tab ? 'active' : ''} onClick={() => setRightTab(tab)}>{tab.charAt(0).toUpperCase() + tab.slice(1)}</button>)}</div>
          {rightTab === 'components' ? <div className="component-library">
            <h2>Real component library</h2><p>Actual parts from real suppliers. Buildable designs.</p>
            <div className="search-box"><Search size={15}/><input value={componentQuery} placeholder="Search components" onChange={(event) => setComponentQuery(event.target.value)}/><button disabled title="Advanced filters are not enabled yet">☷</button></div>
            <div className="filter-row"><button disabled>Category All⌄</button><button disabled>Voltage Any⌄</button><button disabled>Supplier Any⌄</button></div>
            <div className="results-meta"><span>{components.length} results</span><span>Sort: Relevance</span></div>
            {components.map((item) => <ComponentCard key={item.id} item={item} adding={addingComponentId === item.id} onAdd={(id) => void addLibraryComponent(id)}/>)}
            <div className="campaign-card"><div className="campaign-title">⌬ <div><strong>Autonomous engineering campaign</strong><span>Let AI explore, simulate, and improve this design.</span></div></div><ul><li>Parameter optimizer (multi-objective)</li><li>Generate and test design variants</li><li>Validate against real-world constraints</li></ul><button disabled={jobBusy} onClick={() => void startCampaign()}>Start engineering campaign →</button></div>
          </div> : <div className="rail-empty"><strong>{rightTab === 'design' ? 'Design inspector' : 'Analysis workspace'}</strong><span>{rightTab === 'design' ? `${project?.parts.length ?? 0} physical parts · revision ${project?.revision ?? '—'} · active ${project?.active_branch ?? '—'}` : 'Async solver jobs mount here without blocking the viewport.'}</span></div>}
        </aside>
      </section>

      <section className="bottom-dock">
        <nav>{bottomTabs.map(({ id, label, icon: Icon }) => <button data-testid={`tab-${id}`} key={id} className={bottomTab === id ? 'active' : ''} onClick={() => setBottomTab(id)}><Icon size={12}/>{label}</button>)}</nav>
        <div className="dock-content"><BottomContent tab={bottomTab} project={project} workspaceId={workspaceId} runtime={runtime} activeJob={activeJob}/></div>
      </section>
    </section>
  </main>;
}
