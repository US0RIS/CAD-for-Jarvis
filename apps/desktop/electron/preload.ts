import { contextBridge } from 'electron';

export interface ForgeDesktopBridge {
  platform: NodeJS.Platform;
  versions: {
    electron: string;
    chrome: string;
  };
}

const bridge: ForgeDesktopBridge = Object.freeze({
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
});

contextBridge.exposeInMainWorld('forgeDesktop', bridge);
