from __future__ import annotations

"""Runtime invalidation policy for the 3.1 engineering graph.

Containment is navigational, not a dependency: changing one child must not dirty
an entire project merely because every node shares the project parent. Initial
projection establishes a clean baseline. Explicit unresolved dirtiness (for example
a failed physical inspection) survives reconstructable graph rebuilds until a
verification/repair path clears it deliberately.
"""

from typing import Any

from . import engineering_graph


_INSTALLED = False
_ORIGINAL_SYNCHRONIZE = engineering_graph.EngineeringGraphStore.synchronize


def _synchronize(self: engineering_graph.EngineeringGraphStore, *args: Any, **kwargs: Any) -> dict[str, Any]:
    had_projection = self._snapshot is not None
    previous_dirty: dict[str, list[str]] = {}
    if self._snapshot is not None:
        previous_dirty = {
            row.id: list(row.dirty_reasons)
            for row in self._snapshot.nodes
            if row.dirty
        }

    result = _ORIGINAL_SYNCHRONIZE(self, *args, **kwargs)
    if not had_projection:
        self.clear_dirty()
        result["baseline_created"] = True
        result["summary"] = self.summary()
        return result

    # A graph rebuild is a projection operation, not evidence that an unresolved
    # engineering condition disappeared. Preserve explicit dirty state for surviving
    # nodes. Canonical changes discovered by the base synchronizer are already dirty
    # and reasons are unioned rather than overwritten.
    if previous_dirty and self._snapshot is not None:
        node_map = {row.id: row for row in self._snapshot.nodes}
        restored = False
        for node_id, reasons in previous_dirty.items():
            row = node_map.get(node_id)
            if row is None:
                continue
            row.dirty = True
            row.dirty_reasons = sorted(set([*row.dirty_reasons, *reasons]))
            restored = True
        if restored:
            self._recompute_revision_locked()
            self._persist()
            result["summary"] = self.summary()
            result["graph_revision"] = self._snapshot.graph_revision
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    engineering_graph.DEPENDENCY_EDGE_KINDS.discard("contains")
    engineering_graph.EngineeringGraphStore.synchronize = _synchronize
    _INSTALLED = True
