from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 milestone 4 bounded autonomous repair."""

from typing import Any, Callable

from fastapi import Depends, HTTPException

from ..v310.engineering_graph import EngineeringGraphStore
from .autonomous_repair import AutonomousRepairRequest, run_bounded_autonomous_repair


_INSTALLED = False


def install(
    app: Any,
    require_session: Callable[..., None],
    graph: EngineeringGraphStore,
    world: Any | None,
    sync_world: Callable[..., dict[str, Any]] | None = None,
    sync_graph: Callable[..., dict[str, Any]] | None = None,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.post("/v6/engineering/autonomous-repair", dependencies=[Depends(require_session)])
    async def bounded_autonomous_repair(request: AutonomousRepairRequest) -> dict[str, Any]:
        try:
            result = run_bounded_autonomous_repair(graph, world, request)
            if sync_world is not None:
                sync_world(reason="v600_bounded_autonomous_repair")
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_bounded_autonomous_repair")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    _INSTALLED = True
