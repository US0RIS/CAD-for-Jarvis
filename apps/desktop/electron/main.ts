import { app, BrowserWindow, Menu, dialog, ipcMain } from 'electron';
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
const PACKAGED_ENGINE = app.isPackaged && process.platform === 'win32'
  ? path.join(process.resourcesPath, 'forge-engine', 'forge-engine.exe')
  : undefined;
const PLATFORM_DEFAULT_MODEL = process.platform === 'darwin' ? 'qwen3:8b' : 'qwen3.8:27b';
const CONFIGURED_MODEL = process.env.FORGECAD_OLLAMA_MODEL ?? PLATFORM_DEFAULT_MODEL;

const engine = new EngineSupervisor({
  serviceRoot: SERVICE_ROOT,
  configuredModel: CONFIGURED_MODEL,
  ...(PACKAGED_ENGINE ? { engineExecutable: PACKAGED_ENGINE } : {}),
});
let mainWindow: BrowserWindow | null = null;

async function createMainWindow() {
  const connection = await engine.start();
  ipcMain.removeHandler('forgecad:connection');
  ipcMain.handle('forgecad:connection', () => connection);

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

  mainWindow.once('ready-to-show', () => mainWindow?.show());
  if (VITE_DEV_SERVER_URL) {
    await mainWindow.loadURL(VITE_DEV_SERVER_URL);
  } else {
    await mainWindow.loadFile(path.join(RENDERER_DIST, 'index.html'));
  }
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
      title: 'ForgeCAD could not start',
      message: 'Forge Engine failed its startup gate.',
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
