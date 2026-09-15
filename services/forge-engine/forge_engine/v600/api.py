from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 dependency-critical engineering milestones."""

from copy import deepcopy
from typing import Any, Callable

from fastapi import Depends, HTTPException

from ..v110 import core
from . import MILESTONE_VERSION
from . import manufacturer_cad_registration, manufacturer_truth
from .assembly_frame_constraints import MateRequest, apply_mate, solve_mate_transform, validate_constraint_set
from .constraint_rank import analyze_constraint_rank
from .geometry_mounts import MountGeometryRequest, audit_mount_geometry, materialize_mount_geometry, plan_mount_geometry
from .mount_access import MountAccessRequest, audit_mount_access, plan_mount_access
from .mount_hardware import MountHardwareRequest, audit_mount_hardware, plan_mount_hardware, realize_mount_hardware


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

    # Correct manufacturer-sourced mounting truth before any v6 component is
    # instantiated. The overlay patches source registry structures and rebuilds
    # the registry, so later immutable component snapshots inherit the same
    # coordinates, datum and provenance used by the deterministic B-rep builders.
    manufacturer_truth.install_manufacturer_truth()
    manufacturer_cad_registration.install(manufacturer_truth.MANUFACTURER_MOUNT_TRUTH)

    @app.get("/v6/health")
    async def v6_health() -> dict[str, Any]:
        constraints = validate_constraint_set(core.PROJECT)
        rank = analyze_constraint_rank(core.PROJECT)
        geometry_backed_mounts = sum(
            len((obj.get("semantic") or {}).get("geometry_backed_mounts") or [])
            for obj in core.PROJECT.get("objects") or []
            if isinstance(obj, dict)
        )
        hardware_realizations = len(core.PROJECT.get("mount_hardware_realizations") or [])
        return {
            "ok": constraints["ok"],
            "api_version": "6.0-dev",
            "milestone_version": MILESTONE_VERSION,
            "release_complete": False,
            "current_milestone": "revision_bound_physical_feedback",
            "completed_milestones": [
                "interface_constrained_electromechanical_assembly",
                "geometry_backed_assembly_truth",
                "evidence_preserving_analysis_refresh_repair",
                "bounded_multi_strategy_autonomous_repair",
            ],
            "assembly_constraints": constraints,
            "assembly_constraint_rank_summary": rank["summary"],
            "geometry_backed_mount_count": geometry_backed_mounts,
            "mount_hardware_realization_count": hardware_realizations,
            "physical_retest_cycle_count": len(core.PROJECT.get("physical_retest_cycles") or []),
            "manufacturer_mount_truth": manufacturer_truth.summary(),
            "manufacturer_cad_registration": manufacturer_cad_registration.summary(),
            "maturity": {
                "milestone_1": 2,
                "milestone_2": 2,
                "milestone_3": 2,
                "milestone_4": 2,
                "milestone_5": 2,
                "physical_hardware_validation": False,
            },
            "invariants": [
                "designed truth != observed state != inference",
                "autonomous placement derives from declared engineering interfaces",
                "purchased component engineering data remains immutable inside a design revision",
                "fixed/prismatic placement resolves a complete right-handed interface frame rather than an arbitrary point-plus-axis rotation",
                "assembly mobility and redundant constraints are derived from the spatial constraint Jacobian rather than guessed from mate count",
                "a mechanical mount is not verified until declared mounting geometry is present in the fabricated B-rep",
                "manufacturer mounting patterns use explicit coordinates, coordinate datums and source provenance when spacing alone cannot define physical location",
                "manufacturer STEP geometry is authoritative only after rigid registration to a validated mechanical datum; whole-assembly bounding-box centering is not engineering truth",
                "a realized mount is not assembly-ready if neighboring B-reps occupy its standoff or straight-driver access envelopes",
                "standard mount hardware may be specified before supplier selection, but unresolved manufacturer/MPN remains explicitly unresolved",
                "ambiguous component mounting topology fails closed rather than being guessed",
                "a repair candidate cannot reuse solver evidence made stale by its own geometry mutation",
                "autonomous repair may select only among explicitly authorized strategies that survive canonical requirement re-verification",
                "physical evidence applies only to the exact engineering fingerprint that was actually tested",
                "passing one physical retest verifies only its scoped requirement and never silently marks the entire design physically verified",
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
                core.push_history("v6_mate", "human", f"{request.mate_type} full-interface-frame mate")
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

    @app.get("/v6/assembly/constraint-rank", dependencies=[Depends(require_session)])
    async def assembly_constraint_rank() -> dict[str, Any]:
        try:
            return analyze_constraint_rank(core.PROJECT)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @app.post("/v6/assembly/mounts/hardware/plan", dependencies=[Depends(require_session)])
    async def mount_hardware_plan(request: MountHardwareRequest) -> dict[str, Any]:
        try:
            return plan_mount_hardware(core.PROJECT, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/assembly/mounts/hardware/realize", dependencies=[Depends(require_session)])
    async def mount_hardware_realize(request: MountHardwareRequest) -> dict[str, Any]:
        try:
            with core.LOCK:
                core.ensure_mutable("human", "6.0 standards-backed mount hardware")
                result = realize_mount_hardware(core.PROJECT, request)
                core.mark_simulations_stale(request.host_id)
                core.push_history(
                    "v6_realize_mount_hardware",
                    "human",
                    f"Realize {request.component_interface} mount hardware for {request.component_id}",
                )
                core.persist()
            if sync_world is not None:
                sync_world(reason="v600_mount_hardware")
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_mount_hardware")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/assembly/mounts/hardware/audit", dependencies=[Depends(require_session)])
    async def mount_hardware_audit(request: MountHardwareRequest) -> dict[str, Any]:
        return audit_mount_hardware(core.PROJECT, request)

    @app.post("/v6/assembly/mounts/access/plan", dependencies=[Depends(require_session)])
    async def mount_access_plan(request: MountAccessRequest) -> dict[str, Any]:
        try:
            plan = plan_mount_access(core.PROJECT, request)
            return {key: value for key, value in plan.items() if key != "_runtime_envelopes"}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object/interface: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/assembly/mounts/access/audit", dependencies=[Depends(require_session)])
    async def mount_access_audit(request: MountAccessRequest) -> dict[str, Any]:
        return audit_mount_access(core.PROJECT, request)

    _INSTALLED = True
