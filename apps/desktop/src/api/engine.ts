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

export interface ProjectPayload {
  name: string;
  revision: string;
  active_branch: string;
  branches: BranchPayload[];
  parts: Array<{ id: string; name: string; role: string; mass_g: number; material: string; programmable_workspace_id?: string | null }>;
  history: Array<{ time: string; actor: string; message: string; branch: string }>;
  selected_part_id?: string | null;
}

export interface ComponentPayload {
  id: string;
  manufacturer: string;
  model: string;
  category: string;
  image?: { kind: string; uri: string; source?: string };
  key_specs: Array<{ label: string; value: string }>;
  price?: { amount: number; currency: string; supplier: string };
  fit_score?: number;
  fit_reason?: string;
  unknown_required_fields: string[];
  geometry_fidelity: string;
  added?: boolean;
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

export async function engineFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const connection = await engineConnection();
  const headers = new Headers(init.headers);
  headers.set('X-ForgeCAD-Session', connection.sessionToken);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${connection.baseUrl}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Forge Engine ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export const fetchRuntime = () => engineFetch<RuntimePayload>('/v2/runtime');
export const fetchProject = () => engineFetch<ProjectPayload>('/v2/project');
export const fetchComponents = (query = '') => engineFetch<{ items: ComponentPayload[] }>(`/v2/components?q=${encodeURIComponent(query)}`);
export const fetchWorkspace = (id: string) => engineFetch<WorkspacePayload>(`/v2/code/workspaces/${encodeURIComponent(id)}`);
export const fetchCodeFile = (workspaceId: string, path: string) => engineFetch<{ path: string; content: string }>(`/v2/code/workspaces/${encodeURIComponent(workspaceId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`);
export const saveCodeFile = (workspaceId: string, path: string, content: string) => engineFetch<{ path: string; content: string }>(`/v2/code/workspaces/${encodeURIComponent(workspaceId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`, { method: 'PUT', body: JSON.stringify({ content }) });

export function createJob(input: { kind: 'agent' | 'simulation' | 'campaign' | 'component-search' | 'deploy'; text?: string; branch?: string; selected_object_id?: string | null; apply_edits?: boolean; payload?: Record<string, unknown> }) {
  return engineFetch<JobPayload>('/v2/jobs', { method: 'POST', body: JSON.stringify(input) });
}

export async function subscribeEngineEvents(onEvent: (event: EngineEvent) => void): Promise<() => void> {
  const connection = await engineConnection();
  const wsBase = connection.baseUrl.replace(/^http/, 'ws');
  const socket = new WebSocket(`${wsBase}/v2/events?token=${encodeURIComponent(connection.sessionToken)}`);
  socket.addEventListener('message', (event) => {
    try { onEvent(JSON.parse(String(event.data)) as EngineEvent); } catch { /* ignore malformed local event */ }
  });
  const heartbeat = window.setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send('ping');
  }, 15_000);
  return () => {
    window.clearInterval(heartbeat);
    socket.close();
  };
}
