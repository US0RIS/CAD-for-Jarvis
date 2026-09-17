from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .branch_merge import apply_merge, merge_preflight
from .closed_loop import EngineeringLoopRequest, run_engineering_loop
from .engineering_graph import EngineeringGraphStore
from .fabrication_archive import MIME_TYPE as FABRICATION_MIME_TYPE, create_fabrication_archive
from .recovery import create_checkpoint, list_checkpoints, restore_checkpoint


class MergeRequest(BaseModel):
    source: str
    target: str
    branch_name: str | None = None


class CheckpointRequest(BaseModel):
    label: str = "manual"
    reason: str = ""


class FabricationArchiveRequest(BaseModel):
    name: str = "Fabrication Package"
    processes: dict[str, str] = Field(default_factory=dict)
    include_step: bool = True
    include_stl: bool = True


_INSTALLED = False


def install(
    app: Any,
    require_session: Callable[..., None],
    graph: EngineeringGraphStore,
    project_snapshot: Callable[[], dict[str, Any]],
    world: Any,
    sync_world: Callable[..., dict[str, Any]],
    sync_graph: Callable[..., dict[str, Any]],
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.post("/v3.1/history/merge/preflight", dependencies=[Depends(require_session)])
    async def preflight_merge(request: MergeRequest) -> dict[str, Any]:
        try:
            result = merge_preflight(request.source, request.target)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown design branch: {exc.args[0]}") from exc
        # merged_project can be large and is an implementation detail; clients get
        # the semantic conflict report, and apply recomputes preflight transactionally.
        result = dict(result)
        result.pop("merged_project", None)
        return result

    @app.post("/v3.1/history/merge", dependencies=[Depends(require_session)])
    async def merge_branches(request: MergeRequest) -> dict[str, Any]:
        try:
            result = apply_merge(request.source, request.target, branch_name=request.branch_name, actor="human")
            sync_world(reason="v31_semantic_merge")
            result["graph_sync"] = sync_graph(reason="semantic_merge")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown design branch: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v3.1/recovery/checkpoints", dependencies=[Depends(require_session)])
    async def recovery_checkpoints(limit: int = 50) -> dict[str, Any]:
        rows = list_checkpoints(limit=limit)
        return {"items": rows, "count": len(rows)}

    @app.post("/v3.1/recovery/checkpoints", dependencies=[Depends(require_session)])
    async def recovery_checkpoint(request: CheckpointRequest) -> dict[str, Any]:
        return create_checkpoint(request.label, reason=request.reason, actor="human")

    @app.post("/v3.1/recovery/checkpoints/{checkpoint_id}/restore", dependencies=[Depends(require_session)])
    async def recover_checkpoint(checkpoint_id: str) -> dict[str, Any]:
        try:
            result = restore_checkpoint(checkpoint_id, actor="human")
            sync_world(reason="v31_checkpoint_restore")
            result["graph_sync"] = sync_graph(reason="checkpoint_restore")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown recovery checkpoint: {checkpoint_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v3.1/fabrication/archive", dependencies=[Depends(require_session)])
    async def fabrication_archive(request: FabricationArchiveRequest) -> Response:
        try:
            sync_graph(reason="pre_fabrication_archive")
            data, info = create_fabrication_archive(
                graph,
                name=request.name,
                processes=request.processes,
                include_step=request.include_step,
                include_stl=request.include_stl,
            )
            sync_graph(reason="fabrication_archive")
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        filename = str(info["filename"]).replace('"', '')
        return Response(
            data,
            media_type=FABRICATION_MIME_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-ForgeCAD-Fabrication-SHA256": str(info["archive_sha256"]),
                "X-ForgeCAD-Graph-Revision": str(info["manifest"]["engineering_graph_revision"]),
            },
        )

    @app.post("/v3.1/engineering-loop", dependencies=[Depends(require_session)])
    async def engineering_loop(request: EngineeringLoopRequest) -> dict[str, Any]:
        try:
            result = run_engineering_loop(graph, project_snapshot(), world, request)
            sync_world(reason="v31_engineering_loop")
            result["graph_sync"] = sync_graph(reason="engineering_loop")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    _INSTALLED = True
