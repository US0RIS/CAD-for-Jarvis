from __future__ import annotations

"""FastAPI surface for ForgeCAD 2.0 manufacturing resources."""

import asyncio
import hashlib
from typing import Any

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..v110 import core
from . import manufacturing


_INSTALLED = False


class ExportRequest(BaseModel):
    object_ids: list[str] = Field(default_factory=list)
    tolerance_mm: float = 0.15


class SliceRequest(ExportRequest):
    machine_profile: str | None = None
    process_profile: str | None = None
    filament_profiles: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def install(legacy: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = legacy.app

    @app.get("/v2/manufacturing/p2s", dependencies=[Depends(legacy.require_session)])
    async def p2s_status() -> dict[str, Any]:
        return manufacturing.p2s_status(core.PROJECT, core.build_shape)

    @app.post("/v2/manufacturing/p2s/export", dependencies=[Depends(legacy.require_session)])
    async def p2s_export(request: ExportRequest) -> Response:
        tolerance = min(1.0, max(0.03, float(request.tolerance_mm)))
        try:
            # CadQuery/OpenCascade tessellation stays on Forge Engine's main thread.
            # Moving OCC work through asyncio.to_thread has caused Windows deadlocks in
            # the authoritative scene path; manufacturing uses the same kernel.
            payload = manufacturing.geometry_3mf(
                core.PROJECT,
                core.tessellate,
                object_ids=request.object_ids or None,
                tolerance_mm=tolerance,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_name = str(core.PROJECT.get("name") or "forgecad-print")
        filename = manufacturing._safe_filename(project_name, "forgecad-print") + "-P2S.3mf"
        return Response(
            content=payload,
            media_type="model/3mf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-ForgeCAD-Manufacturing-Resource": "Bambu Lab P2S",
                "X-ForgeCAD-3MF-Stage": "geometry-exchange",
                "X-ForgeCAD-Package-SHA256": _sha256(payload),
                "X-ForgeCAD-Branch": core.ACTIVE_DESIGN,
            },
        )

    @app.post("/v2/manufacturing/p2s/slice", dependencies=[Depends(legacy.require_session)])
    async def p2s_slice(request: SliceRequest) -> Response:
        tolerance = min(1.0, max(0.03, float(request.tolerance_mm)))
        try:
            geometry = manufacturing.geometry_3mf(
                core.PROJECT,
                core.tessellate,
                object_ids=request.object_ids or None,
                tolerance_mm=tolerance,
            )
            # The slicer is a subprocess and does not touch OpenCascade state, so it is
            # safe to keep that potentially slow external process off the event loop.
            sliced, details = await asyncio.to_thread(
                manufacturing.slice_3mf_bytes,
                geometry,
                machine_profile=request.machine_profile,
                process_profile=request.process_profile,
                filament_profiles=request.filament_profiles or None,
                timeout_seconds=request.timeout_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        project_name = str(core.PROJECT.get("name") or "forgecad-print")
        filename = manufacturing._safe_filename(project_name, "forgecad-print") + "-P2S-sliced.3mf"
        return Response(
            content=sliced,
            media_type="model/3mf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-ForgeCAD-Manufacturing-Resource": "Bambu Lab P2S",
                "X-ForgeCAD-3MF-Stage": "bambu-studio-sliced",
                "X-ForgeCAD-Slicer-Exit": str(details.get("returncode", 0)),
                "X-ForgeCAD-Package-SHA256": _sha256(sliced),
                "X-ForgeCAD-Branch": core.ACTIVE_DESIGN,
            },
        )
