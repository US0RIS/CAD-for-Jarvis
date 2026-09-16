import { engineFetch } from './engine';

export interface EngineeringGraphSummary {
  ready: boolean;
  schema_version: number;
  graph_revision?: string;
  project_revision?: string;
  active_branch?: string;
  node_count?: number;
  edge_count?: number;
  evidence_count?: number;
  dirty_node_count?: number;
  stale_evidence_count?: number;
  domains?: Record<string, number>;
  profile?: Record<string, unknown>;
}

export interface EngineeringHealthPayload {
  ok: boolean;
  api_version: string;
  engine_version: string;
  engineering_graph: EngineeringGraphSummary;
  graph_sync: { ok: boolean; reason?: string; error?: string };
  world_sync: { ok: boolean; reason?: string; error?: string };
  profile: Record<string, unknown>;
}

export interface EngineeringNodePayload {
  id: string;
  kind: string;
  name: string;
  domain: string;
  source: string;
  source_id?: string | null;
  fingerprint: string;
  properties: Record<string, unknown>;
  tags: string[];
  confidence: number;
  provenance: Array<Record<string, unknown>>;
  dirty: boolean;
  dirty_reasons: string[];
}

export interface EngineeringEdgePayload {
  id: string;
  kind: string;
  from_id: string;
  to_id: string;
  properties: Record<string, unknown>;
  fingerprint: string;
}

export interface EngineeringEvidencePayload {
  id: string;
  kind: string;
  subject_node_ids: string[];
  requirement_ids: string[];
  value: unknown;
  unit?: string | null;
  status: string;
  method: string;
  source_ids: string[];
  input_fingerprints: Record<string, string>;
  assumptions: string[];
  confidence: number;
  created_at: string;
  stale: boolean;
  invalidation_reasons: string[];
  metadata: Record<string, unknown>;
}

export interface EngineeringNodeDetailPayload {
  node: EngineeringNodePayload;
  edges: EngineeringEdgePayload[];
  evidence: EngineeringEvidencePayload[];
}

export interface ProductProfilePayload {
  profile: {
    mode?: 'general_engineering' | 'product_lab';
    name?: string | null;
    envelope_mm?: number[] | null;
    max_mass_g?: number | null;
    human_contact?: boolean;
    wearable?: boolean;
    stored_energy_limit_j?: number | null;
    max_surface_temperature_c?: number | null;
    preferred_processes?: string[];
    ergonomic_keepouts?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
  screening: {
    ok: boolean;
    findings: Array<{ severity: string; code: string; message: string; [key: string]: unknown }>;
  };
}

export interface CadFeaturePayload {
  id: string;
  type: string;
  name: string;
  enabled: boolean;
  created_at?: string;
  [key: string]: unknown;
}

export interface CadFeatureListPayload {
  object_id: string;
  items: CadFeaturePayload[];
  count: number;
}

export const fetchEngineeringHealth = () => engineFetch<EngineeringHealthPayload>('/v3.1/health');

export function fetchEngineeringNodes(filters: { kind?: string; domain?: string; dirty?: boolean; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.domain) params.set('domain', filters.domain);
  if (filters.dirty != null) params.set('dirty', String(filters.dirty));
  params.set('limit', String(filters.limit ?? 500));
  return engineFetch<{ items: EngineeringNodePayload[]; count: number; total: number }>(`/v3.1/graph/nodes?${params.toString()}`);
}

export const fetchEngineeringNode = (nodeId: string) =>
  engineFetch<EngineeringNodeDetailPayload>(`/v3.1/graph/nodes/${encodeURIComponent(nodeId)}`);

export const fetchEngineeringImpact = (nodeId: string) =>
  engineFetch<{ source: EngineeringNodePayload; impacted: Array<{ node_id: string; kind: string; domain: string; name: string; depth: number; via_edge: string }>; count: number }>(`/v3.1/graph/impact/${encodeURIComponent(nodeId)}`);

export const fetchProductProfile = () => engineFetch<ProductProfilePayload>('/v3.1/product-profile');

export function updateProductProfile(profile: ProductProfilePayload['profile']) {
  return engineFetch<ProductProfilePayload>('/v3.1/product-profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
}

export const fetchCadFeatures = (objectId: string) =>
  engineFetch<CadFeatureListPayload>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features`);

export function createCadFeature(objectId: string, feature: { type: string; name?: string; parameters?: Record<string, unknown> }) {
  return engineFetch<{ ok: boolean; feature: CadFeaturePayload; active_design: string }>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: feature.type, name: feature.name, parameters: feature.parameters ?? {} }),
  });
}

export function updateCadFeature(objectId: string, featureId: string, patch: Record<string, unknown>) {
  return engineFetch<{ ok: boolean; feature: CadFeaturePayload }>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features/${encodeURIComponent(featureId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patch }),
  });
}

export function deleteCadFeature(objectId: string, featureId: string) {
  return engineFetch<{ ok: boolean }>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features/${encodeURIComponent(featureId)}`, { method: 'DELETE' });
}

export function suppressCadFeature(objectId: string, featureId: string, suppressed: boolean) {
  return engineFetch<{ ok: boolean; feature: CadFeaturePayload }>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features/${encodeURIComponent(featureId)}/suppress`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ suppressed }),
  });
}

export function duplicateCadFeature(objectId: string, featureId: string) {
  return engineFetch<{ ok: boolean; feature: CadFeaturePayload }>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features/${encodeURIComponent(featureId)}/duplicate`, { method: 'POST' });
}

export function reorderCadFeature(objectId: string, featureId: string, toIndex: number) {
  return engineFetch<{ ok: boolean }>(`/v3.1/cad/objects/${encodeURIComponent(objectId)}/features/${encodeURIComponent(featureId)}/reorder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to_index: toIndex }),
  });
}
