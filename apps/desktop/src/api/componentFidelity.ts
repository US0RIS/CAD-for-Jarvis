import { engineFetch } from './engine';

export interface ComponentFidelityHealthPayload {
  ok: boolean;
  version: string;
  schema_version: number;
  asset_generation: number;
  project_components: number;
  authoritative_cad_components: number;
  fallback_components: number;
  components: Array<{
    object_id: string;
    component_ref: string;
    authoritative_cad?: boolean;
    asset_sha256?: string | null;
    geometry_fidelity?: string | null;
    resolution_state?: string | null;
  }>;
}

export function hasNewResolvedGeometry(lastGeneration: number, payload: ComponentFidelityHealthPayload): boolean {
  return Number.isFinite(payload.asset_generation) && payload.asset_generation > lastGeneration;
}

export function fetchComponentFidelityHealth(): Promise<ComponentFidelityHealthPayload> {
  return engineFetch<ComponentFidelityHealthPayload>('/v6/component-fidelity/health', {
    signal: AbortSignal.timeout(5_000),
  });
}
