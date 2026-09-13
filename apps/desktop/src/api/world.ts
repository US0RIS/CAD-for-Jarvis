import { engineFetch } from './engine';

export interface WorldPosePayload {
  frame_id: string;
  position_m: number[];
  orientation_xyzw: number[];
  confidence: number;
}

export interface WorldCapabilityPayload {
  name: string;
  mode: string;
  constraints: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface WorldInterfacePayload {
  id: string;
  kind: string;
  direction?: string | null;
  protocol?: string | null;
  metadata: Record<string, unknown>;
}

export interface WorldStateValuePayload {
  value: unknown;
  unit?: string | null;
  observed_at: string;
  source: string;
  source_id?: string | null;
  confidence: number;
  metadata: Record<string, unknown>;
}

export interface WorldProvenancePayload {
  source: string;
  source_id?: string | null;
  observed_at: string;
  confidence: number;
  authoritative: boolean;
  note?: string | null;
}

export interface WorldEntityPayload {
  id: string;
  name: string;
  kind: string;
  parent_id?: string | null;
  pose: WorldPosePayload;
  capabilities: WorldCapabilityPayload[];
  interfaces: WorldInterfacePayload[];
  live_state: Record<string, WorldStateValuePayload>;
  provenance: WorldProvenancePayload[];
  source_links: Record<string, string>;
  metadata: Record<string, unknown>;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface WorldRelationPayload {
  id: string;
  kind: string;
  a_id: string;
  b_id: string;
  a_interface_id?: string | null;
  b_interface_id?: string | null;
  metadata: Record<string, unknown>;
  provenance: WorldProvenancePayload[];
  created_at: string;
  updated_at: string;
}

export interface WorldEventPayload {
  id: string;
  at: string;
  type: string;
  entity_id?: string | null;
  relation_id?: string | null;
  source: string;
  payload: Record<string, unknown>;
}

export interface WorldHealthPayload {
  ok: boolean;
  api_version: string;
  engine_version: string;
  world_model_schema_version: number;
  world: {
    schema_version: number;
    revision: number;
    entity_count: number;
    relation_count: number;
    event_count: number;
    by_kind: Record<string, number>;
    by_source: Record<string, number>;
  };
  capability_runtime: {
    binding_count: number;
    action_count: number;
    registered_adapters: string[];
    awaiting_confirmation: number;
  };
  project_sync: {
    ok: boolean;
    reason?: string;
    error?: string;
    project_entity_id?: string;
    branch?: string;
    revision?: string;
    project_object_count?: number;
    world_entity_count?: number;
    world_relation_count?: number;
  };
}

export interface WorldEntityListPayload {
  items: WorldEntityPayload[];
  count: number;
}

export interface WorldRelationListPayload {
  items: WorldRelationPayload[];
  count: number;
}

export interface WorldEventsPayload {
  revision: number;
  items: WorldEventPayload[];
  count: number;
  truncated: boolean;
  last_event_id?: string | null;
}

export interface EntityResolutionCandidatePayload {
  entity_id: string;
  name: string;
  kind: string;
  score: number;
  match_type: string;
  path: string;
  source_links: Record<string, string>;
}

export interface EntityResolutionPayload {
  query: string;
  status: 'resolved' | 'ambiguous' | 'not_found';
  entity_id?: string | null;
  exact: boolean;
  reason: string;
  candidates: EntityResolutionCandidatePayload[];
}

export const fetchWorldHealth = () => engineFetch<WorldHealthPayload>('/v3/health');

export function fetchWorldEntities(filters: {
  kind?: string;
  capability?: string;
  parentId?: string;
} = {}) {
  const params = new URLSearchParams();
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.capability) params.set('capability', filters.capability);
  if (filters.parentId) params.set('parent_id', filters.parentId);
  const suffix = params.size ? `?${params.toString()}` : '';
  return engineFetch<WorldEntityListPayload>(`/v3/world/entities${suffix}`);
}

export const fetchWorldEntity = (entityId: string) =>
  engineFetch<WorldEntityPayload>(`/v3/world/entities/${encodeURIComponent(entityId)}`);

export function fetchWorldRelations(entityId?: string) {
  const params = new URLSearchParams();
  if (entityId) params.set('entity_id', entityId);
  const suffix = params.size ? `?${params.toString()}` : '';
  return engineFetch<WorldRelationListPayload>(`/v3/world/relations${suffix}`);
}

export function fetchWorldEvents(afterId?: string, limit = 100) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (afterId) params.set('after_id', afterId);
  return engineFetch<WorldEventsPayload>(`/v3/world/events?${params.toString()}`);
}

export function resolveWorldReference(query: string, filters: { kind?: string; capability?: string } = {}) {
  const params = new URLSearchParams({ q: query });
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.capability) params.set('capability', filters.capability);
  return engineFetch<EntityResolutionPayload>(`/v3/jarvis/resolve?${params.toString()}`);
}
