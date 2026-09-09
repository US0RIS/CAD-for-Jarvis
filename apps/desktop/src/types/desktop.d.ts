interface ForgeEngineConnection {
  baseUrl: string;
  sessionToken: string;
  configuredModel: string;
}

interface ForgeDesktopBridge {
  platform: NodeJS.Platform;
  versions: {
    electron: string;
    chrome: string;
  };
  getEngineConnection(): Promise<ForgeEngineConnection>;
}

declare interface Window {
  forgeDesktop: ForgeDesktopBridge;
}
