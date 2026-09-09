import { randomBytes } from 'node:crypto';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';

export interface EngineConnection {
  baseUrl: string;
  sessionToken: string;
  configuredModel: string;
}

export interface EngineSupervisorOptions {
  serviceRoot: string;
  configuredModel: string;
  pythonExecutable?: string;
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

export class EngineSupervisor {
  private process: ChildProcessWithoutNullStreams | null = null;
  private connection: EngineConnection | null = null;
  private readonly logs: string[] = [];

  constructor(private readonly options: EngineSupervisorOptions) {}

  get currentConnection(): EngineConnection | null {
    return this.connection;
  }

  get logTail(): string[] {
    return this.logs.slice(-120);
  }

  async start(): Promise<EngineConnection> {
    if (this.connection && this.process && !this.process.killed) return this.connection;

    const port = await freePort();
    const sessionToken = randomBytes(32).toString('hex');
    const python = this.options.pythonExecutable ?? process.env.FORGECAD_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
    const serviceRoot = path.resolve(this.options.serviceRoot);

    this.logs.length = 0;
    this.process = spawn(
      python,
      ['-m', 'uvicorn', 'forge_engine.main:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
      {
        cwd: serviceRoot,
        env: {
          ...process.env,
          PYTHONPATH: serviceRoot,
          FORGECAD_PORT: String(port),
          FORGECAD_SESSION_TOKEN: sessionToken,
          FORGECAD_OLLAMA_MODEL: this.options.configuredModel,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );

    const record = (prefix: string, chunk: Buffer) => {
      for (const line of chunk.toString('utf8').split(/\r?\n/)) {
        if (line.trim()) this.logs.push(`${prefix}${line}`);
      }
      if (this.logs.length > 500) this.logs.splice(0, this.logs.length - 500);
    };
    this.process.stdout.on('data', (chunk: Buffer) => record('', chunk));
    this.process.stderr.on('data', (chunk: Buffer) => record('[stderr] ', chunk));

    const baseUrl = `http://127.0.0.1:${port}`;
    const deadline = Date.now() + 30_000;
    let lastError: unknown;

    while (Date.now() < deadline) {
      if (this.process.exitCode !== null) {
        throw new Error(`Forge Engine exited with status ${this.process.exitCode}.\n${this.logTail.join('\n')}`);
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
    throw new Error(`Forge Engine did not become healthy within 30 seconds. ${String(lastError ?? '')}\n${this.logTail.join('\n')}`);
  }

  stop(): void {
    this.connection = null;
    if (this.process && !this.process.killed) this.process.kill();
    this.process = null;
  }
}
