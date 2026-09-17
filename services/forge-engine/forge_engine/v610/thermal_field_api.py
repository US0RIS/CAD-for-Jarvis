from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from . import simulation_state, thermal_field


_INSTALLED = False


class ThermalFieldRequest(BaseModel):
    object_id: str
    duration_s: float = Field(gt=0.0)
    timestep_s: float = Field(gt=0.0)
    initial_temperature_c: float
    heat_w: float
    convection_h_w_m2k: float = Field(ge=0.0)
    ambient_temperature_c: float
    emissivity: float = Field(default=0.0, ge=0.0, le=1.0)
    grid: list[int] = Field(default_factory=lambda: [12, 8, 6], min_length=3, max_length=3)
    max_samples: int = Field(default=120, ge=2, le=500)


def install(app: Any, require_session: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.post("/v6/simulation/thermal/field", dependencies=[Depends(require_session)])
    async def simulation_thermal_field(request: ThermalFieldRequest) -> dict[str, Any]:
        try:
            result = thermal_field.solve_box_thermal_field(
                core.PROJECT,
                request.object_id,
                duration_s=request.duration_s,
                timestep_s=request.timestep_s,
                initial_temperature_c=request.initial_temperature_c,
                heat_w=request.heat_w,
                convection_h_w_m2k=request.convection_h_w_m2k,
                ambient_temperature_c=request.ambient_temperature_c,
                emissivity=request.emissivity,
                grid=request.grid,
                max_samples=request.max_samples,
            )
            simulation_state.record_simulation(
                "thermal_field_3d",
                params=request.model_dump(),
                result=result,
                object_id=request.object_id,
                dependency_object_ids=[request.object_id],
                solver=str(result.get("solver") or "ForgeCAD ThermalField3D"),
                solver_version=str(result.get("solver_version") or "6.1.0"),
                solver_grade=str(result.get("solver_grade") or "unsupported"),
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown object: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    _INSTALLED = True
