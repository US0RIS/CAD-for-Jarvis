from __future__ import annotations

"""Canonical simulation provenance, invalidation and transform integration for ForgeCAD 6.1."""

from copy import deepcopy
from typing import Any, Iterable

from ..v110 import core
from ..v200 import physical_evidence
from . import SIMULATION_SCHEMA_VERSION
from . import multibody


_ORIGINAL_MARK_STALE = None
_ORIGINAL_EXECUTE = None
_INSTALLED = False


def design_fingerprint(project: dict[str, Any] | None = None) -> str:
    # canonical_fingerprint.install() extends this function in-place for newer v2 state.
    return physical_evidence.design_fingerprint(project)


def invalidate_simulations(
    project: dict[str, Any],
    affected_ids: Iterable[str] | None = None,
    *,
    reason: str = "canonical engineering state changed",
) -> int:
    affected = None if affected_ids is None else {str(value) for value in affected_ids}
    count = 0
    for simulation in project.get("simulations") or []:
        if not isinstance(simulation, dict):
            continue
        object_id = simulation.get("object_id")
        dependencies = {str(value) for value in simulation.get("dependency_object_ids") or []}
        should_stale = affected is None
        if affected is not None:
            # System-level/multibody/thermal/aero runs depend on assembly state unless
            # they explicitly declare a narrower dependency set.
            should_stale = object_id is None or str(object_id) in affected or bool(dependencies & affected)
        if should_stale and not simulation.get("stale"):
            simulation["stale"] = True
            simulation["stale_reason"] = reason
            simulation["stale_against_fingerprint"] = design_fingerprint(project)
            count += 1
    return count


def record_simulation(
    kind: str,
    *,
    params: dict[str, Any],
    result: dict[str, Any],
    object_id: str | None = None,
    dependency_object_ids: Iterable[str] | None = None,
    solver: str,
    solver_version: str,
    solver_grade: str,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    item = core.record_simulation(kind, object_id, params, result)
    item.update({
        "simulation_schema": SIMULATION_SCHEMA_VERSION,
        "design_fingerprint": design_fingerprint(core.PROJECT),
        "dependency_object_ids": sorted({str(value) for value in dependency_object_ids or []}),
        "solver": solver,
        "solver_version": solver_version,
        "solver_grade": solver_grade,
        "limitations": deepcopy(limitations or result.get("limitations") or result.get("assumptions") or []),
        "prediction_not_observation": True,
        "physical_verification": False,
    })
    core.persist()
    return item


def current_runs(project: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    source = project if project is not None else core.PROJECT
    fingerprint = design_fingerprint(source)
    rows: list[dict[str, Any]] = []
    for simulation in source.get("simulations") or []:
        if not isinstance(simulation, dict):
            continue
        row = deepcopy(simulation)
        recorded = row.get("design_fingerprint")
        row["fingerprint_current"] = recorded is None or recorded == fingerprint
        if recorded is not None and recorded != fingerprint:
            row["stale"] = True
            row.setdefault("stale_reason", "design fingerprint changed")
        rows.append(row)
    return rows


def _participates_in_joint_graph(object_id: str) -> bool:
    try:
        graph = multibody.assembly_graph(core.PROJECT)
    except Exception:
        return False
    return any(object_id in {str(edge.get("parent_id")), str(edge.get("child_id"))} for edge in graph.get("edges") or [])


def install() -> None:
    global _INSTALLED, _ORIGINAL_MARK_STALE, _ORIGINAL_EXECUTE
    if _INSTALLED:
        return
    _ORIGINAL_MARK_STALE = core.mark_simulations_stale
    _ORIGINAL_EXECUTE = core.execute

    def mark_simulations_stale(object_id: str | None = None) -> int:
        affected = None if object_id is None else [object_id]
        return invalidate_simulations(core.PROJECT, affected, reason="canonical object changed")

    def execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
        payload = deepcopy(args or {})
        if op != "transform" or not payload.get("id") or not _participates_in_joint_graph(str(payload["id"])):
            assert _ORIGINAL_EXECUTE is not None
            return _ORIGINAL_EXECUTE(op, payload, actor=actor, reason=reason)

        object_id = str(payload["id"])
        with core.LOCK:
            core.ensure_mutable(actor, reason or "constraint-preserving transform")
            obj = core.object_by_id(object_id)
            current = deepcopy(obj.get("transform") or {
                "position": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            })
            requested = {
                "position": payload.get("position", current["position"]),
                "rotation_deg": payload.get("rotation_deg", current["rotation_deg"]),
                "scale": payload.get("scale", current["scale"]),
            }
            result = multibody.apply_driver_transform(core.PROJECT, object_id, requested)
            invalidate_simulations(
                core.PROJECT,
                result["affected_ids"],
                reason="constraint-preserving viewport transform changed multibody pose",
            )
            core.push_history(op, actor, reason or "constraint-preserving transform")
            core.persist()
            return {
                "ok": True,
                "op": op,
                "project": core.PROJECT,
                "active_design": core.ACTIVE_DESIGN,
                "simulation_propagation": {
                    "solver": result["solver"],
                    "affected_ids": result["affected_ids"],
                    "mode": result["mode"],
                },
            }

    core.mark_simulations_stale = mark_simulations_stale
    core.execute = execute
    _INSTALLED = True
