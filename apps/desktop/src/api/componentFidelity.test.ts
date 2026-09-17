import { describe, expect, it } from 'vitest';
import { hasNewResolvedGeometry, type ComponentAssetRevision } from './componentFidelity';

function revision(epoch: string, generation: number): ComponentAssetRevision {
  return { epoch, generation };
}

describe('component fidelity scene refresh revision', () => {
  it('establishes an initial baseline without a redundant scene reload', () => {
    expect(hasNewResolvedGeometry(null, revision('engine-a', 0))).toBe(false);
  });

  it('refreshes only after a new exact CAD asset is resolved in the same engine process', () => {
    expect(hasNewResolvedGeometry(revision('engine-a', 0), revision('engine-a', 0))).toBe(false);
    expect(hasNewResolvedGeometry(revision('engine-a', 0), revision('engine-a', 1))).toBe(true);
    expect(hasNewResolvedGeometry(revision('engine-a', 1), revision('engine-a', 1))).toBe(false);
    expect(hasNewResolvedGeometry(revision('engine-a', 1), revision('engine-a', 2))).toBe(true);
  });

  it('refreshes when the engine process epoch changes even if generation resets', () => {
    expect(hasNewResolvedGeometry(revision('engine-a', 7), revision('engine-b', 0))).toBe(true);
  });
});
