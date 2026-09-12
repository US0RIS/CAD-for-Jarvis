import { app, BrowserWindow, Menu, dialog, ipcMain } from 'electron';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { EngineSupervisor } from './engineSupervisor';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.join(__dirname, '..');
const RENDERER_DIST = path.join(APP_ROOT, 'dist');
const VITE_DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;
const SERVICE_ROOT = process.env.FORGECAD_ENGINE_ROOT ?? (app.isPackaged
  ? path.join(process.resourcesPath, 'forge-engine')
  : path.resolve(APP_ROOT, '../../services/forge-engine'));

function packagedEnginePath(): string | undefined {
  if (!app.isPackaged) return undefined;
  const root = path.join(process.resourcesPath, 'forge-engine');
  const candidates = process.platform === 'win32'
    ? [path.join(root, 'forge-engine.exe')]
    : [
        // macOS 1.1.2+ uses PyInstaller onedir so CAD/OCP/VTK libraries do not need to
        // unpack from a giant one-file executable on every launch. Keep the legacy path
        // as a fallback so development and older packages remain diagnosable.
        path.join(root, 'forge-engine', 'forge-engine'),
        path.join(root, 'forge-engine'),
      ];
  return candidates.find((candidate) => existsSync(candidate)) ?? candidates[0];
}

const PACKAGED_ENGINE = packagedEnginePath();
const CONFIGURED_MODEL = process.env.FORGECAD_OLLAMA_MODEL ?? 'qwen3:8b';

const engine = new EngineSupervisor({
  serviceRoot: SERVICE_ROOT,
  configuredModel: CONFIGURED_MODEL,
  startupTimeoutMs: app.isPackaged ? 120_000 : 45_000,
  ...(PACKAGED_ENGINE ? { engineExecutable: PACKAGED_ENGINE } : {}),
});
let mainWindow: BrowserWindow | null = null;
let engineLoadingWindow: BrowserWindow | null = null;

// Always resolve the current engine connection dynamically. If the native engine exits,
// EngineSupervisor.start() creates a fresh process/port/session and the renderer can recover
// without being stranded on the stale connection captured when the window first opened.
ipcMain.handle('forgecad:connection', () => engine.start());

const ENGINE_LOADING_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="dark">
<style>
  *{box-sizing:border-box}
  html,body{width:100%;height:100%;margin:0;overflow:hidden;background:transparent;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e6e9ed}
  body{display:grid;place-items:center;padding:8px}
  .modal{width:100%;height:100%;display:flex;flex-direction:column;justify-content:center;padding:30px 34px;background:#171a1e;border:1px solid #414851;border-radius:12px;box-shadow:0 22px 70px rgba(0,0,0,.55)}
  .brand{display:flex;align-items:center;gap:10px;margin-bottom:22px;color:#aab1b9;font-size:12px;font-weight:600;letter-spacing:.02em}
  .mark{display:grid;place-items:center;width:25px;height:25px;border-radius:3px;background:#e8eaed;color:#1a1d21;font-weight:800;font-size:14px}
  h1{margin:0 0 8px;font-size:20px;line-height:1.2;font-weight:650;letter-spacing:-.01em;color:#f0f2f4}
  p{margin:0;color:#929aa3;font-size:12px;line-height:1.45}
  .track{position:relative;height:5px;margin-top:22px;overflow:hidden;border-radius:3px;background:#292e34;border:1px solid #343a42}
  .track span{position:absolute;top:-1px;bottom:-1px;width:38%;border-radius:3px;background:#5d94bd;animation:load 1.15s cubic-bezier(.45,0,.55,1) infinite}
  .status{margin-top:10px;font-size:10px;color:#737c85}
  @keyframes load{0%{left:-40%}50%{left:48%}100%{left:102%}}
  @media (prefers-reduced-motion:reduce){.track span{animation-duration:2.4s}}
</style>
</head>
<body>
  <section class="modal" role="dialog" aria-modal="true" aria-labelledby="engine-title">
    <div class="brand"><span class="mark">F</span><span>ForgeCAD</span></div>
    <h1 id="engine-title">Engine loading</h1>
    <p>Starting the local Forge Engine and CAD services.</p>
    <div class="track" role="progressbar" aria-label="Forge Engine loading"><span></span></div>
    <div class="status">The design interface will unlock automatically when the engine is ready.</div>
  </section>
</body>
</html>`;

async function createEngineLoadingModal(parent: BrowserWindow): Promise<BrowserWindow> {
  const modal = new BrowserWindow({
    parent,
    modal: true,
    width: 440,
    height: 250,
    minWidth: 440,
    minHeight: 250,
    maxWidth: 440,
    maxHeight: 250,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    closable: false,
    frame: false,
    transparent: true,
    hasShadow: true,
    show: false,
    backgroundColor: '#00000000',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  modal.on('closed', () => {
    if (engineLoadingWindow === modal) engineLoadingWindow = null;
  });
  await modal.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(ENGINE_LOADING_HTML)}`);
  return modal;
}

async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1586,
    height: 992,
    minWidth: 1280,
    minHeight: 760,
    backgroundColor: '#071016',
    title: 'ForgeCAD — AI Engineering Studio',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const window = mainWindow;
  window.on('closed', () => {
    if (mainWindow === window) mainWindow = null;
    if (engineLoadingWindow && !engineLoadingWindow.isDestroyed()) engineLoadingWindow.destroy();
  });

  // Start the native engine immediately, but do not hold the entire desktop window back.
  // The user sees ForgeCAD at once with a true modal child window over it. Because the
  // child is `modal: true`, the CAD workbench cannot receive pointer or keyboard input
  // until EngineSupervisor has passed its health gate and this window is destroyed.
  const engineStartup = engine.start().then(
    (connection) => ({ ok: true as const, connection }),
    (error: unknown) => ({ ok: false as const, error }),
  );

  engineLoadingWindow = await createEngineLoadingModal(window);

  if (VITE_DEV_SERVER_URL) {
    await window.loadURL(VITE_DEV_SERVER_URL);
  } else {
    await window.loadFile(path.join(RENDERER_DIST, 'index.html'));
  }

  if (window.isDestroyed()) return;
  window.show();
  if (engineLoadingWindow && !engineLoadingWindow.isDestroyed()) {
    engineLoadingWindow.show();
    engineLoadingWindow.focus();
  }

  const startup = await engineStartup;
  if (startup.ok) {
    if (engineLoadingWindow && !engineLoadingWindow.isDestroyed()) engineLoadingWindow.destroy();
    engineLoadingWindow = null;
    window.focus();
    return;
  }

  if (engineLoadingWindow && !engineLoadingWindow.isDestroyed()) engineLoadingWindow.destroy();
  engineLoadingWindow = null;
  const detail = startup.error instanceof Error ? startup.error.message : String(startup.error);
  await dialog.showMessageBox(window, {
    type: 'error',
    title: 'ForgeCAD could not start',
    message: 'Forge Engine failed its startup gate.',
    detail,
    buttons: ['Quit'],
  });
  app.quit();
}

function createMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [
    { role: 'appMenu' },
    { label: 'File', submenu: [{ role: 'close' }] },
    { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }] },
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'togglefullscreen' }] },
    { label: 'Project', submenu: [] },
    { label: 'Simulation', submenu: [] },
    { label: 'Tools', submenu: [] },
    { role: 'windowMenu' },
    { role: 'help' },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(async () => {
  createMenu();
  try {
    await createMainWindow();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    await dialog.showMessageBox({
      type: 'error',
      title: 'ForgeCAD could not open',
      message: 'ForgeCAD could not create its desktop window.',
      detail,
      buttons: ['Quit'],
    });
    app.quit();
    return;
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createMainWindow();
  });
});

app.on('before-quit', () => engine.stop());
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});