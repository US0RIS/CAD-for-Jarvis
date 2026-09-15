from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 milestone 5 physical feedback lineage."""

from typing import Any, Callable

from fastapi import Depends, HTTPException

from .physical_retest import (
    BeginPhysicalRetestCycleRequest,
    CompletePhysicalRetestRequest,
    begin_physical_retest_cycle,
    complete_physical_retest_cycle,
    physical_retest_cycles,
    physical_retest_lineage,
)


_INSTALLED = False


def install(app: Any, require_session: Callable[..., None]) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.post("/v6/physical/retest-cycles", dependencies=[Depends(require_session)])
    async def begin_retest(request: BeginPhysicalRetestCycleRequest) -> dict[str, Any]:
        try:
            return begin_physical_retest_cycle(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/complete", dependencies=[Depends(require_session)])
    async def complete_retest(cycle_id: str, request: CompletePhysicalRetestRequest) -> dict[str, Any]:
        try:
            return complete_physical_retest_cycle(cycle_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/requirement identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles", dependencies=[Depends(require_session)])
    async def list_retests() -> dict[str, Any]:
        return physical_retest_cycles()

    @app.get("/v6/physical/retest-lineage", dependencies=[Depends(require_session)])
    async def list_retest_lineage() -> dict[str, Any]:
        return physical_retest_lineage()

    _INSTALLED = True
