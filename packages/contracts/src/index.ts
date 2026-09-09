export type RuntimeChannelState = 'starting' | 'ready' | 'degraded' | 'offline' | 'failed';
export type OllamaState = 'checking' | 'warming' | 'ready' | 'offline' | 'failed';
export type DesignStatus = 'working' | 'not_working' | 'unverified';
export type GeometryFidelity = 'exact' | 'manufacturer_mesh' | 'proxy';
export type JobState = 'queued' | 'warming' | 'planning' | 'applying' | 'analyzing' | 'verifying' | 'completed' | 'failed' | 'cancelled';

export interface RuntimeState {
  engine: RuntimeChannelState;
  scene: RuntimeChannelState;
  ollama: OllamaState;
  configuredModel: string;
  resolvedModel?: string;
  apiVersion?: string;
}

export interface DesignBranchSummary {
  name: string;
  headCommit: string;
  parentBranch?: string;
  status: DesignStatus;
  physicalVerified: boolean;
  protected: boolean;
  commitCount: number;
  active: boolean;
}

export interface StructuredError {
  code: string;
  message: string;
  detail?: string;
  recoverable?: boolean;
}

export interface EngineeringJob {
  id: string;
  kind: 'agent' | 'simulation' | 'campaign' | 'component-search' | 'deploy';
  state: JobState;
  createdAt: string;
  progress?: number;
  message?: string;
  branch?: string;
  selectedObjectId?: string;
  error?: StructuredError;
}

export interface ComponentImage {
  kind: 'manufacturer' | 'supplier' | 'cad_render' | 'fallback';
  uri: string;
  source?: string;
  cachedHash?: string;
}

export interface ComponentCandidate {
  id: string;
  manufacturer: string;
  model: string;
  category: string;
  image?: ComponentImage;
  keySpecs: Array<{ label: string; value: string }>;
  price?: { amount: number; currency: string; supplier: string };
  fitScore?: number;
  fitReason?: string;
  unknownRequiredFields: string[];
  geometryFidelity: GeometryFidelity;
}

export interface ScenePartManifest {
  id: string;
  name: string;
  semanticRole?: string;
  assetId: string;
  geometryFidelity: GeometryFidelity;
  transform: {
    position: [number, number, number];
    quaternion: [number, number, number, number];
    scale: [number, number, number];
  };
  bounds?: {
    min: [number, number, number];
    max: [number, number, number];
  };
  explodeGroup?: string;
  programmableWorkspaceId?: string;
}

export interface SceneManifest {
  revision: string;
  branch: string;
  assets: Array<{ id: string; uri: string; hash: string }>;
  parts: ScenePartManifest[];
}
