import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Activity, Bot, Box, Check, ChevronDown, ChevronRight, CircleAlert, Code2, Download, FileText,
  FolderOpen, GitBranch, History, Keyboard, Layers, MessageSquare, MoreHorizontal, Package, Play, Printer,
  Plus, Redo2, Search, Send, Settings, Trash2, Undo2, Upload, X,
} from 'lucide-react';
import {
  activateBranch, addComponent, createJob, deleteObject, downloadProjectBundle, engineFetch, fetchComponents, fetchJob, fetchProject, fetchRegistryStats, fetchRuntime,
  importProjectBundle, importStepFile, newProject, redoHistory, subscribeEngineEvents, undoHistory,
  type ComponentPayload, type JobPayload, type ProjectPayload, type RegistryStatsPayload, type RuntimePayload,
} from './api/engine';
import { CodeWorkspace } from './components/CodeWorkspace';
import { DesignLineagePanel } from './components/DesignLineagePanel';
import { EngineeringWorkbench } from './components/EngineeringWorkbench';
import { FeatureHistoryPanel } from './components/FeatureHistoryPanel';
import { ManufacturePanel } from './components/ManufacturePanel';
import { Viewport } from './components/Viewport';
import { WorldSystemPanel } from './components/WorldSystemPanel';

type RightTab = 'properties' | 'components' | 'analysis' | 'manufacture';
type BrowserTab = 'model' | 'copilot';
type BottomTab = 'history' | 'code' | 'simulations' | 'system';
type ChatEntry = { role: 'user' | 'agent'; text: string };

const terminalStates = new Set<JobPayload['state']>(['completed', 'failed', 'cancelled']);
const jobStateLabels: Record<JobPayload['state'], string> = {
  queued: 'Queued', warming: 'Starting local AI', planning: 'Planning', applying: 'Applying changes',
  analyzing: 'Analyzing', verifying: 'Verifying', completed: 'Complete', failed: 'Failed', cancelled: 'Cancelled',
};
let componentThumbnailQueue: Promise<void> = Promise.resolve();
const THUMBNAIL_GRACE_MS = 500;
const THUMBNAIL_COOLDOWN_MS = 350;

function delay(ms: number) { return new Promise<void>((resolve) => window.setTimeout(resolve, ms)); }
function formatElapsed(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return minutes ? `${minutes}:${String(remainder).padStart(2, '0')}` : `${remainder}s`;
}
function messageOf(error: unknown) { return error instanceof Error ? error.message : String(error); }
function engineeringJobLabel(job: JobPayload) {
  if (job.kind === 'campaign') return 'Variant campaign';
  if (job.kind === 'simulation') return 'Dynamics simulation';
  if (job.kind === 'deploy') return 'Deployment';
  if (job.kind === 'component-search') return 'Component search';
  return job.kind.replaceAll('-', ' ');
}

function RuntimeStatus({ runtime, error }: { runtime: RuntimePayload | null; error: string | null }) {
  const good = !error && runtime?.engine === 'ready';
  return <div className={`engine-state ${error ? 'error' : good ? 'ready' : ''}`} data-testid="runtime-banner" title={error ?? undefined}>
    <span className="state-dot"/><span>{error ? 'Engine error' : good ? 'Engine ready' : 'Starting engine'}</span>
  </div>;
}
function MarkdownMessage({ text }: { text: string }) {
  return <div className="message-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>;
}
function BranchRow({ branch, onActivate }: { branch: ProjectPayload['branches'][number]; onActivate: (name: string) => void }) {
  return <button className={`browser-row branch-card ${branch.active ? 'selected' : ''}`} aria-pressed={branch.active} title={branch.active ? 'Active design branch' : `Switch to ${branch.name}`} onClick={() => onActivate(branch.name)}>
    <GitBranch size={13}/><span className="browser-row-main"><strong>{branch.name}</strong><small>{branch.status.replace('_', ' ')}{branch.physical_verified ? ' · physical evidence' : ''}</small></span>{branch.active ? <Check size={13}/> : <ChevronRight size={13}/>} 
  </button>;
}

function ComponentImage({ item }: { item: ComponentPayload }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const queuedRef = useRef(false);
  const [requested, setRequested] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => { queuedRef.current = false; setRequested(false); setFailed(false); }, [item.image?.uri]);
  useEffect(() => {
    const node = hostRef.current;
    const uri = item.image?.uri;
    if (!node || requested || failed || !uri) return;
    let cancelled = false;
    let graceTimer: number | null = null;
    const prime = () => {
      if (queuedRef.current) return;
      queuedRef.current = true;
      componentThumbnailQueue = componentThumbnailQueue.catch(() => undefined).then(async () => {
        if (cancelled) return;
        const response = await fetch(uri, { cache: 'force-cache' });
        if (!response.ok) throw new Error(`Thumbnail ${response.status}`);
        await response.blob();
        if (!cancelled) setRequested(true);
        await delay(THUMBNAIL_COOLDOWN_MS);
      }).catch(() => { if (!cancelled) setFailed(true); });
    };
    const schedulePrime = () => {
      if (graceTimer != null || queuedRef.current) return;
      graceTimer = window.setTimeout(() => { graceTimer = null; prime(); }, THUMBNAIL_GRACE_MS);
    };
    if (!('IntersectionObserver' in window)) {
      schedulePrime();
      return () => { cancelled = true; if (graceTimer != null) window.clearTimeout(graceTimer); };
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      schedulePrime(); observer.disconnect();
    }, { rootMargin: '120px 0px', threshold: 0.01 });
    observer.observe(node);
    return () => { cancelled = true; if (graceTimer != null) window.clearTimeout(graceTimer); observer.disconnect(); };
  }, [failed, item.image?.uri, requested]);
  return <div ref={hostRef} style={{ width: '100%', height: '100%', display: 'grid', placeItems: 'center' }}>
    {requested && item.image?.uri && !failed ? <img src={item.image.uri} alt={`${item.manufacturer} ${item.model}`} decoding="async" onError={() => setFailed(true)}/> : <div className="component-image-fallback"><Package size={18}/></div>}
  </div>;
}
function ComponentRow({ item, inserting, onInsert }: { item: ComponentPayload; inserting: boolean; onInsert: (id: string) => void }) {
  return <div className="component-row" data-testid={`component-${item.id}`}>
    <div className="component-thumb"><ComponentImage item={item}/></div>
    <div className="component-details">
      <div className="component-title"><strong>{item.model}</strong><span>{item.manufacturer}</span></div>
      <div className="component-spec-line">{item.key_specs.length ? item.key_specs.map((spec) => spec.value).join(' · ') : item.category}</div>
      <div className="component-meta"><span>{item.geometry_fidelity.replaceAll('_', ' ')}</span>{item.fit_score != null && <span>{item.fit_score}% fit</span>}<span>{item.price ? `${item.price.currency === 'USD' ? '$' : ''}${item.price.amount.toFixed(2)}` : 'price n/a'}</span></div>
    </div>
    <button className="insert-button" disabled={inserting} onClick={() => onInsert(item.id)}><Plus size={13}/>{inserting ? 'Inserting' : item.added ? 'Insert another' : 'Insert'}</button>
  </div>;
}

function PropertiesPanel({ project, selectedPart, onProject, onRefresh, onOpenCode, onDelete }: { project: ProjectPayload | null; selectedPart: ProjectPayload['parts'][number] | null; onProject: (project: ProjectPayload) => void; onRefresh: () => void; onOpenCode: () => void; onDelete: () => void }) {
  const active = project?.branches.find((branch) => branch.active) ?? null;
  return <div className="properties-panel">
    <div className="panel-title"><div><strong>{selectedPart ? 'Object properties' : 'Design properties'}</strong><small>{selectedPart ? selectedPart.role : project?.active_branch ?? 'main'}</small></div></div>
    {selectedPart ? <>
      <div className="property-section"><div className="property-section-title">IDENTITY</div><dl className="property-grid"><dt>Name</dt><dd>{selectedPart.name}</dd><dt>Role</dt><dd>{selectedPart.role}</dd><dt>Source</dt><dd>{selectedPart.component_ref ?? 'Fabricated / imported'}</dd></dl></div>
      <div className="property-section"><div className="property-section-title">PHYSICAL</div><dl className="property-grid"><dt>Mass</dt><dd>{selectedPart.mass_g} g</dd><dt>Material</dt><dd>{selectedPart.material}</dd><dt>Geometry</dt><dd>{selectedPart.geometry_fidelity?.replaceAll('_', ' ') ?? 'CAD geometry'}</dd></dl></div>
      {!selectedPart.component_ref && <div className="property-section property-feature-history"><div className="property-section-title">PARAMETRIC CAD</div><FeatureHistoryPanel objectId={selectedPart.id} onChanged={onRefresh}/></div>}
      {selectedPart.programmable_workspace_id && <div className="property-section"><button className="wide-action" onClick={onOpenCode}><Code2 size={13}/>Open embedded code</button></div>}
      <div className="property-section"><button className="wide-action danger-action" data-testid="delete-selected" onClick={onDelete}><Trash2 size={13}/>Delete object</button></div>
    </> : <div className="property-section"><div className="property-section-title">DOCUMENT</div><dl className="property-grid"><dt>Name</dt><dd>{project?.name ?? 'Untitled Design'}</dd><dt>Branch</dt><dd>{project?.active_branch ?? 'main'}</dd><dt>Objects</dt><dd>{project?.parts.length ?? 0}</dd><dt>BOM lines</dt><dd>{project?.bom?.length ?? 0}</dd><dt>Connections</dt><dd>{project?.connections?.length ?? 0}</dd></dl></div>}
    <div className="property-section"><div className="property-section-title">DESIGN STATE</div><dl className="property-grid"><dt>Status</dt><dd>{active?.status.replace('_', ' ') ?? 'unverified'}</dd><dt>Physical</dt><dd>{active?.physical_verified ? 'Verified by evidence' : 'Not verified'}</dd><dt>History</dt><dd>{project?.history.length ?? 0} operations</dd></dl></div>
    <DesignLineagePanel project={project} onProject={onProject}/>
  </div>;
}

function BottomContent({ tab, project, workspaceId, runtime, engineeringJobs, selectedObjectId, onAskCopilot, onCancelJob }: {
  tab: BottomTab; project: ProjectPayload | null; workspaceId: string | null; runtime: RuntimePayload | null; engineeringJobs: JobPayload[]; selectedObjectId: string | null;
  onAskCopilot: (workspaceId: string, path: string) => void;
  onCancelJob: (job: JobPayload) => void;
}) {
  if (tab === 'code') return workspaceId ? <CodeWorkspace workspaceId={workspaceId} onAskCopilot={onAskCopilot}/> : <div className="dock-empty"><Code2 size={18}/><span>Select a programmable component and choose “Open embedded code.”</span></div>;
  if (tab === 'history') return <div className="history-panel">{project?.history.length ? project.history.slice().reverse().map((item, index) => <div className="history-row" key={`${item.time}-${index}`}><span>{item.branch}</span><strong>{item.message}</strong><small>{item.actor}</small></div>) : <div className="dock-empty"><History size={18}/><span>No design operations yet.</span></div>}</div>;
  if (tab === 'simulations') return engineeringJobs.length ? <div className="history-panel" data-testid="simulation-job-status">
    {engineeringJobs.slice(0, 12).map((job) => <div className="history-row" key={job.id}>
      <span>{engineeringJobLabel(job)}</span>
      <strong>{jobStateLabels[job.state]}{job.progress != null ? ` · ${Math.round(Math.max(0, Math.min(1, job.progress)) * 100)}%` : ''}</strong>
      <small>{job.message || job.branch || 'Forge Engine job'}</small>
      {!terminalStates.has(job.state) && <button className="editor-action" onClick={() => onCancelJob(job)}>Cancel</button>}
    </div>)}
  </div> : <div className="dock-empty" data-testid="simulation-job-status"><Activity size={18}/><strong>Simulation & campaign jobs</strong><span>Run Dynamics or a variant campaign after geometry is present.</span></div>;
  return <WorldSystemPanel selectedObjectId={selectedObjectId}/>;
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
  const [componentCatalogRevision, setComponentCatalogRevision] = useState(0);
  const [visibleComponentCount, setVisibleComponentCount] = useState(80);
  const [registryStats, setRegistryStats] = useState<RegistryStatsPayload | null>(null);
  const [insertingComponentId, setInsertingComponentId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [openWorkspaceId, setOpenWorkspaceId] = useState<string | null>(null);
  const [sceneReady, setSceneReady] = useState(false);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [jobsById, setJobsById] = useState<Record<string, JobPayload>>({});
  const [activeAgentJobId, setActiveAgentJobId] = useState<string | null>(null);
  const [streamText, setStreamText] = useState('');
  const [submittingAgent, setSubmittingAgent] = useState(false);
  const [agentSubmitError, setAgentSubmitError] = useState<string | null>(null);
  const [agentStartedAt, setAgentStartedAt] = useState<number | null>(null);
  const [agentElapsed, setAgentElapsed] = useState(0);
  const [optimisticHiddenIds, setOptimisticHiddenIds] = useState<ReadonlySet<string>>(() => new Set());
  const [chat, setChat] = useState<ChatEntry[]>([{ role: 'agent', text: 'Ask me to build, modify, or inspect the active design. Press Enter to send; Shift+Enter adds a new line.' }]);
  const [newBusy, setNewBusy] = useState(false);
  const handledJobs = useRef(new Set<string>());
  const activeAgentJobIdRef = useRef<string | null>(null);
  const componentSearchGeneration = useRef(0);
  const conversationRef = useRef<HTMLElement | null>(null);
  const stepInput = useRef<HTMLInputElement | null>(null);
  const focadInput = useRef<HTMLInputElement | null>(null);

  const selectedPart = useMemo(() => project?.parts.find((part) => part.id === selectedId) ?? null, [project, selectedId]);
  const workspaceId = openWorkspaceId;
  const activeAgentJob = activeAgentJobId ? jobsById[activeAgentJobId] ?? null : null;
  const engineeringJobs = useMemo(() => Object.values(jobsById)
    .filter((job) => job.kind !== 'agent')
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)), [jobsById]);
  const engineeringWorkingJob = engineeringJobs.find((job) => !terminalStates.has(job.state)) ?? null;
  const latestCampaignJob = engineeringJobs.find((job) => job.kind === 'campaign') ?? null;
  const statusJob = activeAgentJob;
  const copilotBusy = submittingAgent || Boolean(activeAgentJob && !terminalStates.has(activeAgentJob.state));
  const hasGeometry = Boolean(project?.parts.length);
  const sceneRevision = project ? `${project.active_branch}:${project.revision}` : 'loading';
  const visibleComponents = useMemo(() => components.slice(0, visibleComponentCount), [components, visibleComponentCount]);
  const statusWorking = submittingAgent || Boolean(statusJob && !terminalStates.has(statusJob.state));
  const statusProgress = submittingAgent ? 0.04 : Math.max(0, Math.min(1, statusJob?.progress ?? 0));
  const globalWorking = statusWorking || Boolean(engineeringWorkingJob);
  const aiUnavailable = runtime?.ollama === 'offline' || runtime?.ollama === 'failed';
  const modelHealthLabel = runtime?.ollama === 'ready' ? 'AI ready' : runtime?.ollama === 'warming' ? 'AI warming' : runtime?.ollama === 'checking' || !runtime ? 'Checking AI' : 'AI unavailable';
  const agentTone = agentSubmitError || statusJob?.state === 'failed' ? 'error' : statusJob?.state === 'completed' ? 'done' : statusWorking ? 'working' : 'idle';
  const agentTitle = agentSubmitError ? 'Could not start task' : submittingAgent ? 'Sending request' : statusJob ? ({ queued: 'Request queued', warming: 'Starting local AI', planning: 'Planning the design', applying: 'Applying design changes', analyzing: 'Analyzing the design', verifying: 'Verifying the result', completed: 'Task complete', failed: 'Task failed', cancelled: 'Task cancelled' } as Record<JobPayload['state'], string>)[statusJob.state] : aiUnavailable ? 'Local AI unavailable' : 'Ready for a task';
  const agentDetail = agentSubmitError ?? (submittingAgent ? 'Creating an engineering job and handing it to Forge Engine…' : statusJob?.message ?? (aiUnavailable ? `Forge Engine is ready, but ${runtime?.configured_model ?? 'the configured model'} is not currently available in Ollama. Start Ollama and install/start that model, then retry.` : 'Ready to inspect or modify the active design.'));

  useEffect(() => {
    if (!actionError) return;
    const timer = window.setTimeout(() => setActionError(null), 5000);
    return () => window.clearTimeout(timer);
  }, [actionError]);

  useEffect(() => {
    if (!openWorkspaceId) return;
    if (!project?.parts.some((part) => part.programmable_workspace_id === openWorkspaceId)) setOpenWorkspaceId(null);
  }, [openWorkspaceId, project]);

  const refreshProject = useCallback(async () => {
    const nextProject = await fetchProject();
    setProject(nextProject);
    setSelectedId((current) => current && nextProject.parts.some((part) => part.id === current) ? current : null);
  }, []);

  const acceptJobSnapshot = useCallback((job: JobPayload) => {
    setJobsById((current) => ({ ...current, [job.id]: job }));
    if (job.kind === 'agent') {
      setActiveAgentJobId(job.id);
      if (!terminalStates.has(job.state)) activeAgentJobIdRef.current = job.id;
      else if (activeAgentJobIdRef.current === job.id) activeAgentJobIdRef.current = null;
      setSubmittingAgent(false);
      setAgentSubmitError(null);
    }
    if (!terminalStates.has(job.state) || handledJobs.current.has(job.id)) return;
    handledJobs.current.add(job.id);
    if (job.kind === 'agent') {
      if (job.state === 'completed') {
        const text = job.assistant_text.trim();
        if (text) setChat((items) => [...items, { role: 'agent', text }]);
      } else if (job.state === 'failed') {
        setChat((items) => [...items, { role: 'agent', text: `Engineering job failed: ${job.error?.message ?? job.message ?? 'Unknown local-engine error'}` }]);
      } else if (job.state === 'cancelled') {
        setChat((items) => [...items, { role: 'agent', text: 'Task cancelled.' }]);
      }
      setStreamText('');
    }
    void refreshProject();
  }, [refreshProject]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const tasks = [
        fetchRuntime().then((next) => { if (!cancelled) setRuntime(next); }),
        fetchProject().then((next) => { if (!cancelled) { setProject(next); setSelectedId(null); } }),
        fetchRegistryStats().then((next) => { if (!cancelled) setRegistryStats(next); }),
      ];
      const results = await Promise.allSettled(tasks);
      if (cancelled) return;
      const failure = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
      setStartupError(failure ? messageOf(failure.reason) : null);
    };
    void load();
    const runtimeTimer = window.setInterval(() => {
      void fetchRuntime().then((next) => { setRuntime(next); setStartupError(null); }).catch((error) => setStartupError(messageOf(error)));
    }, 3000);
    let stop: (() => void) | undefined;
    void subscribeEngineEvents((event) => {
      if (event.type === 'job.updated') acceptJobSnapshot(event.job);
      else if (event.type === 'job.token' && event.job_id === activeAgentJobIdRef.current) setStreamText((value) => value + event.token);
      else if (event.type === 'project.updated') {
        setProject(event.project);
        setSelectedId((current) => current && event.project.parts.some((part) => part.id === current) ? current : null);
      }
    }).then((cleanup) => { stop = cleanup; }).catch(() => undefined);
    return () => { cancelled = true; window.clearInterval(runtimeTimer); stop?.(); };
  }, [acceptJobSnapshot]);

  useEffect(() => {
    const ids = Object.values(jobsById).filter((job) => !terminalStates.has(job.state)).map((job) => job.id);
    if (!ids.length) return;
    const poll = window.setInterval(() => {
      ids.forEach((jobId) => void fetchJob(jobId).then(acceptJobSnapshot).catch(() => undefined));
    }, 900);
    return () => window.clearInterval(poll);
  }, [jobsById, acceptJobSnapshot]);

  useEffect(() => {
    if (!agentStartedAt || !statusWorking) return;
    const update = () => setAgentElapsed(Math.max(0, Math.floor((Date.now() - agentStartedAt) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [agentStartedAt, statusWorking]);

  useEffect(() => {
    setVisibleComponentCount(80);
    const generation = ++componentSearchGeneration.current;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const voltage = componentVoltage.trim() ? Number(componentVoltage) : undefined;
      void fetchComponents(componentQuery, componentCategory || undefined, Number.isFinite(voltage) ? voltage : undefined)
        .then((result) => { if (!cancelled && generation === componentSearchGeneration.current) setComponents(result.items); })
        .catch((error) => { if (!cancelled && generation === componentSearchGeneration.current) setActionError(messageOf(error)); });
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [componentQuery, componentCategory, componentVoltage, componentCatalogRevision]);

  useEffect(() => setSceneReady(false), [sceneRevision]);
  useEffect(() => { const node = conversationRef.current; if (node) node.scrollTop = node.scrollHeight; }, [chat, streamText, activeAgentJob?.state, submittingAgent]);

  const deleteSelected = useCallback(async () => {
    const id = selectedId;
    if (!id || !project) { setActionError('Select an object to delete.'); return; }
    const previous = project;
    setSelectedId(null);
    setProject((current) => current ? { ...current, parts: current.parts.filter((part) => part.id !== id) } : current);
    setOptimisticHiddenIds((current) => new Set([...current, id]));
    try {
      const result = await deleteObject(id);
      setProject(result.project);
      window.dispatchEvent(new CustomEvent('forgecad:notice', { detail: 'Object deleted · Ctrl/Cmd+Z to undo' }));
    } catch (error) {
      setProject(previous);
      setOptimisticHiddenIds((current) => { const next = new Set(current); next.delete(id); return next; });
      setSelectedId(id);
      setActionError(messageOf(error));
    }
  }, [project, selectedId]);

  useEffect(() => {
    const deleteHandler = () => void deleteSelected();
    const deselectHandler = () => setSelectedId(null);
    window.addEventListener('forgecad:delete-selected', deleteHandler);
    window.addEventListener('forgecad:deselect', deselectHandler);
    return () => {
      window.removeEventListener('forgecad:delete-selected', deleteHandler);
      window.removeEventListener('forgecad:deselect', deselectHandler);
    };
  }, [deleteSelected]);

  const refreshRuntimeNow = useCallback(async () => {
    try { setRuntime(await fetchRuntime()); setStartupError(null); setAgentSubmitError(null); }
    catch (error) { setStartupError(messageOf(error)); }
  }, []);

  const runAgent = useCallback(async (text: string, edits: boolean) => {
    const trimmed = text.trim();
    if (!trimmed || copilotBusy) return;
    if (aiUnavailable) {
      setBrowserTab('copilot');
      setAgentSubmitError(`Local AI is unavailable. Start Ollama and make ${runtime?.configured_model ?? 'the configured model'} available, then retry. Your draft has been kept.`);
      return;
    }
    setStreamText('');
    setAgentSubmitError(null);
    setAgentStartedAt(Date.now());
    setAgentElapsed(0);
    setSubmittingAgent(true);
    try {
      const job = await createJob({ kind: 'agent', text: trimmed, selected_object_id: selectedId, apply_edits: edits, ...(project?.active_branch ? { branch: project.active_branch } : {}) });
      activeAgentJobIdRef.current = job.id;
      setChat((items) => [...items, { role: 'user', text: trimmed }]);
      setMessage('');
      acceptJobSnapshot(job);
    } catch (error) {
      const detail = messageOf(error);
      setAgentSubmitError(detail);
      setAgentStartedAt(null);
    } finally { setSubmittingAgent(false); }
  }, [aiUnavailable, acceptJobSnapshot, copilotBusy, project?.active_branch, runtime?.configured_model, selectedId]);

  async function cancelJob(job: JobPayload) {
    if (terminalStates.has(job.state)) return;
    try { acceptJobSnapshot(await engineFetch<JobPayload>(`/v2/jobs/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' })); }
    catch (error) {
      if (job.kind === 'agent') setAgentSubmitError(messageOf(error));
      else setActionError(messageOf(error));
    }
  }
  async function switchBranch(name: string) {
    if (name === project?.active_branch) return;
    try {
      setSceneReady(false); setSelectedId(null); setOpenWorkspaceId(null); setProject(await activateBranch(name));
      setComponentCatalogRevision((revision) => revision + 1); setExplode(0); setOptimisticHiddenIds(new Set()); setActionError(null);
    } catch (error) { setActionError(messageOf(error)); }
  }
  async function insertLibraryComponent(id: string) {
    setInsertingComponentId(id);
    try {
      setSceneReady(false);
      const result = await addComponent(id);
      setProject(result.project);
      setComponents((items) => items.map((item) => item.id === id ? { ...item, added: true, instance_id: result.component.instance_id ?? item.instance_id ?? null } : item));
      setSelectedId(result.component.instance_id ?? null); setRightTab('properties'); setComponentCatalogRevision((revision) => revision + 1); setActionError(null);
    } catch (error) { setActionError(messageOf(error)); }
    finally { setInsertingComponentId(null); }
  }
  async function createBlankProject() {
    if (newBusy) return;
    if (project?.parts.length && !window.confirm('Create a new blank design? Export the current design as .focad first if you want a portable copy.')) return;
    try {
      setNewBusy(true); setSceneReady(false); setSelectedId(null); setOpenWorkspaceId(null); setProject(await newProject());
      setComponentCatalogRevision((revision) => revision + 1); setExplode(0); setBottomTab(null); setRightTab('components'); setOptimisticHiddenIds(new Set()); setActionError(null);
    } catch (error) { setActionError(messageOf(error)); }
    finally { setNewBusy(false); }
  }
  async function importFocad(file?: File) {
    if (!file) return;
    try {
      setSceneReady(false); setSelectedId(null); setOpenWorkspaceId(null);
      const result = await importProjectBundle(file);
      setProject(result.project); setComponentCatalogRevision((revision) => revision + 1); setExplode(0); setBottomTab(null); setRightTab('properties');
      setRegistryStats(await fetchRegistryStats()); setOptimisticHiddenIds(new Set()); setActionError(null);
    } catch (error) { setActionError(messageOf(error)); }
    finally { if (focadInput.current) focadInput.current.value = ''; }
  }
  async function exportFocad() {
    try {
      const blob = await downloadProjectBundle();
      const safeName = (project?.name || 'ForgeCAD-Design').replace(/[^a-z0-9._-]+/gi, '-').replace(/^-+|-+$/g, '') || 'ForgeCAD-Design';
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${safeName}.focad`; document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); setActionError(null);
    } catch (error) { setActionError(messageOf(error)); }
  }
  async function importStep(file?: File) {
    if (!file) return;
    try {
      setSceneReady(false); const result = await importStepFile(file); setProject(result.project); const importedId = String(result.object.id ?? ''); if (importedId) setSelectedId(importedId); setRightTab('properties'); setActionError(null);
    } catch (error) { setActionError(messageOf(error)); }
    finally { if (stepInput.current) stepInput.current.value = ''; }
  }
  async function undoDesign() {
    try { const result = await undoHistory(); setProject(result.project); setSelectedId(null); setOptimisticHiddenIds(new Set()); setActionError(null); }
    catch (error) { setActionError(messageOf(error)); }
  }
  async function redoDesign() {
    try { const result = await redoHistory(); setProject(result.project); setSelectedId(null); setOptimisticHiddenIds(new Set()); setActionError(null); }
    catch (error) { setActionError(messageOf(error)); }
  }
  async function startSimulation() {
    if (!hasGeometry) return;
    setBottomTab('simulations');
    try { acceptJobSnapshot(await createJob({ kind: 'simulation', selected_object_id: selectedId, ...(project?.active_branch ? { branch: project.active_branch } : {}) })); }
    catch (error) { setActionError(messageOf(error)); }
  }
  async function startCampaign() {
    if (!hasGeometry) return;
    try { acceptJobSnapshot(await createJob({ kind: 'campaign', selected_object_id: selectedId, ...(project?.active_branch ? { branch: project.active_branch } : {}) })); setBottomTab('simulations'); }
    catch (error) { setActionError(messageOf(error)); }
  }
  function openCodeForSelected() {
    if (!selectedPart?.programmable_workspace_id) return;
    setOpenWorkspaceId(selectedPart.programmable_workspace_id);
    setBottomTab('code');
  }
  function askCopilotAboutCode(workspace: string, path: string) {
    setBrowserTab('copilot');
    setMessage(`Inspect ${path} in workspace ${workspace}. Explain any problems you see and propose the safest concrete improvement. Do not change the design unless I ask you to.`);
    window.setTimeout(() => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Copilot request"]')?.focus(), 0);
  }

  return <main className="cad-app">
    {actionError && <div className="shortcut-toast action-toast" role="alert"><CircleAlert size={13}/>{actionError}</div>}
    <header className="app-bar">
      <div className="wordmark"><span className="wordmark-icon">F</span><strong>ForgeCAD</strong></div>
      <div className="doc-tab"><FileText size={13}/><span>{project?.name ?? 'Opening…'}</span><small>{project?.active_branch ?? ''}</small></div>
      <div className="app-bar-spacer"/>
      {globalWorking && <button className="agent-global-status" data-testid="agent-global-status" onClick={() => { if (statusWorking) setBrowserTab('copilot'); else setBottomTab('simulations'); }} title={statusWorking ? 'Open Copilot activity' : 'Open engineering job activity'}><Activity size={12} className="agent-spin"/>{statusWorking ? `Agent working · ${agentTitle}` : engineeringWorkingJob ? `${engineeringJobLabel(engineeringWorkingJob)} · ${jobStateLabels[engineeringWorkingJob.state]}` : 'Engineering job running'}</button>}
      <RuntimeStatus runtime={runtime} error={startupError}/>
      <button className="toolbar-button" onClick={() => void createBlankProject()} disabled={newBusy}><Plus size={14}/>New</button>
      <button className="toolbar-button" data-testid="open-focad" onClick={() => focadInput.current?.click()} title="Open a portable ForgeCAD design"><Upload size={14}/>Open .focad</button>
      <button className="toolbar-button" data-testid="export-focad" onClick={() => void exportFocad()} title="Export this design for ForgeCAD or ChatGPT"><Download size={14}/>Export .focad</button>
      <button className="icon-button" title="Keyboard shortcuts" aria-label="Keyboard shortcuts" onClick={() => window.dispatchEvent(new Event('forgecad:show-shortcuts'))}><Keyboard size={15}/></button>
      <input ref={focadInput} hidden type="file" accept=".focad,.forgecad.zip,application/vnd.forgecad.project+zip,application/zip" onChange={(event) => void importFocad(event.target.files?.[0])}/>
      <input ref={stepInput} hidden type="file" accept=".step,.stp" onChange={(event) => void importStep(event.target.files?.[0])}/>
    </header>

    <div className={`workbench ${browserTab === 'copilot' ? 'copilot-open' : ''}`}>
      <aside className="left-panel">
        <div className="panel-tabs compact"><button className={browserTab === 'model' ? 'active' : ''} onClick={() => setBrowserTab('model')}><Layers size={13}/>Model</button><button className={browserTab === 'copilot' ? 'active' : ''} onClick={() => setBrowserTab('copilot')}><MessageSquare size={13}/>Copilot</button></div>
        {browserTab === 'model' ? <div className="browser-content">
          <section className="browser-section"><div className="section-heading"><span>DESIGN</span><MoreHorizontal size={13}/></div><div className="doc-summary"><strong>{project?.name ?? 'Untitled Design'}</strong><small>{project?.parts.length ?? 0} objects · {project?.bom?.length ?? 0} BOM lines</small></div></section>
          <section className="browser-section grow"><div className="section-heading"><span>OBJECTS</span><span>{project?.parts.length ?? 0}</span></div><div className="browser-list">
            {project?.parts.length ? project.parts.map((part) => <button key={part.id} data-object-id={part.id} className={`browser-row object-row ${selectedId === part.id ? 'selected' : ''}`} onClick={() => setSelectedId(part.id)}><Box size={13}/><span className="browser-row-main"><strong>{part.name}</strong><small>{part.role}</small></span>{part.programmable_workspace_id && <Code2 size={12}/>}<ChevronRight size={12}/></button>) : <div className="browser-empty">No geometry</div>}
          </div></section>
          <section className="browser-section branches-section"><div className="section-heading"><span>BRANCHES</span><button className="section-link" data-testid="manage-design-lineage" onClick={() => setRightTab('properties')}>Manage</button></div><div className="browser-list">{project?.branches.map((branch) => <BranchRow key={branch.name} branch={branch} onActivate={(name) => void switchBranch(name)}/>)}</div></section>
        </div> : <div className="copilot-pane">
          <div className="copilot-header"><Bot size={16}/><div className="copilot-header-main"><strong>Engineering Copilot</strong><small>{runtime?.configured_model ?? 'local model'} · runs locally through Forge Engine</small></div><div className={`copilot-health ${runtime?.ollama ?? 'checking'}`} title={`Ollama: ${runtime?.ollama ?? 'checking'}`}><span className="copilot-health-dot"/>{modelHealthLabel}</div></div>
          <div className={`agent-status-card ${agentTone}`} data-testid="agent-status" aria-live="polite">
            <div className="agent-status-row"><span className="agent-status-icon">{statusWorking ? <Activity size={14} className="agent-spin"/> : agentTone === 'done' ? <Check size={14}/> : agentTone === 'error' ? <CircleAlert size={14}/> : <Bot size={14}/>}</span><div className="agent-status-copy"><strong>{agentTitle}</strong><small>{agentDetail}</small></div>{(agentStartedAt || statusWorking) && <span className="agent-elapsed">{formatElapsed(agentElapsed)}</span>}</div>
            {statusWorking && <div className="agent-progress-track" title={`${Math.round(statusProgress * 100)}%`}><span style={{ width: `${Math.max(4, Math.round(statusProgress * 100))}%` }}/></div>}
            {(submittingAgent || statusJob) && <div className="agent-status-meta"><span>{submittingAgent ? 'Submitting' : statusJob ? jobStateLabels[statusJob.state] : 'Working'}</span><span>{Math.round(statusProgress * 100)}%</span><span>{statusJob?.branch ?? project?.active_branch ?? 'main'}</span></div>}
            <div className="agent-status-actions">{statusWorking && activeAgentJob && <button className="agent-cancel" onClick={() => void cancelJob(activeAgentJob)}><X size={11}/>Cancel task</button>}{aiUnavailable && !statusWorking && <button className="agent-cancel" onClick={() => void refreshRuntimeNow()}>Retry AI status</button>}</div>
          </div>
          <section className="conversation" ref={conversationRef} data-testid="conversation">
            {chat.map((entry, index) => <div className={`message ${entry.role}`} key={`${index}-${entry.text.slice(0, 18)}`}><span className="message-author">{entry.role === 'agent' ? 'ForgeCAD' : 'You'}</span>{entry.role === 'agent' ? <MarkdownMessage text={entry.text}/> : <p>{entry.text}</p>}</div>)}
            {statusWorking && (submittingAgent || statusJob) && <div className="message agent live" data-testid="agent-live-message"><span className="message-author">ForgeCAD · live</span><div className="agent-live-line"><Activity size={12} className="agent-spin"/><strong>{agentTitle}</strong></div>{streamText ? <MarkdownMessage text={streamText}/> : <p className="agent-live-detail">{agentDetail}</p>}</div>}
          </section>
          <div className="composer" data-testid="composer">
            <textarea aria-label="Copilot request" value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !(event.nativeEvent as KeyboardEvent).isComposing) { event.preventDefault(); void runAgent(message, applyEdits); }
            }} placeholder={copilotBusy ? 'ForgeCAD is working. You can draft your next request here…' : aiUnavailable ? 'Local AI is unavailable. You can keep a draft here while you start Ollama…' : 'Describe what you want to build, change, or inspect…'}/>
            <div className="composer-permission-note">{applyEdits ? 'ForgeCAD may add, move, connect, and edit design objects for this task.' : 'Analysis only — ForgeCAD will not change the design.'}</div>
            <div className="composer-footer"><label className="edit-permission" title="Turn this off when you only want analysis or an answer"><input type="checkbox" checked={applyEdits} onChange={(event) => setApplyEdits(event.target.checked)}/>Modify design</label><div className="composer-actions"><span className="composer-shortcut">{copilotBusy ? 'One task at a time' : 'Enter sends · Shift+Enter newline'}</span><button className="send-button" data-testid="send-button" disabled={copilotBusy || !message.trim()} onClick={() => void runAgent(message, applyEdits)}>{copilotBusy ? <Activity size={13} className="agent-spin"/> : <Send size={13}/>}<span>{copilotBusy ? 'Working' : 'Send'}</span></button></div></div>
          </div>
        </div>}
      </aside>

      <section className={`center-column ${bottomTab ? 'dock-open' : ''}`}>
        <div className="document-toolbar">
          <div className="tool-group"><button className="icon-button" title="Undo" onClick={() => void undoDesign()}><Undo2 size={15}/></button><button className="icon-button" title="Redo" onClick={() => void redoDesign()}><Redo2 size={15}/></button></div><div className="tool-divider"/>
          <label className="branch-picker"><GitBranch size={13}/><select aria-label="Active design branch" value={project?.active_branch ?? ''} onChange={(event) => void switchBranch(event.target.value)}>{project?.branches.map((branch) => <option key={branch.name} value={branch.name}>{branch.name}</option>)}</select><ChevronDown size={12}/></label><div className="tool-divider"/>
          <button className="toolbar-button" onClick={() => setRightTab('components')}><Package size={14}/>Insert component</button><button className="toolbar-button" onClick={() => stepInput.current?.click()}><FolderOpen size={14}/>Import STEP</button><div className="document-toolbar-spacer"/>
          <button className="toolbar-button" disabled={!hasGeometry} onClick={() => setBottomTab(bottomTab === 'history' ? null : 'history')}><History size={14}/>History</button><button className="toolbar-button" data-testid="toolbar-manufacture" disabled={!hasGeometry} onClick={() => setRightTab('manufacture')}><Printer size={14}/>Manufacture</button><button className="primary-action" disabled={!hasGeometry} onClick={() => void startSimulation()}><Play size={14}/>Dynamics</button>
        </div>
        <div className="viewport-wrap">
          <Viewport explode={explode} onExplode={setExplode} onSelectionChange={setSelectedId} onReady={() => setSceneReady(true)} onLoading={() => setSceneReady(false)} onError={(error) => { setSceneReady(false); setStartupError(error.message); }} sceneRevision={sceneRevision} selectedId={selectedId} empty={!hasGeometry} optimisticHiddenIds={optimisticHiddenIds}/>
          {!hasGeometry && sceneReady && <div className="empty-canvas"><Box size={24}/><strong>No geometry</strong><span>Insert a component, import STEP, or open a .focad design.</span><div><button onClick={() => setRightTab('components')}><Package size={13}/>Insert component</button><button onClick={() => focadInput.current?.click()}><Upload size={13}/>Open .focad</button><button onClick={() => stepInput.current?.click()}><FolderOpen size={13}/>Import STEP</button></div></div>}
          {selectedPart && <div className="selection-chip"><span><strong>{selectedPart.name}</strong><small>{selectedPart.role}</small></span><button className="selection-delete" title="Delete selected object" aria-label="Delete selected object" onClick={() => void deleteSelected()}><Trash2 size={12}/></button><button title="Deselect" aria-label="Deselect object" onClick={() => setSelectedId(null)}><X size={12}/></button></div>}
          <div className={`scene-health ${sceneReady ? 'ready' : ''}`} data-testid="scene-health">{sceneReady ? '3D READY' : 'STARTING 3D'}</div>
        </div>
        <div className="bottom-bar">
          <button data-testid="tab-history" className={bottomTab === 'history' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'history' ? null : 'history')}><History size={12}/>History</button>
          <button data-testid="tab-code" className={bottomTab === 'code' ? 'active' : ''} onClick={() => { if (bottomTab === 'code') setBottomTab(null); else { if (!openWorkspaceId && selectedPart?.programmable_workspace_id) setOpenWorkspaceId(selectedPart.programmable_workspace_id); setBottomTab('code'); } }}><Code2 size={12}/>Code</button>
          <button data-testid="tab-simulations" className={bottomTab === 'simulations' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'simulations' ? null : 'simulations')}><Activity size={12}/>Simulation</button>
          <button data-testid="tab-system" className={bottomTab === 'system' ? 'active' : ''} onClick={() => setBottomTab(bottomTab === 'system' ? null : 'system')}><Settings size={12}/>System</button>
          <div className="bottom-spacer"/><span>{project?.parts.length ?? 0} objects</span><span>mm</span><span>Z up</span>
        </div>
        {bottomTab && <div className="bottom-dock"><BottomContent tab={bottomTab} project={project} workspaceId={workspaceId} runtime={runtime} engineeringJobs={engineeringJobs} selectedObjectId={selectedId} onAskCopilot={askCopilotAboutCode} onCancelJob={(job) => void cancelJob(job)}/></div>}
      </section>

      <aside className="right-panel">
        <div className="panel-tabs right-tabs"><button className={rightTab === 'properties' ? 'active' : ''} onClick={() => setRightTab('properties')}>Properties</button><button className={rightTab === 'components' ? 'active' : ''} onClick={() => setRightTab('components')}>Components</button><button className={rightTab === 'analysis' ? 'active' : ''} onClick={() => setRightTab('analysis')}>Analyze</button><button data-testid="tab-manufacture" className={rightTab === 'manufacture' ? 'active' : ''} onClick={() => setRightTab('manufacture')}>Manufacture</button></div>
        {rightTab === 'components' ? <div className="component-panel">
          <div className="panel-title"><div><strong>Component library</strong><small>{registryStats?.total ?? '…'} catalog parts</small></div></div>
          <div className="search-control"><Search size={14}/><input aria-label="Search component library" value={componentQuery} onChange={(event) => setComponentQuery(event.target.value)} placeholder="Search manufacturer, model, category…"/></div>
          <div className="component-filters"><select aria-label="Component category" value={componentCategory} onChange={(event) => setComponentCategory(event.target.value)}><option value="">All categories</option>{registryStats?.categories.map((category) => <option value={category} key={category}>{category}</option>)}</select><input aria-label="Component voltage" value={componentVoltage} onChange={(event) => setComponentVoltage(event.target.value)} placeholder="Voltage" inputMode="decimal"/></div>
          <div className="result-count">{components.length} results</div><div className="component-results">{visibleComponents.map((item) => <ComponentRow key={item.id} item={item} inserting={insertingComponentId === item.id} onInsert={(id) => void insertLibraryComponent(id)}/>)}{visibleComponents.length < components.length && <button className="wide-action" onClick={() => setVisibleComponentCount((count) => Math.min(components.length, count + 80))}>Load 80 more</button>}</div>
        </div> : rightTab === 'properties' ? <PropertiesPanel project={project} selectedPart={selectedPart} onProject={setProject} onRefresh={() => void refreshProject()} onOpenCode={openCodeForSelected} onDelete={() => void deleteSelected()}/> : rightTab === 'manufacture' ? <ManufacturePanel project={project} selectedId={selectedId} onSelectPart={setSelectedId} onDraftRedesign={(part) => {
          setSelectedId(part.id); setBrowserTab('copilot'); const warningText = part.warnings.map((warning) => warning.message).join(' '); setMessage(`Redesign "${part.name}" so it can be manufactured reliably on my Bambu Lab P2S. Preserve its functional role and interfaces. ${warningText} If the part is too large, split it into printable bodies with alignment features and a mechanically sound joining strategy, then re-check the design against the P2S manufacturing constraints.`);
        }}/> : <EngineeringWorkbench mode="analysis" project={project} selectedId={selectedId} activeJob={latestCampaignJob} onProject={setProject} onStartSimulation={() => void startSimulation()} onStartCampaign={() => void startCampaign()} onJobStarted={acceptJobSnapshot}/>} 
      </aside>
    </div>
  </main>;
}
