from __future__ import annotations

"""Additional ForgeCAD 6.1 simulation endpoints over validated lower-level solvers."""

import inspect
from typing import Any, Awaitable, Callable, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from ..v200 import fluid_network, project_structural, rigid_body_dynamics, structural_fea
from . import motion_simulation, simulation_state


_INSTALLED = False


class JointSweepRequest(BaseModel):
    joint_id: str
    start_state: dict[str, float] = Field(default_factory=dict)
    end_state: dict[str, float] = Field(default_factory=dict)
    duration_s: float = Field(default=1.0, gt=0.0)
    samples: int = Field(default=21, ge=3, le=121)
    gravity_m_s2: list[float] = Field(default_factory=lambda: [0.0, 0.0, -9.80665], min_length=3, max_length=3)
    collision_tolerance_mm3: float = Field(default=1e-6, ge=0.0)


class StructuralRequest(BaseModel):
    object_id: str
    mode: Literal["canonical", "screening"] = "canonical"
    force_n: float = 100.0
    load_direction: Literal["x", "y", "z"] = "z"
    convergence: bool = True


class RigidBodyRequest(BaseModel):
    object_ids: list[str] = Field(default_factory=list)
    force_n: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    torque_nm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    gravity_m_s2: list[float] = Field(default_factory=lambda: [0.0, 0.0, -9.80665], min_length=3, max_length=3)
    duration_s: float = Field(default=0.0, ge=0.0)
    initial_velocity_m_s: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    initial_angular_velocity_rad_s: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)


class FluidSteadyRequest(BaseModel):
    record: bool = True


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _object(object_id: str) -> dict[str, Any]:
    return core.object_by_id(object_id)


def install(
    app: Any,
    require_session: Any,
    *,
    snapshot: Callable[[], dict[str, Any]] | None = None,
    broadcast: Callable[[dict[str, Any]], Awaitable[Any] | Any] | None = None,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    async def publish() -> None:
        if broadcast is not None and snapshot is not None:
            await _maybe_await(broadcast({"type": "project.updated", "project": snapshot()}))

    @app.post("/v6/simulation/joints/sweep", dependencies=[Depends(require_session)])
    async def simulation_joint_sweep(request: JointSweepRequest) -> dict[str, Any]:
        try:
            result = motion_simulation.simulate_joint_sweep(
                core.PROJECT,
                request.joint_id,
                start_state=request.start_state,
                end_state=request.end_state,
                duration_s=request.duration_s,
                samples=request.samples,
                gravity_m_s2=request.gravity_m_s2,
                collision_tolerance_mm3=request.collision_tolerance_mm3,
            )
            simulation_state.record_simulation(
                "multibody_motion",
                params=request.model_dump(),
                result=result,
                dependency_object_ids=result["moving_object_ids"],
                solver=result["solver"],
                solver_version=result["solver_version"],
                solver_grade=result["solver_grade"],
            )
            await publish()
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown joint/object: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/structural", dependencies=[Depends(require_session)])
    async def simulation_structural(request: StructuralRequest) -> dict[str, Any]:
        try:
            obj = _object(request.object_id)
            if request.mode == "canonical":
                result = project_structural.solve_project_box(obj, core.PROJECT)
                if not result.get("supported"):
                    # Unsupported is evidence, not an HTTP failure. It tells the UI exactly
                    # why this design cannot currently make a structural claim.
                    result.setdefault("solver", "ForgeCAD ProjectSolidFEA")
                    result.setdefault("solver_version", "2.0.0")
                    result.setdefault("solver_grade", "unsupported")
            else:
                result = structural_fea.solve_box(
                    obj,
                    force_n=request.force_n,
                    load_direction=request.load_direction,
                )
                if request.convergence and result.get("supported"):
                    result["convergence"] = structural_fea.convergence_study(
                        obj,
                        force_n=request.force_n,
                        load_direction=request.load_direction,
                    )
            solver = str(result.get("solver") or "ForgeCAD SolidFEA")
            version = str(result.get("solver_version") or "2.0.0")
            grade = str(result.get("solver_grade") or ("engineering_iteration" if result.get("supported") else "unsupported"))
            simulation_state.record_simulation(
                "structural_fea",
                params=request.model_dump(),
                result=result,
                object_id=request.object_id,
                dependency_object_ids=[request.object_id],
                solver=solver,
                solver_version=version,
                solver_grade=grade,
            )
            await publish()
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/fluid/steady", dependencies=[Depends(require_session)])
    async def simulation_fluid_steady(request: FluidSteadyRequest) -> dict[str, Any]:
        try:
            result = fluid_network.solve_fluid_network(core.PROJECT)
            if request.record and result.get("requested"):
                dependencies = [
                    str(row.get("object_id"))
                    for row in result.get("nodes") or []
                    if isinstance(row, dict) and row.get("object_id")
                ]
                simulation_state.record_simulation(
                    "fluid_network_steady",
                    params=request.model_dump(),
                    result=result,
                    dependency_object_ids=dependencies,
                    solver=str(result.get("solver") or "ForgeCAD FluidNetwork"),
                    solver_version=str(result.get("solver_version") or "2.0.0"),
                    solver_grade=str(result.get("solver_grade") or "engineering_iteration"),
                )
                await publish()
            return result
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/simulation/rigid-body", dependencies=[Depends(require_session)])
    async def simulation_rigid_body(request: RigidBodyRequest) -> dict[str, Any]:
        try:
            result = rigid_body_dynamics.rigid_body_response(
                core.PROJECT,
                object_ids=request.object_ids or None,
                force_n=request.force_n,
                torque_nm=request.torque_nm,
                gravity_m_s2=request.gravity_m_s2,
                duration_s=request.duration_s,
                initial_velocity_m_s=request.initial_velocity_m_s,
                initial_angular_velocity_rad_s=request.initial_angular_velocity_rad_s,
            )
            dependencies = [str(row.get("id")) for row in result.get("bodies") or [] if isinstance(row, dict) and row.get("id")]
            simulation_state.record_simulation(
                "rigid_body",
                params=request.model_dump(),
                result=result,
                dependency_object_ids=dependencies,
                solver=str(result.get("solver") or "ForgeCAD RigidBody"),
                solver_version=str(result.get("solver_version") or "2.0.0"),
                solver_grade=str(result.get("solver_grade") or "engineering_iteration"),
            )
            await publish()
            return result
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    _INSTALLED = True
