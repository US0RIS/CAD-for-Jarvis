export interface RuntimePayload {
  engine: 'starting' | 'ready' | 'degraded' | 'offline' | 'failed';
  scene: 'starting' | 'ready' | 'degraded' | 'offline' | 'failed';
  ollama: 'checking' | 'warming' | 'ready' | 'offline' | 'failed';
  configured_model: string;
  resolved_model?: string | null;
  api_version: string;
}

let cachedConnection: ForgeEngineConnection | null = null;

export async function engineConnection(): Promise<ForgeEngineConnection> {
  if (cachedConnection) return cachedConnection;
  cachedConnection = await window.forgeDesktop.getEngineConnection();
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

export function fetchRuntime(): Promise<RuntimePayload> {
  return engineFetch<RuntimePayload>('/v2/runtime');
}
