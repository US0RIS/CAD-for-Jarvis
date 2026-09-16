import { describe, expect, it } from 'vitest';
import { hasNewResolvedGeometry, type ComponentFidelityHealthPayload } from './componentFidelity';

function health(assetGeneration: number): ComponentFidelityHealthPayload {
  return {
    ok: true,
    version: '6.2.0',
    schema_version: 2,
    asset_generation: assetGeneration,
    project_components: 1,
    authoritative_cad_components: assetGeneration > 0 ? 1 : 0,
    fallback_components: assetGeneration > 0 ? 0 : 1,
    components: [],
  };
}

describe('component fidelity scene refresh generation', () => {
  it('refreshes only after a new exact CAD asset is resolved', () => {
    expect(hasNewResolvedGeometry(0, health(0))).toBe(false);
    expect(hasNewResolvedGeometry(0, health(1))).toBe(true);
    expect(hasNewResolvedGeometry(1, health(1))).toBe(false);
    expect(hasNewResolvedGeometry(1, health(2))).toBe(true);
  });
});
