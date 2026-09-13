import { contextBridge, ipcRenderer } from 'electron';

export interface EngineConnection {
  baseUrl: string;
  sessionToken: string;
  configuredModel: string;
}

export interface ForgeDesktopBridge {
  platform: NodeJS.Platform;
  versions: {
    electron: string;
    chrome: string;
  };
  getEngineConnection(): Promise<EngineConnection>;
  reportComponentCatalogState(state: 'ready' | 'failed', detail?: string): void;
}

const bridge: ForgeDesktopBridge = Object.freeze({
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
  getEngineConnection: () => ipcRenderer.invoke('forgecad:connection') as Promise<EngineConnection>,
  reportComponentCatalogState: (state, detail) => ipcRenderer.send('forgecad:component-catalog-state', state, detail),
});

contextBridge.exposeInMainWorld('forgeDesktop', bridge);
