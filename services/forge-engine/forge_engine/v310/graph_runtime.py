from __future__ import annotations

"""Runtime invalidation policy for the 3.1 engineering graph.

Containment is navigational, not a dependency: changing one child must not dirty
an entire project merely because every node shares the project parent. Initial
projection also establishes a clean baseline rather than reporting every newly
projected node as stale work.
"""

from typing import Any

from . import engineering_graph


_INSTALLED = False
_ORIGINAL_SYNCHRONIZE = engineering_graph.EngineeringGraphStore.synchronize


def _synchronize(self: engineering_graph.EngineeringGraphStore, *args: Any, **kwargs: Any) -> dict[str, Any]:
    had_projection = self._snapshot is not None
    result = _ORIGINAL_SYNCHRONIZE(self, *args, **kwargs)
    if not had_projection:
        self.clear_dirty()
        result["baseline_created"] = True
        result["summary"] = self.summary()
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    engineering_graph.DEPENDENCY_EDGE_KINDS.discard("contains")
    engineering_graph.EngineeringGraphStore.synchronize = _synchronize
    _INSTALLED = True
