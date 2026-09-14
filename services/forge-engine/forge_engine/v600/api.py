from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 dependency-critical assembly milestones."""

from copy import deepcopy
from typing import Any, Callable

from fastapi import Depends, HTTPException

from ..v110 import core
from . import MILESTONE_VERSION
from .assembly_constraints import MateRequest, apply_mate, solve_mate_transform, validate_constraint_set
from .geometry_mounts import MountGeometryRequest, audit_mount_geometry, materialize_mount_geometry, plan_mount_geometry


_INSTALLED = False


def install(
    app: Any,
    require_session: Callable[..., None],
    sync_world: Callable[..., dict[str, Any]] | None = None,
    sync_graph: Callable[..., dict[str, Any]] | None = None,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.get("/v6/health")
    async def v6_health() -> dict[str, Any]:
        constraints = validate_constraint_set(core.PROJECT)
        geometry_backed_mounts = sum(
            len((obj.get("semantic") or {}).get("geometry_backed_mounts") or [])
            for obj in core.PROJECT.get("objects") or []
            if isinstance(obj, dict)
        )
        return {
            "ok": constraints["ok"],
            "api_version": "6.0-dev",
            "milestone_version": MILESTONE_VERSION,
            "release_complete": False,
            "current_milestone": "geometry_backed_assembly_truth",
            "completed_milestones": ["interface_constrained_electromechanical_assembly"],
            "assembly_constraints": constraints,
            "geometry_backed_mount_count": geometry_backed_mounts,
            "invariants": [
                "designed truth != observed state != inference",
                "autonomous placement derives from declared engineering interfaces",
                "purchased component engineering data remains immutable inside a design revision",
                "a mechanical mount is not verified until declared mounting geometry is present in the fabricated B-rep",
                "ambiguous component mounting topology fails closed rather than being guessed",
            ],
        }

    @app.post("/v6/assembly/mates/solve", dependencies=[Depends(require_session)])
    async def solve_mate(request: MateRequest) -> dict[str, Any]:
        try:
            return solve_mate_transform(core.PROJECT, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/assembly/mates/apply", dependencies=[Depends(require_session)])
    async def create_mate(request: MateRequest) -> dict[str, Any]:
        try:
            with core.LOCK:
                core.ensure_mutable("human", "6.0 interface-constrained mate")
                result = apply_mate(core.PROJECT, request)
                core.mark_simulations_stale(request.source_id)
                core.push_history("v6_mate", "human", f"{request.mate_type} interface-constrained mate")
                core.persist()
            if sync_world is not None:
                sync_world(reason="v600_interface_mate")
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_interface_mate")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/assembly/constraints", dependencies=[Depends(require_session)])
    async def assembly_constraints() -> dict[str, Any]:
        return validate_constraint_set(core.PROJECT)

    @app.get("/v6/assembly/mates", dependencies=[Depends(require_session)])
    async def assembly_mates() -> dict[str, Any]:
        rows = [
            deepcopy(row)
            for row in core.PROJECT.get("joints", [])
            if str(row.get("solver") or "").startswith("forgecad.v600.")
        ]
        return {"items": rows, "count": len(rows)}

    @app.post("/v6/assembly/mounts/plan", dependencies=[Depends(require_session)])
    async def mount_plan(request: MountGeometryRequest) -> dict[str, Any]:
        try:
            return plan_mount_geometry(core.PROJECT, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/assembly/mounts/materialize", dependencies=[Depends(require_session)])
    async def materialize_mount(request: MountGeometryRequest) -> dict[str, Any]:
        try:
            with core.LOCK:
                core.ensure_mutable("human", "6.0 geometry-backed mounting pattern")
                result = materialize_mount_geometry(core.PROJECT, request, actor="human")
                core.mark_simulations_stale(request.host_id)
                core.push_history(
                    "v6_materialize_mount_geometry",
                    "human",
                    f"Materialize {request.component_interface} mounting geometry into {request.host_interface}",
                )
                core.persist()
            if sync_world is not None:
                sync_world(reason="v600_geometry_backed_mount")
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_geometry_backed_mount")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/assembly/mounts/audit", dependencies=[Depends(require_session)])
    async def audit_mount(request: MountGeometryRequest) -> dict[str, Any]:
        try:
            return audit_mount_geometry(core.PROJECT, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    _INSTALLED = True
