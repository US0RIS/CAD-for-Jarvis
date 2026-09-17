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
  reportComponentCatalogState(state: 'ready' | 'failed', detail?: string): void;
}

declare interface Window {
  forgeDesktop: ForgeDesktopBridge;
}
