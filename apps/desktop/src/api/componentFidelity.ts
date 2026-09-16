import { engineFetch } from './engine';

export interface ComponentAssetRevisionPayload {
  ok: boolean;
  version: string;
  epoch: string;
  generation: number;
}

export type ComponentAssetRevision = Pick<ComponentAssetRevisionPayload, 'epoch' | 'generation'>;

export function hasNewResolvedGeometry(previous: ComponentAssetRevision | null, next: ComponentAssetRevision): boolean {
  if (!previous) return false;
  if (next.epoch !== previous.epoch) return true;
  return Number.isFinite(next.generation) && next.generation > previous.generation;
}

export function fetchComponentAssetRevision(): Promise<ComponentAssetRevisionPayload> {
  return engineFetch<ComponentAssetRevisionPayload>('/v6/component-fidelity/revision', {
    signal: AbortSignal.timeout(5_000),
  });
}
