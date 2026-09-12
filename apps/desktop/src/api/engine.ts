export interface RuntimePayload {
  engine: 'starting' | 'ready' | 'degraded' | 'offline' | 'failed';
  scene: 'starting' | 'ready' | 'degraded' | 'offline' | 'failed';
  ollama: 'checking' | 'warming' | 'ready' | 'offline' | 'failed';
  configured_model: string;
  resolved_model?: string | null;
  api_version: string;
}

export interface BranchPayload {
  name: string;
  head_commit: string;
  parent_branch?: string | null;
  status: 'working' | 'not_working' | 'unverified';
  physical_verified: boolean;
  protected: boolean;
  commit_count: number;
  active: boolean;
}

export interface PartPayload {
  id: string;
  name: string;
  role: string;
  mass_g: number;
  material: string;
  programmable_workspace_id?: string | null;
  component_ref?: string | null;
  geometry_fidelity?: string;
}

export interface ProjectPayload {
  name: string;
  revision: string;
  active_branch: string;
  branches: BranchPayload[];
  parts: PartPayload[];
  history: Array<{ time: string; actor: string; message: string; branch: string }>;
  selected_part_id?: string | null;
  bom?: Array<Record<string, unknown>>;
  connections?: Array<Record<string, unknown>>;
  requirements?: Array<Record<string, unknown>>;
  metrics?: Record<string, unknown>;
}

export interface ComponentPayload {
  id: string;
  manufacturer: string;
  model: string;
  category: string;
  image?: { kind: string; uri: string; source?: string };
  key_specs: Array<{ label: string; value: string }>;
  price?: { amount: number; currency: string; supplier: string } | null;
  fit_score?: number;
  fit_reason?: string;
  unknown_required_fields: string[];
  geometry_fidelity: string;
  trust_score?: number;
  added?: boolean;
  instance_id?: string | null;
}

export interface RegistryStatsPayload {
  schema_version: number;
  total: number;
  builtin: number;
  custom: number;
  categories: string[];
  geometry_fidelity: Record<string, number>;
  provenance: Record<string, number>;
}

export interface ValidationPayload {
  ok: boolean;
  counts: { error: number; warning: number; info: number };
  risks: Array<{ severity: 'error' | 'warning' | 'info'; code?: string; message: string; [key: string]: unknown }>;
  requirements?: Array<Record<string, unknown>>;
  metrics?: Record<string, unknown>;
  assembly?: Record<string, unknown>;
}

export interface SceneMeshPayload {
  id: string;
  positions: number[][];
  triangles: number[][];
  triangle_colors?: string[];
  color?: string;
}

export interface ScenePayload {
  revision: string;
  branch: string;
  authoritative: boolean;
  parts: Array<{
    id: string;
    name: string;
    semantic_role: string;
    explode_vector: number[];
    base_transform: { position: number[]; rotation_deg: number[]; scale: number[] };
    programmable_workspace_id?: string | null;
    mesh: SceneMeshPayload;
  }>;
}

export interface WorkspacePayload {
  id: string;
  device_part_id: string;
  target: string;
  runtime: string;
  files: string[];
}

export interface JobPayload {
  id: string;
  kind: string;
  state: 'queued' | 'warming' | 'planning' | 'applying' | 'analyzing' | 'verifying' | 'completed' | 'failed' | 'cancelled';
  created_at: string;
  progress?: number | null;
  message?: string | null;
  branch?: string | null;
  selected_object_id?: string | null;
  assistant_text: string;
  result: Record<string, unknown>;
  error?: { code: string; message: string; recoverable?: boolean } | null;
}

export type EngineEvent =
  | { type: 'job.updated'; job: JobPayload }
  | { type: 'job.token'; job_id: string; token: string }
  | { type: 'project.updated'; project: ProjectPayload };

let cachedConnection: ForgeEngineConnection | null = null;
let projectRequest: Promise<ProjectPayload> | null = null;
let sceneRequest: Promise<ScenePayload> | null = null;

function invalidateProjectRequests() {
  projectRequest = null;
  sceneRequest = null;
}

export async function engineConnection(): Promise<ForgeEngineConnection> {
  if (cachedConnection) return cachedConnection;
  if (window.forgeDesktop?.getEngineConnection) {
    cachedConnection = await window.forgeDesktop.getEngineConnection();
  } else {
    const baseUrl = import.meta.env.VITE_FORGECAD_ENGINE_URL as string | undefined;
    if (!baseUrl) throw new Error('ForgeCAD desktop bridge is unavailable');
    cachedConnection = {
      baseUrl,
      sessionToken: (import.meta.env.VITE_FORGECAD_ENGINE_TOKEN as string | undefined) ?? 'test-session',
      configuredModel: (import.meta.env.VITE_FORGECAD_MODEL as string | undefined) ?? 'qwen3:8b',
    };
  }
  return cachedConnection;
}

export async function engineRawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const connection = await engineConnection();
  const headers = new Headers(init.headers);
  headers.set('X-ForgeCAD-Session', connection.sessionToken);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${connection.baseUrl}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Forge Engine ${response.status}: ${detail}`);
  }
  return response;
}

export async function engineFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await engineRawFetch(path, init);
  return response.json() as Promise<T>;
}

export const fetchRuntime = () => engineFetch<RuntimePayload>('/v2/runtime');

export function fetchProject(): Promise<ProjectPayload> {
  if (projectRequest) return projectRequest;
  const request = engineFetch<ProjectPayload>('/v2/project');
  projectRequest = request;
  request.then(
    () => { if (projectRequest === request) projectRequest = null; },
    () => { if (projectRequest === request) projectRequest = null; },
  );
  return request;
}

export function fetchScene(): Promise<ScenePayload> {
  if (sceneRequest) return sceneRequest;
  const request = engineFetch<ScenePayload>('/v2/scene', { signal: AbortSignal.timeout(90_000) });
  sceneRequest = request;
  request.then(
    () => { if (sceneRequest === request) sceneRequest = null; },
    () => { if (sceneRequest === request) sceneRequest = null; },
  );
  return request;
}

export const fetchRegistryStats = () => engineFetch<RegistryStatsPayload>('/v2/component-registry/stats');
export const fetchValidation = () => engineFetch<ValidationPayload>('/v2/validation');
export const fetchComponents = (query = '', category?: string, voltage?: number) => {
  const params = new URLSearchParams({ q: query });
  if (category) params.set('category', category);
  if (voltage != null) params.set('voltage_v', String(voltage));
  return engineFetch<{ items: ComponentPayload[]; stats?: RegistryStatsPayload }>(`/v2/components?${params.toString()}`);
};
export const fetchWorkspace = (id: string) => engineFetch<WorkspacePayload>(`/v2/code/workspaces/${encodeURIComponent(id)}`);
export const fetchCodeFile = (workspaceId: string, path: string) => engineFetch<{ path: string; content: string }>(`/v2/code/workspaces/${encodeURIComponent(workspaceId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`);
export const saveCodeFile = (workspaceId: string, path: string, content: string) => engineFetch<{ path: string; content: string }>(`/v2/code/workspaces/${encodeURIComponent(workspaceId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`, { method: 'PUT', body: JSON.stringify({ content }) });
export const fetchJob = (id: string) => engineFetch<JobPayload>(`/v2/jobs/${encodeURIComponent(id)}`);

export async function activateBranch(name: string) {
  const result = await engineFetch<ProjectPayload>(`/v2/branches/${encodeURIComponent(name)}/activate`, { method: 'POST' });
  invalidateProjectRequests();
  return result;
}
export async function createBranch(name: string, reason = '') {
  const result = await engineFetch<ProjectPayload>('/v2/branches', { method: 'POST', body: JSON.stringify({ name, reason }) });
  invalidateProjectRequests();
  return result;
}
export const compareBranch = (name: string) => engineFetch<{ source: string; target: string; changes: Array<Record<string, unknown>>; count: number }>(`/v2/branches/${encodeURIComponent(name)}/compare`);
export async function setBranchStatus(name: string, status: BranchPayload['status'], note = '', physicalVerified = false) {
  const result = await engineFetch<{ branch: Record<string, unknown>; project: ProjectPayload }>(`/v2/branches/${encodeURIComponent(name)}/status`, { method: 'PUT', body: JSON.stringify({ status, note, physical_verified: physicalVerified }) });
  invalidateProjectRequests();
  return result;
}
export async function addComponent(id: string) {
  const result = await engineFetch<{ component: ComponentPayload; project: ProjectPayload }>(`/v2/components/${encodeURIComponent(id)}/add`, { method: 'POST' });
  invalidateProjectRequests();
  return result;
}
export async function executeOperation(op: string, args: Record<string, unknown>, reason = '') {
  const result = await engineFetch<{ operation: Record<string, unknown>; project: ProjectPayload }>('/v2/operations', { method: 'POST', body: JSON.stringify({ op, args, reason }) });
  invalidateProjectRequests();
  return result;
}
export async function newProject() {
  const result = await executeOperation('new_project', {}, 'Create blank design');
  return result.project;
}
export async function undoHistory() {
  const result = await engineFetch<{ ok: boolean; project: ProjectPayload }>('/v2/history/undo', { method: 'POST' });
  invalidateProjectRequests();
  return result;
}
export async function redoHistory() {
  const result = await engineFetch<{ ok: boolean; project: ProjectPayload }>('/v2/history/redo', { method: 'POST' });
  invalidateProjectRequests();
  return result;
}

export async function importStepFile(file: File) {
  const body = new FormData();
  body.set('file', file);
  const result = await engineFetch<{ object: Record<string, unknown>; project: ProjectPayload }>('/v2/import/step', { method: 'POST', body });
  invalidateProjectRequests();
  return result;
}

export async function importProjectBundle(file: File) {
  const body = new FormData();
  body.set('file', file);
  const result = await engineFetch<{ project: ProjectPayload }>('/v2/project/import', { method: 'POST', body });
  invalidateProjectRequests();
  return result;
}

export async function downloadProjectBundle(): Promise<Blob> {
  const response = await engineRawFetch('/v2/project/export');
  return response.blob();
}

export function createJob(input: { kind: 'agent' | 'simulation' | 'campaign' | 'component-search' | 'deploy'; text?: string; branch?: string; selected_object_id?: string | null; apply_edits?: boolean; payload?: Record<string, unknown> }) {
  return engineFetch<JobPayload>('/v2/jobs', { method: 'POST', body: JSON.stringify(input) });
}

export async function subscribeEngineEvents(onEvent: (event: EngineEvent) => void): Promise<() => void> {
  const connection = await engineConnection();
  const wsBase = connection.baseUrl.replace(/^http/, 'ws');
  const socket = new WebSocket(`${wsBase}/v2/events?token=${encodeURIComponent(connection.sessionToken)}`);
  socket.addEventListener('message', (event) => {
    try {
      const parsed = JSON.parse(String(event.data)) as EngineEvent;
      if (parsed.type === 'project.updated') invalidateProjectRequests();
      onEvent(parsed);
    } catch { /* ignore malformed local event */ }
  });
  const heartbeat = window.setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send('ping');
  }, 15_000);
  return () => {
    window.clearInterval(heartbeat);
    socket.close();
  };
}
