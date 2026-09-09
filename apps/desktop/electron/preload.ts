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
}

const bridge: ForgeDesktopBridge = Object.freeze({
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
  getEngineConnection: () => ipcRenderer.invoke('forgecad:connection') as Promise<EngineConnection>,
});

contextBridge.exposeInMainWorld('forgeDesktop', bridge);
