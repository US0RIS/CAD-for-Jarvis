import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Activity, Bot, Box, Check, ChevronDown, ChevronRight, CircleAlert, Code2, FileText,
  FolderOpen, GitBranch, History, Layers, MessageSquare, MoreHorizontal, Package, Play,
  Plus, Redo2, Search, Send, Settings, Undo2, X,
} from 'lucide-react';
import {
  activateBranch, addComponent, createJob, fetchComponents, fetchJob, fetchProject, fetchRegistryStats, fetchRuntime,
  importStepFile, newProject, redoHistory, subscribeEngineEvents, undoHistory,
  type ComponentPayload, type JobPayload, type ProjectPayload, type RegistryStatsPayload, type RuntimePayload,
} from './api/engine';
import { CodeWorkspace } from './components/CodeWorkspace';
import { EngineeringWorkbench } from './components/EngineeringWorkbench';
import { Viewport } from './components/Viewport';

type RightTab = 'properties' | 'components' | 'analysis';
type BrowserTab = 'model' | 'copilot';
type BottomTab = 'history' | 'code' | 'simulations' | 'system';
type ChatEntry = { role: 'user' | 'agent'; text: string };

const terminalStates = new Set<JobPayload['state']>(['completed', 'failed', 'cancelled']);

function RuntimeStatus({ runtime, error }: { runtime: RuntimePayload | null; error: string | null }) {
  const good = !error && runtime?.engine === 'ready';
  return <div className={`engine-state ${error ? 'error' : good ? 'ready' : ''}`} data-testid="runtime-banner" title={error ?? undefined}>
    <span className="state-dot"/>
    <span>{error ? 'Engine error' : good ? 'Engine ready' : 'Starting engine'}</span>
  </div>;
}

function MarkdownMessage({ text }: { text: string }) {
  return <div className="message-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>;
}

function BranchRow({ branch, onActivate }: { branch: ProjectPayload['branches'][number]; onActivate: (name: string) => void }) {
  return <button
    className={`browser-row branch-card ${branch.active ? 'selected' : ''}`}
    aria-pressed={branch.active}
    title={branch.active ? 'Active design branch' : `Switch to ${branch.name}`}
    onClick={() => onActivate(branch.name)}
  >
    <GitBranch size={13}/>
    <span className="browser-row-main"><strong>{branch.name}</strong><small>{branch.status.replace('_', ' ')}</small></span>
    {branch.active ? <Check size={13}/> : <ChevronRight size={13}/>} 
  </button>;
}

function ComponentImage({ item }: { item: ComponentPayload }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [item.image?.uri]);
  if (!item.image || failed) return <div className="component-image-fallback"><Package size={18}/></div>;
  return <img src={item.image.uri} alt="" loading="lazy" onError={() => setFailed(true)}/>;
}

function ComponentRow({ item, inserting, onInsert }: { item: ComponentPayload; inserting: boolean; onInsert: (id: string) => void }) {
  return <div className="component-row" data-testid={`component-${item.id}`}>
    <div className="component-thumb"><ComponentImage item={item}/></div>
    <div className="component-details">
      <div className="component-title"><strong>{item.model}</strong><span>{item.manufacturer}</span></div>
      <div className="component-spec-line">{item.key_specs.length ? item.key_specs.map((spec) => spec.value).join(' · ') : item.category}</div>
      <div className="component-meta">
        <span>{item.geometry_fidelity.replaceAll('_', ' ')}</span>
        {item.fit_score != null && <span>{item.fit_score}% fit</span>}
        <span>{item.price ? `${item.price.currency === 'USD' ? '$' : ''}${item.price.amount.toFixed(2)}` : 'price n/a'}</span>
      </div>
    </div>
    <button className="insert-button" disabled={inserting} onClick={() => onInsert(item.id)}>
      <Plus size={13}/>{inserting ? 'Inserting' : item.added ? 'Insert another' : 'Insert'}
    </button>
  </div>;
}

function PropertiesPanel({ project, selectedPart, onOpenCode }: { project: ProjectPayload | null; selectedPart: ProjectPayload['parts'][number] | null; onOpenCode: () => void }) {
  const active = project?.branches.find((branch) => branch.active) ?? null;
  return <div className="properties-panel">
    <div className="panel-title"><div><strong>{selectedPart ? 'Object properties' : 'Design properties'}</strong><small>{selectedPart ? selectedPart.role : project?.active_branch ?? 'main'}</small></div></div>
    {selectedPart ? <>
      <div className="property-section">
        <div className="property-section-title">IDENTITY</div>
        <dl className="property-grid"><dt>Name</dt><dd>{selectedPart.name}</dd><dt>Role</dt><dd>{selectedPart.role}</dd><dt>Source</dt><dd>{selectedPart.component_ref ?? 'Fabricated / imported'}</dd></dl>
      </div>
      <div className="property-section">
        <div className="property-section-title">PHYSICAL</div>
        <dl className="property-grid"><dt>Mass</dt><dd>{selectedPart.mass_g} g</dd><dt>Material</dt><dd>{selectedPart.material}</dd><dt>Geometry</dt><dd>{selectedPart.geometry_fidelity?.replaceAll('_', ' ') ?? 'CAD geometry'}</dd></dl>
      </div>
      {selectedPart.programmable_workspace_id && <div className="property-section"><button className="wide-action" onClick={onOpenCode}><Code2 size={13}/>Open embedded code</button></div>}
    </> : <div className="property-section">
      <div className="property-section-title">DOCUMENT</div>
      <dl className="property-grid"><dt>Name</dt><dd>{project?.name ?? 'Untitled Design'}</dd><dt>Branch</dt><dd>{project?.active_branch ?? 'main'}</dd><dt>Objects</dt><dd>{project?.parts.length ?? 0}</dd><dt>BOM lines</dt><dd>{project?.bom?.length ?? 0}</dd><dt>Connections</dt><dd>{project?.connections?.length ?? 0}</dd></dl>
    </div>}
    <div className="property-section">
      <div className="property-section-title">DESIGN STATE</div>
      <dl className="property-grid"><dt>Status</dt><dd>{active?.status.replace('_', ' ') ?? 'unverified'}</dd><dt>Physical</dt><dd>{active?.physical_verified ? 'Verified' : 'Not verified'}</dd><dt>History</dt><dd>{project?.history.length ?? 0} operations</dd></dl>
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
  if (tab === 'code') return workspaceId
    ? <CodeWorkspace workspaceId={workspaceId}/>
    : <div className="dock-empty"><Code2 size={18}/><span>Select a programmable component to open its workspace.</span></div>;
  if (tab === 'history') return <div className="history-panel">{project?.history.length
    ? project.history.slice().reverse().map((item, index) => <div className="history-row" key={`${item.time}-${index}`}><span>{item.branch}</span><strong>{item.message}</strong><small>{item.actor}</small></div>)
    : <div className="dock-empty"><History size={18}/><span>No design operations yet.</span></div>}</div>;
  if (tab === 'simulations') return <div className="dock-empty"><Activity size={18}/><strong>Simulation jobs</strong><span>{activeJob?.kind === 'simulation' ? `${activeJob.state}: ${activeJob.message ?? ''}` : 'Run Dynamics after geometry is present.'}</span></div>;
  return <div className="system-panel"><div><span>Forge Engine</span><strong>{runtime?.engine ?? 'starting'}</strong></div><div><span>Local model</span><strong>{runtime?.configured_model ?? 'checking'}</strong></div><div><span>Ollama</span><strong>{runtime?.ollama ?? 'checking'}</strong></div><div><span>API</span><strong>v{runtime?.api_version ?? '2'}</strong></div></div>;
}

export default function App() {
  const [browserTab, setBrowserTab] = useState<BrowserTab>('model');
  const [rightTab, setRightTab] = useState<RightTab>('components');
  const [bottomTab, setBottomTab] = useState<BottomTab | null>(null);
  const [explode, setExplode] = useState(0);
  const [message, setMessage] = useState('');
  const [applyEdits, setApplyEdits] = useState(true);
  const [runtime, setRuntime] = useState<RuntimePayload | null>(null);
  const [project, setProject] = useState<ProjectPayload | null>(null);
  const [components, setComponents] = useState<ComponentPayload[]>([]);
  const [componentQuery, setComponentQuery] = useState('');
  const [componentCategory, setComponentCategory] = useState('');
  const [componentVoltage, setComponentVoltage] = useState('');
  const [registryStats, setRegistryStats] = useState<RegistryStatsPayload | null>(null);
  const [insertingComponentId, setInsertingComponentId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sceneReady, setSceneReady] = useState(false);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<JobPayload | null>(null);
  const [streamText, setStreamText] = useState('');
  const [chat, setChat] = useState<ChatEntry[]>([
    { role: 'agent', text: 'Describe what you want to build or change. I can inspect the design, choose catalog components, and apply edits through Forge Engine.' },
  ]);
  const [newBusy, setNewBusy] = useState(false);
  const handledJobs = useRef(new Set<string>());
  const conversationRef = useRef<HTMLElement | null>(null);
  const stepInput = useRef<HTMLInputElement | null>(null);

  const selectedPart = useMemo(() => project?.parts.find((part) => part.id === selectedId) ?? null, [project, selectedId]);
  const workspaceId = selectedPart?.programmable_workspace_id ?? project?.parts.find((part) => part.programmable_workspace_id)?.programmable_workspace_id ?? null;
  const jobBusy = Boolean(activeJob && !terminalStates.has(activeJob.state));
  const hasGeometry = Boolean(project?.parts.length);
  const sceneRevision = project ? `${project.active_branch}:${project.revision}` : 'loading';

  const refreshProject = useCallback(async () => {
    const voltage = componentVoltage.trim() ? Number(componentVoltage) : undefined;
    const [nextProject, nextComponents, nextStats] = await Promise.all([
      fetchProject(),
      fetchComponents(componentQuery, componentCategory || undefined, Number.isFinite(voltage) ? voltage : undefined),
      fetchRegistryStats(),
    ]);
    setProject(nextProject);
    setComponents(nextComponents.items);
    setRegistryStats(nextStats);
    setSelectedId((current) => current && nextProject.parts.some((part) => part.id === current) ? current : null);
  }, [componentQuery, componentCategory, componentVoltage]);

  const acceptJobSnapshot = useCallback((job: JobPayload) => {
    setActiveJob(job);
    if (!terminalStates.has(job.state) || handledJobs.current.has(job.id)) return;
    handledJobs.current.add(job.id);
    if (job.state === 'completed') {
      const text = job.assistant_text.trim();
      if (text) setChat((items) => [...items, { role: 'agent', text }]);
    } else if (job.state === 'failed') {
      setChat((items) => [...items, { role: 'agent', text: `Engineering job failed: ${job.error?.message ?? job.message ?? 'Unknown local-engine error'}` }]);
    }
    setStreamText('');
    void refreshProject();
  }, [refreshProject]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const tasks = [
        fetchRuntime().then((next) => { if (!cancelled) setRuntime(next); }),
        fetchProject().then((next) => { if (!cancelled) { setProject(next); setSelectedId(null); } }),
        fetchComponents('').then((next) => { if (!cancelled) setComponents(next.items); }),
        fetchRegistryStats().then((next) => { if (!cancelled) setRegistryStats(next); }),
      ];
      const results = await Promise.allSettled(tasks);
      if (cancelled) return;
      const failure = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
      setStartupError(failure ? (failure.reason instanceof Error ? failure.reason.message : String(failure.reason)) : null);
    };
    void load();
    const runtimeTimer = window.setInterval(() => {
      void fetchRuntime().then((next) => { setRuntime(next); setStartupError(null); }).catch((error) => setStartupError(error instanceof Error ? error.message : String(error)));
    }, 3000);
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
      const voltage = componentVoltage.trim() ? Number(componentVoltage) : undefined;
      void fetchComponents(componentQuery, componentCategory || undefined, Number.isFinite(voltage) ? voltage : undefined)
        .then((result) => setComponents(result.items)).catch(() => undefined);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [componentQuery, componentCategory, componentVoltage]);

  useEffect(() => setSceneReady(false), [sceneRevision]);

  useEffect(() => {
    const node = conversationRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [chat, streamText, activeJob?.state]);

  const runAgent = useCallback(async (text: string, edits: boolean) => {
    const trimmed = text.trim();
    if (!trimmed || jobBusy) return;
    setChat((items) => [...items, { role: 'user', text: trimmed }]);
    setMessage('');
    setStreamText('');
    try {
      const job = await createJob({
        kind: 'agent', text: trimmed, selected_object_id: selectedId, apply_edits: edits,
        ...(project?.active_branch ? { branch: project.active_branch } : {}),
      });
      setActiveJob(job);
    } catch (error) {
      setChat((items) => [...items, { role: 'agent', text: `Could not start engineering job: ${error instanceof Error ? error.message : String(error)}` }]);
    }
  }, [jobBusy, project?.active_branch, selectedId]);

  async function switchBranch(name: string) {
    if (name === project?.active_branch) return;
    try {
      setSceneReady(false);
      setSelectedId(null);
      setProject(await activateBranch(name));
      setExplode(0);
    } catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
  }

  async function insertLibraryComponent(id: string) {
    setInsertingComponentId(id);
    try {
      setSceneReady(false);
      const result = await addComponent(id);
      setProject(result.project);
      setSelectedId(result.component.instance_id ?? null);
      setRightTab('properties');
      const refreshed = await fetchComponents(componentQuery, componentCategory || undefined, componentVoltage.trim() ? Number(componentVoltage) : undefined);
      setComponents(refreshed.items);
    } catch (error) {
      setStartupError(error instanceof Error ? error.message : String(error));
    } finally {
      setInsertingComponentId(null);
    }
  }

  async function createBlankProject() {
    if (newBusy) return;
    if (project?.parts.length && !window.confirm('Create a new blank design? The current local design remains in its exported files only.')) return;
    try {
      setNewBusy(true);
      setSceneReady(false);
      setSelectedId(null);
      setProject(await newProject());
      setExplode(0);
      setBottomTab(null);
      setRightTab('components');
    } catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
    finally { setNewBusy(false); }
  }

  async function importStep(file?: File) {
    if (!file) return;
    try {
      setSceneReady(false);
      const result = await importStepFile(file);
      setProject(result.project);
      const importedId = String(result.object.id ?? '');
      if (importedId) setSelectedId(importedId);
      setRightTab('properties');
    } catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
    finally { if (stepInput.current) stepInput.current.value = ''; }
  }

  async function undoDesign() {
    try { const result = await undoHistory(); setProject(result.project); setSelectedId(null); }
    catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
  }
  async function redoDesign() {
    try { const result = await redoHistory(); setProject(result.project); setSelectedId(null); }
    catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
  }
  async function startSimulation() {
    if (!hasGeometry) return;
    setBottomTab('simulations');
    try { setActiveJob(await createJob({ kind: 'simulation', selected_object_id: selectedId, ...(project?.active_branch ? { branch: project.active_branch } : {}) })); }
    catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
  }
  async function startCampaign() {
    if (!hasGeometry) return;
    try { setActiveJob(await createJob({ kind: 'campaign', selected_object_id: selectedId, ...(project?.active_branch ? { branch: project.active_branch } : {}) })); setBottomTab('simulations'); }
    catch (error) { setStartupError(error instanceof Error ? error.message : String(error)); }
  }

  return <main className="cad-app">
    <header className="app-bar">
      <div className="wordmark"><span className="wordmark-icon">F</span><strong>ForgeCAD</strong></div>
      <div className="doc-tab"><FileText size={13}/><span>{project?.name ?? 'Opening…'}</span><small>{project?.active_branch ?? ''}</small></div>
      <div className="app-bar-spacer"/>
      <RuntimeStatus runtime={runtime} error={startupError}/>
      <button className="toolbar-button" onClick={() => void createBlankProject()} disabled={newBusy}><Plus size={14}/>New</button>
      <button className="toolbar-button" onClick={() => stepInput.current?.click()}><FolderOpen size={14}/>Import</button>
      <button className="icon-button" title="Settings"><Settings size={15}/></button>
      <input ref={stepInput} hidden type="file" accept=".step,.stp" onChange={(event) => void importStep(event.target.files?.[0])}/>
    </header>

    <div className="workbench">
      <aside className="left-panel">
        <div className="panel-tabs compact">
          <button className={browserTab === 'model' ? 'active' : ''} onClick={() => setBrowserTab('model')}><Layers size={13}/>Model</button>
          <button className={browserTab === 'copilot' ? 'active' : ''} onClick={() => setBrowserTab('copilot')}><MessageSquare size={13}/>Copilot</button>
        </div>

        {browserTab === 'model' ? <div className="browser-content">
          <section className="browser-section">
            <div className="section-heading"><span>DESIGN</span><MoreHorizontal size={13}/></div>
            <div className="doc-summary"><strong>{project?.name ?? 'Untitled Design'}</strong><small>{project?.parts.length ?? 0} objects · {project?.bom?.length ?? 0} BOM lines</small></div>
          </section>
          <section className="browser-section grow">
            <div className="section-heading"><span>OBJECTS</span><span>{project?.parts.length ?? 0}</span></div>
            <div className="browser-list">
              {project?.parts.length ? project.parts.map((part) => <button key={part.id} className={`browser-row object-row ${selectedId === part.id ? 'selected' : ''}`} onClick={() => setSelectedId(part.id)}>
                <Box size={13}/><span className="browser-row-main"><strong>{part.name}</strong><small>{part.role}</small></span>{part.programmable_workspace_id && <Code2 size={12}/>}<ChevronRight size={12}/>
              </button>) : <div className="browser-empty">No geometry</div>}
            </div>
          </section>
          <section className="browser-section branches-section">
            <div className="section-heading"><span>DESIGNS</span><span>{project?.branches.length ?? 0}</span></div>
            <div className="browser-list">{project?.branches.map((branch) => <BranchRow key={branch.name} branch={branch} onActivate={(name) => void switchBranch(name)}/>)}</div>
          </section>
        </div> : <div className="copilot-pane">
          <div className="copilot-header"><Bot size={15}/><div><strong>Engineering Copilot</strong><small>{runtime?.configured_model ?? 'local model'} · local</small></div></div>
          <section className="conversation" ref={conversationRef} data-testid="conversation">
            {chat.map((entry, index) => <div className={`message ${entry.role}`} key={`${index}-${entry.text.slice(0, 18)}`}><span className="message-author">{entry.role === 'agent' ? 'ForgeCAD' : 'You'}</span>{entry.role === 'agent' ? <MarkdownMessage text={entry.text}/> : <p>{entry.text}</p>}</div>)}
            {jobBusy && <div className="message agent live"><span className="message-author">ForgeCAD · {activeJob?.state}</span><MarkdownMessage text={streamText || activeJob?.message || 'Working…'}/><div className="job-progress"><span style={{ width: `${Math.round((activeJob?.progress ?? 0) * 100)}%` }}/></div></div>}
          </section>
          <div className="composer" data-testid="composer">
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') void runAgent(message, applyEdits); }} placeholder="Ask about this design…"/>
            <div className="composer-footer"><label><input type="checkbox" checked={applyEdits} onChange={(event) => setApplyEdits(event.target.checked)}/>Allow edits</label><button className="send-button" data-testid="send-button" disabled={jobBusy || !message.trim()} onClick={() => void runAgent(message, applyEdits)}><Send size={14}/></button></div>
          </div>
        </div>}
      </aside>

      <section className={`center-column ${bottomTab ? 'dock-open' : ''}`}>
        <div className="document-toolbar">
          <div className="tool-group"><button className="icon-button" title="Undo" onClick={() => void undoDesign()}><Undo2 size={15}/></button><button className="icon-button" title="Redo" onClick={() => void redoDesign()}><Redo2 size={15}/></button></div>
          <div className="tool-divider"/>
          <label className="branch-picker"><GitBranch size={13}/><select value={project?.active_branch ?? ''} onChange={(event) => void switchBranch(event.target.value)}>{project?.branches.map((branch) => <option key={branch.name} value={branch.name}>{branch.name}</option>)}</select><ChevronDown size={12}/></label>
          <div className="tool-divider"/>
          <button className="toolbar-button" onClick={() => setRightTab('components')}><Package size={14}/>Insert component</button>
          <button className="toolbar-button" onClick={() => stepInput.current?.click()}><FolderOpen size={14}/>Import STEP</button>
          <div className="document-toolbar-spacer"/>
          <button className="toolbar-button" disabled={!hasGeometry} onClick={() => setBottomTab(bottomTab === 'history' ? null : 'history')}><History size={14}/>History</button>
          <button className="primary-action" disabled={!hasGeometry} onClick={() => void startSimulation()}><Play size={14}/>Dynamics</button>
        </div>

        <div className="viewport-wrap">
          <Viewport
            explode={explode}
            onExplode={setExplode}
            onSelectionChange={setSelectedId}
            onReady={() => setSceneReady(true)}
            onLoading={() => setSceneReady(false)}
            onError={(error) => { setSceneReady(false); setStartupError(error.message); }}
            sceneRevision={sceneRevision}
            selectedId={selectedId}
            empty={!hasGeometry}
          />
          {!hasGeometry && sceneReady && <div className="empty-canvas">
            <Box size={24}/><strong>No geometry</strong><span>Insert a catalog component or import a STEP file to begin.</span>
            <div><button onClick={() => setRightTab('components')}><Package size={13}/>Insert component</button><button onClick={() => stepInput.current?.click()}><FolderOpen size={13}/>Import STEP</button></div>
          </div>}
          {selectedPart && <div className="selection-chip"><span><strong>{selectedPart.name}</strong><small>{selectedPart.role}</small></span><button onClick={() => setSelectedId(null)}><X size={12}/></button></div>}
          <div className={`scene-health ${sceneReady ? 'ready' : ''}`} data-testid="scene-health">{sceneReady ? '3D READY' : 'STARTING 3D'}</div>
        </div>

        <div className="bottom-bar">
          <button data-testid="tab-history" className={bottomTab === 'history' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'history' ? null : 'history')}><History size={12}/>History</button>
          <button data-testid="tab-code" className={bottomTab === 'code' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'code' ? null : 'code')}><Code2 size={12}/>Code</button>
          <button data-testid="tab-simulations" className={bottomTab === 'simulations' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'simulations' ? null : 'simulations')}><Activity size={12}/>Simulation</button>
          <button data-testid="tab-system" className={bottomTab === 'system' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'system' ? null : 'system')}><Settings size={12}/>System</button>
          <div className="bottom-spacer"/><span>{project?.parts.length ?? 0} objects</span><span>mm</span><span>Z up</span>
        </div>
        {bottomTab && <div className="bottom-dock"><BottomContent tab={bottomTab} project={project} workspaceId={workspaceId} runtime={runtime} activeJob={activeJob}/></div>}
      </section>

      <aside className="right-panel">
        <div className="panel-tabs">
          <button className={rightTab === 'properties' ? 'active' : ''} onClick={() => setRightTab('properties')}>Properties</button>
          <button className={rightTab === 'components' ? 'active' : ''} onClick={() => setRightTab('components')}>Components</button>
          <button className={rightTab === 'analysis' ? 'active' : ''} onClick={() => setRightTab('analysis')}>Analyze</button>
        </div>
        {rightTab === 'components' ? <div className="component-panel">
          <div className="panel-title"><div><strong>Component library</strong><small>{registryStats?.total ?? '…'} catalog parts</small></div></div>
          <div className="search-control"><Search size={14}/><input value={componentQuery} onChange={(event) => setComponentQuery(event.target.value)} placeholder="Search manufacturer, model, category…"/></div>
          <div className="component-filters"><select value={componentCategory} onChange={(event) => setComponentCategory(event.target.value)}><option value="">All categories</option>{registryStats?.categories.map((category) => <option value={category} key={category}>{category}</option>)}</select><input value={componentVoltage} onChange={(event) => setComponentVoltage(event.target.value)} placeholder="Voltage" inputMode="decimal"/></div>
          <div className="result-count">{components.length} results</div>
          <div className="component-results">{components.map((item) => <ComponentRow key={item.id} item={item} inserting={insertingComponentId === item.id} onInsert={(id) => void insertLibraryComponent(id)}/>)}</div>
        </div> : rightTab === 'properties' ? <PropertiesPanel project={project} selectedPart={selectedPart} onOpenCode={() => setBottomTab('code')}/> : <EngineeringWorkbench mode="analysis" project={project} selectedId={selectedId} activeJob={activeJob} onProject={setProject} onStartSimulation={() => void startSimulation()} onStartCampaign={() => void startCampaign()}/>} 
      </aside>
    </div>
  </main>;
}
