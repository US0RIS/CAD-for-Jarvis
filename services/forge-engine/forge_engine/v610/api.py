from __future__ import annotations

"""ForgeCAD 6.1 simulation API."""

from copy import deepcopy
import inspect
from typing import Any, Awaitable, Callable, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from ..v600 import external_solvers
from . import MILESTONE_VERSION, RELEASE_COMPLETE, SIMULATION_SCHEMA_VERSION
from . import aerodynamics, joint_loads, multibody, simulation_state, thermal_transient


_INSTALLED = False


class RigidTransform(BaseModel):
    position: list[float] = Field(min_length=3, max_length=3)
    rotation_deg: list[float] = Field(min_length=3, max_length=3)
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)


class AssemblyTransformRequest(BaseModel):
    driver_id: str
    transform: RigidTransform
    reason: str = "Constraint-preserving viewport transform"


class JointPoseRequest(BaseModel):
    joint_id: str
    value: float | None = None
    rotation_deg: float | None = None
    translation_mm: float | None = None
    plane_u_mm: float = 0.0
    plane_v_mm: float = 0.0
    commit: bool = True
    reason: str = "Drive canonical mechanical joint"


class ThermalTransientRequest(BaseModel):
    duration_s: float = Field(gt=0.0)
    timestep_s: float = Field(gt=0.0)
    initial_temperature_c: float
    max_samples: int = Field(default=240, ge=2, le=1000)


class AerodynamicRequest(BaseModel):
    solver: Literal["integral", "openfoam"] = "integral"
    object_ids: list[str] = Field(default_factory=list)
    relative_air_velocity_m_s: list[float] = Field(min_length=3, max_length=3)
    air_density_kg_m3: float = Field(gt=0.0)
    drag_coefficient: float = Field(ge=0.0)
    reference_area_m2: float | None = Field(default=None, gt=0.0)
    lift_coefficient: float = 0.0
    lift_direction: list[float] | None = Field(default=None, min_length=3, max_length=3)
    dynamic_viscosity_pa_s: float | None = Field(default=None, gt=0.0)
    characteristic_length_m: float | None = Field(default=None, gt=0.0)
    center_of_pressure_mm: list[float] | None = Field(default=None, min_length=3, max_length=3)
    moment_reference_mm: list[float] | None = Field(default=None, min_length=3, max_length=3)


class JointLoadRequest(BaseModel):
    gravity_m_s2: list[float] = Field(default_factory=lambda: [0.0, 0.0, -9.80665], min_length=3, max_length=3)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def install(
    app: Any,
    require_session: Any,
    sync_world: Callable[..., Any] | None = None,
    sync_graph: Callable[..., Any] | None = None,
    snapshot: Callable[[], dict[str, Any]] | None = None,
    broadcast: Callable[[dict[str, Any]], Awaitable[Any] | Any] | None = None,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    simulation_state.install()

    async def publish(reason: str, result: dict[str, Any] | None = None) -> None:
        if sync_world is not None:
            sync_world(reason=reason)
        if sync_graph is not None and result is not None:
            result["graph_sync"] = sync_graph(reason=reason)
        if broadcast is not None and snapshot is not None:
            await _maybe_await(broadcast({"type": "project.updated", "project": snapshot()}))

    @app.get("/v6/simulation/health", dependencies=[Depends(require_session)])
    async def simulation_health() -> dict[str, Any]:
        graph = multibody.assembly_graph(core.PROJECT)
        return {
            "ok": bool(graph["ok"]),
            "version": MILESTONE_VERSION,
            "release_complete": RELEASE_COMPLETE,
            "simulation_schema": SIMULATION_SCHEMA_VERSION,
            "design_fingerprint": simulation_state.design_fingerprint(core.PROJECT),
            "active_branch": core.ACTIVE_DESIGN,
            "assembly": graph,
            "domains": {
                "multibody_kinematics": {
                    "available": True,
                    "grade": "engineering_iteration",
                    "features": ["rigid subtree propagation", "joint actuation", "arbitrary joint axes", "constraint continuity"],
                },
                "joint_load_path": {"available": True, "grade": "engineering_iteration"},
                "transient_thermal": {
                    "available": True,
                    "grade": "engineering_iteration",
                    "features": ["thermal capacitance", "conduction", "convection", "fixed temperature", "radiation"],
                },
                "integral_aerodynamics": {
                    "available": True,
                    "grade": "screening",
                    "is_cfd": False,
                },
                "steady_thermal_network": {"available": True, "grade": "engineering_iteration", "source": "v200"},
                "steady_fluid_network": {"available": True, "grade": "engineering_iteration", "source": "v200"},
                "solid_fea": {"available": True, "grade": "engineering_iteration", "source": "v200", "scope": "supported exact geometry only"},
                "rigid_body": {"available": True, "grade": "engineering_iteration", "source": "v200"},
            },
            "external_solvers": external_solvers.solver_inventory(),
            "truth": "Simulation results are predictions tied to the exact design fingerprint; they never constitute physical verification.",
        }

    @app.get("/v6/simulation/assembly/graph", dependencies=[Depends(require_session)])
    async def simulation_assembly_graph() -> dict[str, Any]:
        return multibody.assembly_graph(core.PROJECT)

    @app.post("/v6/simulation/assembly/transform", dependencies=[Depends(require_session)])
    async def simulation_assembly_transform(request: AssemblyTransformRequest) -> dict[str, Any]:
        try:
            with core.LOCK:
                core.ensure_mutable("human", request.reason)
                result = multibody.apply_driver_transform(core.PROJECT, request.driver_id, request.transform.model_dump())
                simulation_state.invalidate_simulations(
                    core.PROJECT,
                    result["affected_ids"],
                    reason="constraint-preserving assembly transform changed canonical body poses",
                )
                core.push_history("v610_multibody_transform", "human", request.reason)
                core.persist()
            await publish("v610_multibody_transform", result)
            result["active_branch"] = core.ACTIVE_DESIGN
            result["design_fingerprint"] = simulation_state.design_fingerprint(core.PROJECT)
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/joints/pose", dependencies=[Depends(require_session)])
    async def simulation_joint_pose(request: JointPoseRequest) -> dict[str, Any]:
        kwargs = {
            "value": request.value,
            "rotation_deg": request.rotation_deg,
            "translation_mm": request.translation_mm,
            "plane_u_mm": request.plane_u_mm,
            "plane_v_mm": request.plane_v_mm,
        }
        try:
            if not request.commit:
                result = multibody.solve_joint_pose(core.PROJECT, request.joint_id, **kwargs)
                result["committed"] = False
                return result
            with core.LOCK:
                core.ensure_mutable("human", request.reason)
                result = multibody.apply_joint_pose(core.PROJECT, request.joint_id, **kwargs)
                simulation_state.invalidate_simulations(
                    core.PROJECT,
                    result["affected_ids"],
                    reason=f"joint {request.joint_id} pose changed",
                )
                core.push_history("v610_joint_pose", "human", request.reason)
                core.persist()
            await publish("v610_joint_pose", result)
            result["committed"] = True
            result["active_branch"] = core.ACTIVE_DESIGN
            result["design_fingerprint"] = simulation_state.design_fingerprint(core.PROJECT)
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown joint/object: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/joints/gravity-loads", dependencies=[Depends(require_session)])
    async def simulation_joint_loads(request: JointLoadRequest) -> dict[str, Any]:
        try:
            result = joint_loads.solve_joint_loads(core.PROJECT, gravity_m_s2=request.gravity_m_s2)
            simulation_state.record_simulation(
                "joint_load_path",
                params=request.model_dump(),
                result=result,
                dependency_object_ids=[str(obj.get("id")) for obj in core.PROJECT.get("objects") or [] if isinstance(obj, dict) and obj.get("id")],
                solver=result["solver"],
                solver_version=result["solver_version"],
                solver_grade=result["solver_grade"],
            )
            await publish("v610_joint_load_simulation")
            return result
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/thermal/transient", dependencies=[Depends(require_session)])
    async def simulation_thermal_transient(request: ThermalTransientRequest) -> dict[str, Any]:
        try:
            result = thermal_transient.solve_transient_thermal(core.PROJECT, **request.model_dump())
            dependencies = [str(row["object_id"]) for row in result.get("nodes") or []]
            simulation_state.record_simulation(
                "thermal_transient",
                params=request.model_dump(),
                result=result,
                dependency_object_ids=dependencies,
                solver=result["solver"],
                solver_version=result["solver_version"],
                solver_grade=result["solver_grade"],
            )
            await publish("v610_transient_thermal_simulation")
            return result
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/aerodynamics", dependencies=[Depends(require_session)])
    async def simulation_aerodynamics(request: AerodynamicRequest) -> dict[str, Any]:
        if request.solver == "openfoam":
            readiness = aerodynamics.openfoam_readiness()
            raise HTTPException(status_code=409, detail={"message": readiness["reason"], "openfoam": readiness})
        try:
            payload = request.model_dump(exclude={"solver"})
            result = aerodynamics.solve_integral_aerodynamics(core.PROJECT, **payload)
            simulation_state.record_simulation(
                "aerodynamics_integral",
                params=request.model_dump(),
                result=result,
                dependency_object_ids=result["object_ids"],
                solver=result["solver"],
                solver_version=result["solver_version"],
                solver_grade=result["solver_grade"],
            )
            await publish("v610_aerodynamic_simulation")
            return result
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/simulation/runs", dependencies=[Depends(require_session)])
    async def simulation_runs() -> dict[str, Any]:
        rows = simulation_state.current_runs(core.PROJECT)
        return {
            "items": rows,
            "count": len(rows),
            "current_count": sum(not bool(row.get("stale")) and bool(row.get("fingerprint_current")) for row in rows),
            "design_fingerprint": simulation_state.design_fingerprint(core.PROJECT),
        }

    _INSTALLED = True
