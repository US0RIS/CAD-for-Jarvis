from __future__ import annotations

"""ForgeCAD 6.0 milestone 6 external-solver and chemistry API."""

from typing import Any, Callable

from fastapi import Depends, HTTPException

from .chemistry import (
    ChemistryStudyRequest,
    chemistry_runs,
    chemistry_studies,
    create_chemistry_study,
    run_chemistry_study,
)
from .external_solvers import solver_inventory, solver_status


_INSTALLED = False


def install(
    app: Any,
    require_session: Callable[..., None],
    graph: Any,
    sync_graph: Callable[..., dict[str, Any]] | None = None,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.get("/v6/solvers", dependencies=[Depends(require_session)])
    async def external_solvers() -> dict[str, Any]:
        return solver_inventory()

    @app.get("/v6/solvers/{solver_id}", dependencies=[Depends(require_session)])
    async def external_solver(solver_id: str) -> dict[str, Any]:
        try:
            return solver_status(solver_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown external solver: {solver_id}") from exc

    @app.post("/v6/chemistry/studies", dependencies=[Depends(require_session)])
    async def create_study(request: ChemistryStudyRequest) -> dict[str, Any]:
        try:
            if sync_graph is not None:
                sync_graph(reason="v600_chemistry_precreate")
            study = create_chemistry_study(request)
            return {"study": study, "release_claim": "controlled_external_solver_capability"}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown engineering identity: {exc.args[0]}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/chemistry/studies", dependencies=[Depends(require_session)])
    async def list_studies() -> dict[str, Any]:
        rows = chemistry_studies()
        return {"items": rows, "count": len(rows)}

    @app.post("/v6/chemistry/studies/{study_id}/run", dependencies=[Depends(require_session)])
    async def run_study(study_id: str) -> dict[str, Any]:
        try:
            if sync_graph is not None:
                sync_graph(reason="v600_chemistry_prerun")
            result = run_chemistry_study(study_id, graph)
            if sync_graph is not None:
                # Canonical design did not change; this synchronization preserves the
                # externally generated evidence and confirms its captured CAD fingerprint.
                sync_graph(reason="v600_chemistry_postrun")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown chemistry/engineering identity: {exc.args[0]}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/chemistry/runs", dependencies=[Depends(require_session)])
    async def list_runs(study_id: str | None = None) -> dict[str, Any]:
        rows = chemistry_runs(study_id)
        return {"items": rows, "count": len(rows), "study_id": study_id}

    _INSTALLED = True
