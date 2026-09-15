from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 milestone 5 physical feedback lineage."""

from typing import Any, Callable

from fastapi import Depends, HTTPException

from .physical_artifacts import (
    PhysicalArtifactContractRequest,
    PhysicalArtifactSubmissionRequest,
    artifact_evidence_ids,
    assert_artifact_contract_satisfied,
    link_cycle_artifacts_to_inspections,
    physical_test_artifacts,
    set_artifact_contract,
    submit_artifacts,
)
from .physical_retest import (
    BeginPhysicalRetestCycleRequest,
    CompletePhysicalRetestRequest,
    begin_physical_retest_cycle,
    complete_physical_retest_cycle,
    physical_retest_cycles,
    physical_retest_lineage,
)


_INSTALLED = False


def install(
    app: Any,
    require_session: Callable[..., None],
    graph: Any | None = None,
    sync_graph: Callable[..., dict[str, Any]] | None = None,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.post("/v6/physical/retest-cycles", dependencies=[Depends(require_session)])
    async def begin_retest(request: BeginPhysicalRetestCycleRequest) -> dict[str, Any]:
        try:
            result = begin_physical_retest_cycle(request)
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_physical_retest_redesign")
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/artifact-contract", dependencies=[Depends(require_session)])
    async def lock_artifact_contract(cycle_id: str, request: PhysicalArtifactContractRequest) -> dict[str, Any]:
        try:
            return set_artifact_contract(cycle_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/artifacts", dependencies=[Depends(require_session)])
    async def submit_retest_artifacts(cycle_id: str, request: PhysicalArtifactSubmissionRequest) -> dict[str, Any]:
        try:
            if graph is None:
                raise ValueError("Engineering graph is required for physical artifact evidence")
            if sync_graph is not None:
                sync_graph(reason="v600_physical_artifact_presubmit")
            result = submit_artifacts(cycle_id, request, graph)
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles/{cycle_id}/artifacts", dependencies=[Depends(require_session)])
    async def list_retest_artifacts(cycle_id: str) -> dict[str, Any]:
        return physical_test_artifacts(cycle_id)

    @app.post("/v6/physical/retest-cycles/{cycle_id}/complete", dependencies=[Depends(require_session)])
    async def complete_retest(cycle_id: str, request: CompletePhysicalRetestRequest) -> dict[str, Any]:
        try:
            artifacts = assert_artifact_contract_satisfied(cycle_id)
            artifact_evidence = artifact_evidence_ids(cycle_id)
            effective_request = request.model_copy(
                update={"evidence_ids": [*request.evidence_ids, *[row for row in artifact_evidence if row not in request.evidence_ids]]}
            )
            if sync_graph is not None:
                sync_graph(reason="v600_physical_retest_precomplete")
            result = complete_physical_retest_cycle(cycle_id, effective_request, graph=graph)
            inspection_ids = [str(row) for row in result.get("cycle", {}).get("inspection_ids") or []]
            if artifacts and graph is not None:
                result["artifacts"] = link_cycle_artifacts_to_inspections(cycle_id, inspection_ids, graph)
            else:
                result["artifacts"] = artifacts
            if sync_graph is not None:
                result["graph_sync"] = sync_graph(reason="v600_physical_retest_complete")
            return result
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
