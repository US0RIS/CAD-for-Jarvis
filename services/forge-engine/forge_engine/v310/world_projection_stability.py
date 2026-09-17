from __future__ import annotations

"""Remove bookkeeping-only churn from the 3.1 engineering graph projection.

The 3.0 Physical World Model intentionally timestamps every upsert. Re-projecting an
unchanged ForgeCAD design therefore refreshes ``updated_at`` and provenance
``observed_at`` values even though no engineering fact changed. Those timestamps are
important in the world event log, but they must not invalidate engineering evidence or
mark graph nodes dirty.

This installer wraps the 3.1 graph synchronization boundary and strips only those
bookkeeping timestamps from the *derived graph input*. Canonical world state remains
untouched and live-state observation timestamps remain part of the engineering
fingerprint because a new observation is an actual state change.
"""

from copy import deepcopy
from typing import Any

from ..v110 import core
from . import integration_services


_INSTALLED = False


def _stable_provenance(rows: Any) -> list[dict[str, Any]]:
    stable: list[dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        row = deepcopy(raw)
        row.pop("observed_at", None)
        stable.append(row)
    return stable


def semantic_world_payload(world: Any | None) -> dict[str, Any] | None:
    if world is None:
        return None
    snapshot = world.snapshot()
    payload = snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else deepcopy(snapshot)
    payload = deepcopy(payload)
    # World revision and event history are transport/audit metadata. The graph models
    # current engineering facts, not the fact that a no-op sync emitted an audit event.
    payload.pop("revision", None)
    payload.pop("events", None)
    for entity in payload.get("entities", []) or []:
        if not isinstance(entity, dict):
            continue
        entity.pop("created_at", None)
        entity.pop("updated_at", None)
        entity["provenance"] = _stable_provenance(entity.get("provenance"))
    for relation in payload.get("relations", []) or []:
        if not isinstance(relation, dict):
            continue
        relation.pop("created_at", None)
        relation.pop("updated_at", None)
        relation["provenance"] = _stable_provenance(relation.get("provenance"))
    return payload


def _synchronize_graph(graph: Any, project_snapshot: dict[str, Any], world: Any | None = None) -> dict[str, Any]:
    with core.LOCK:
        raw = deepcopy(core.PROJECT)
    return graph.synchronize(
        project_snapshot=project_snapshot,
        raw_project=raw,
        world_snapshot=semantic_world_payload(world),
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    integration_services.synchronize_graph = _synchronize_graph
    _INSTALLED = True
