from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 milestone 3 closed-loop repair work."""

from copy import deepcopy
from typing import Any, Callable

from fastapi import Depends, HTTPException

from ..v110 import core
from ..v310.engineering_graph import EngineeringGraphStore
from .analysis_refresh_repair import AnalysisRefreshingRepairRequest, run_analysis_refreshing_repair
from .repair_trials import ParametricRepairTrialRequest, run_parametric_repair_trial


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

    @app.post("/v6/engineering/repair-trials/parametric", dependencies=[Depends(require_session)])
    async def parametric_repair_trial(request: ParametricRepairTrialRequest) -> dict[str, Any]:
        try:
            result = run_parametric_repair_trial(graph, world, request)
            if sync_world is not None:
                sync_world(reason="v600_parametric_repair_trial")
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_parametric_repair_trial")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/engineering/repair-trials/analysis-refresh", dependencies=[Depends(require_session)])
    async def analysis_refreshing_repair_trial(request: AnalysisRefreshingRepairRequest) -> dict[str, Any]:
        try:
            result = run_analysis_refreshing_repair(graph, world, request)
            if sync_world is not None:
                sync_world(reason="v600_analysis_refresh_repair")
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_analysis_refresh_repair")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/engineering/repair-trials", dependencies=[Depends(require_session)])
    async def repair_trials() -> dict[str, Any]:
        rows = deepcopy(core.PROJECT.get("engineering_trials") or [])
        return {"items": rows, "count": len(rows), "active_branch": core.ACTIVE_DESIGN}

    _INSTALLED = True
