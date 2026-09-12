import { randomBytes } from 'node:crypto';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';

export interface EngineConnection { baseUrl: string; sessionToken: string; configuredModel: string; }
export interface EngineSupervisorOptions {
  serviceRoot: string;
  configuredModel: string;
  pythonExecutable?: string;
  engineExecutable?: string;
  startupTimeoutMs?: number;
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        server.close();
        reject(new Error('Could not allocate Forge Engine port'));
        return;
      }
      const port = address.port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function managedPython(serviceRoot: string): string | null {
  const candidate = process.platform === 'win32'
    ? path.join(serviceRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(serviceRoot, '.venv', 'bin', 'python');
  return existsSync(candidate) ? candidate : null;
}

export class EngineSupervisor {
  private process: ChildProcess | null = null;
  private connection: EngineConnection | null = null;
  private readonly logs: string[] = [];

  constructor(private readonly options: EngineSupervisorOptions) {}

  get currentConnection(): EngineConnection | null { return this.connection; }
  get logTail(): string[] { return this.logs.slice(-120); }

  async start(): Promise<EngineConnection> {
    // ChildProcess.killed only means kill() was called; it remains false when a child
    // crashes on its own. Use exitCode to decide whether the existing engine is alive.
    if (this.connection && this.process && this.process.exitCode === null && !this.process.killed) return this.connection;

    this.connection = null;
    this.process = null;

    const port = await freePort();
    const sessionToken = randomBytes(32).toString('hex');
    const serviceRoot = path.resolve(this.options.serviceRoot);
    const packagedEngine = this.options.engineExecutable ? path.resolve(this.options.engineExecutable) : null;

    if (packagedEngine && !existsSync(packagedEngine)) {
      throw new Error(`Bundled Forge Engine executable is missing: ${packagedEngine}`);
    }

    const python = this.options.pythonExecutable
      ?? process.env.FORGECAD_PYTHON
      ?? managedPython(serviceRoot)
      ?? (process.platform === 'win32' ? 'python' : 'python3');

    const command = packagedEngine ?? python;
    const args = packagedEngine
      ? []
      : ['-m', 'uvicorn', 'forge_engine.main:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'];

    this.logs.length = 0;
    const launchState: { error: Error | null } = { error: null };
    const child = spawn(command, args, {
      cwd: packagedEngine ? path.dirname(packagedEngine) : serviceRoot,
      env: {
        ...process.env,
        ...(packagedEngine ? {} : { PYTHONPATH: serviceRoot }),
        FORGECAD_PORT: String(port),
        FORGECAD_SESSION_TOKEN: sessionToken,
        FORGECAD_OLLAMA_MODEL: this.options.configuredModel,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    this.process = child;

    const record = (prefix: string, chunk: Buffer) => {
      for (const line of chunk.toString('utf8').split(/\r?\n/)) {
        if (line.trim()) this.logs.push(`${prefix}${line}`);
      }
      if (this.logs.length > 500) this.logs.splice(0, this.logs.length - 500);
    };
    child.stdout?.on('data', (chunk: Buffer) => record('', chunk));
    child.stderr?.on('data', (chunk: Buffer) => record('[stderr] ', chunk));

    // If the native engine exits after startup, invalidate the connection immediately.
    // The renderer can then ask for a fresh connection and this supervisor will restart it.
    child.once('exit', (code, signal) => {
      if (this.process !== child) return;
      this.logs.push(`[supervisor] Forge Engine exited code=${String(code)} signal=${String(signal)}`);
      this.connection = null;
      this.process = null;
    });
    child.once('error', (error) => {
      launchState.error = error;
      this.logs.push(`[supervisor] Forge Engine process error: ${error.message}`);
      if (this.process === child) this.connection = null;
    });

    const baseUrl = `http://127.0.0.1:${port}`;
    const startupTimeoutMs = this.options.startupTimeoutMs ?? (packagedEngine ? 120_000 : 45_000);
    const deadline = Date.now() + startupTimeoutMs;
    let lastError: unknown;

    while (Date.now() < deadline) {
      const launchError = launchState.error;
      if (launchError) {
        this.stop();
        throw new Error(`Forge Engine could not launch: ${launchError.message}\nExecutable: ${command}\n${this.logTail.join('\n')}`);
      }
      if (child.exitCode !== null) {
        this.stop();
        throw new Error(`Forge Engine exited with status ${child.exitCode}.\nExecutable: ${command}\n${this.logTail.join('\n')}`);
      }
      try {
        const response = await fetch(`${baseUrl}/v2/health`, { signal: AbortSignal.timeout(1_000) });
        if (response.ok) {
          const payload = await response.json() as { api_version?: string };
          if (payload.api_version !== '2') throw new Error(`Unsupported Forge Engine API ${payload.api_version ?? 'unknown'}`);
          this.connection = { baseUrl, sessionToken, configuredModel: this.options.configuredModel };
          return this.connection;
        }
        lastError = new Error(`Health returned HTTP ${response.status}`);
      } catch (error) {
        lastError = error;
      }
      await new Promise((resolve) => setTimeout(resolve, 150));
    }

    this.stop();
    const bootstrapHint = packagedEngine
      ? 'Reinstall ForgeCAD; its bundled Forge Engine did not start correctly.'
      : process.platform === 'win32'
        ? 'Run scripts\\bootstrap-windows.ps1 to create the managed Forge Engine runtime.'
        : 'Run scripts/bootstrap-macos.sh to create the managed Forge Engine runtime.';
    const timeoutSeconds = Math.round(startupTimeoutMs / 1000);
    throw new Error(`Forge Engine did not become healthy within ${timeoutSeconds} seconds. ${String(lastError ?? '')}\nExecutable: ${command}\n${bootstrapHint}\n${this.logTail.join('\n')}`);
  }

  stop(): void {
    this.connection = null;
    const child = this.process;
    this.process = null;
    if (child && child.exitCode === null && !child.killed) child.kill();
  }
}