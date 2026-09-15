from __future__ import annotations

"""HTTP surface for ForgeCAD 6.0 milestone 5 physical feedback lineage."""

from typing import Any, Callable

from fastapi import Depends, HTTPException, Response

from ..v200.physical_evidence import Measurement
from ..v310.fabrication_archive import MIME_TYPE as FABRICATION_MIME_TYPE
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
from .physical_metrology import (
    MetrologyContractRequest,
    MetrologySubmissionRequest,
    assert_metrology_contract_satisfied,
    link_metrology_to_inspections,
    physical_metrology,
    set_metrology_contract,
    submit_metrology,
)
from .physical_specimen_contract import (
    PhysicalSpecimenContractRequest,
    attach_specimen_lineage_to_runs,
    refresh_specimen_linked_run_evidence,
    set_specimen_contract,
    validate_run_specimens,
)
from .physical_specimens import (
    PhysicalFabricationPackageRequest,
    PhysicalSpecimenRegistrationRequest,
    generate_fabrication_package,
    physical_fabrication_packages,
    physical_specimens,
    register_specimen,
)
from .physical_test_execution import (
    PhysicalTestExecutionContractRequest,
    PhysicalTestRunSubmissionRequest,
    assert_execution_contract_satisfied,
    link_test_runs_to_inspections,
    physical_test_execution,
    set_execution_contract,
    submit_test_runs,
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
            return submit_artifacts(cycle_id, request, graph)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles/{cycle_id}/artifacts", dependencies=[Depends(require_session)])
    async def list_retest_artifacts(cycle_id: str) -> dict[str, Any]:
        return physical_test_artifacts(cycle_id)

    @app.post("/v6/physical/retest-cycles/{cycle_id}/metrology-contract", dependencies=[Depends(require_session)])
    async def lock_metrology_contract(cycle_id: str, request: MetrologyContractRequest) -> dict[str, Any]:
        try:
            return set_metrology_contract(cycle_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/metrology", dependencies=[Depends(require_session)])
    async def submit_retest_metrology(cycle_id: str, request: MetrologySubmissionRequest) -> dict[str, Any]:
        try:
            if graph is None:
                raise ValueError("Engineering graph is required for physical metrology evidence")
            if sync_graph is not None:
                sync_graph(reason="v600_physical_metrology_presubmit")
            return submit_metrology(cycle_id, request, graph)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles/{cycle_id}/metrology", dependencies=[Depends(require_session)])
    async def list_retest_metrology(cycle_id: str) -> dict[str, Any]:
        return physical_metrology(cycle_id)

    @app.post("/v6/physical/retest-cycles/{cycle_id}/fabrication-package", dependencies=[Depends(require_session)])
    async def create_retest_fabrication_package(cycle_id: str, request: PhysicalFabricationPackageRequest) -> Response:
        try:
            if graph is None:
                raise ValueError("Engineering graph is required for physical fabrication package lineage")
            if sync_graph is not None:
                sync_graph(reason="v600_physical_package_pregenerate")
            data, result = generate_fabrication_package(cycle_id, request, graph)
            record = result["record"]
            if sync_graph is not None:
                sync_graph(reason="v600_physical_package_generated")
            filename = str(record.get("filename") or "physical-test.forgefab.zip").replace('"', "")
            return Response(
                data,
                media_type=FABRICATION_MIME_TYPE,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "X-ForgeCAD-Physical-Package-ID": str(record["id"]),
                    "X-ForgeCAD-Fabrication-SHA256": str(record["archive_sha256"]),
                    "X-ForgeCAD-Graph-Revision": str(record.get("engineering_graph_revision") or ""),
                    "X-ForgeCAD-Design-Fingerprint": str(record["design_fingerprint"]),
                },
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles/{cycle_id}/fabrication-packages", dependencies=[Depends(require_session)])
    async def list_retest_fabrication_packages(cycle_id: str) -> dict[str, Any]:
        try:
            return physical_fabrication_packages(cycle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/specimens", dependencies=[Depends(require_session)])
    async def register_retest_specimen(cycle_id: str, request: PhysicalSpecimenRegistrationRequest) -> dict[str, Any]:
        try:
            if graph is None:
                raise ValueError("Engineering graph is required for physical specimen lineage")
            if sync_graph is not None:
                sync_graph(reason="v600_physical_specimen_preregister")
            return register_specimen(cycle_id, request, graph)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles/{cycle_id}/specimens", dependencies=[Depends(require_session)])
    async def list_retest_specimens(cycle_id: str) -> dict[str, Any]:
        try:
            return physical_specimens(cycle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/specimen-contract", dependencies=[Depends(require_session)])
    async def lock_specimen_contract(cycle_id: str, request: PhysicalSpecimenContractRequest) -> dict[str, Any]:
        try:
            return set_specimen_contract(cycle_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/execution-contract", dependencies=[Depends(require_session)])
    async def lock_execution_contract(cycle_id: str, request: PhysicalTestExecutionContractRequest) -> dict[str, Any]:
        try:
            return set_execution_contract(cycle_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/test-runs", dependencies=[Depends(require_session)])
    async def submit_retest_runs(cycle_id: str, request: PhysicalTestRunSubmissionRequest) -> dict[str, Any]:
        try:
            if graph is None:
                raise ValueError("Engineering graph is required for physical test-run evidence")
            if sync_graph is not None:
                sync_graph(reason="v600_physical_test_run_presubmit")
            specimen_lineage = validate_run_specimens(cycle_id, [row.specimen_id for row in request.runs])
            result = submit_test_runs(cycle_id, request, graph)
            if specimen_lineage:
                enriched = attach_specimen_lineage_to_runs(cycle_id, result.get("items") or [], specimen_lineage, graph)
                result["items"] = enriched
                evidence_ids = {f"physical-test-run:{row['id']}" for row in enriched}
                result["graph_evidence"] = [
                    row.model_dump(mode="json")
                    for row in graph.evidence()
                    if row.id in evidence_ids
                ]
                result["specimen_lineage_applied"] = True
            else:
                result["specimen_lineage_applied"] = False
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest/engineering identity: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v6/physical/retest-cycles/{cycle_id}/test-runs", dependencies=[Depends(require_session)])
    async def list_retest_runs(cycle_id: str) -> dict[str, Any]:
        try:
            return physical_test_execution(cycle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown retest identity: {exc.args[0]}") from exc

    @app.post("/v6/physical/retest-cycles/{cycle_id}/complete", dependencies=[Depends(require_session)])
    async def complete_retest(cycle_id: str, request: CompletePhysicalRetestRequest) -> dict[str, Any]:
        try:
            cycle_rows = physical_retest_cycles()["items"]
            cycle = next((row for row in cycle_rows if str(row.get("id")) == cycle_id), None)
            if cycle is None:
                raise KeyError(cycle_id)
            # All M5 evidence-quality contracts are opt-in and additive. A cycle that
            # never locked one follows the previously validated completion behavior.
            if cycle.get("artifact_requirements"):
                artifacts = assert_artifact_contract_satisfied(cycle_id)
            else:
                artifacts = physical_test_artifacts(cycle_id)["items"]

            if cycle.get("physical_test_execution_contract"):
                if request.measurements:
                    raise ValueError(
                        "Physical test execution contract derives completion measurements from recorded runs; omit manual completion measurements"
                    )
                execution = assert_execution_contract_satisfied(cycle_id)
                completion_measurements = [
                    Measurement.model_validate(row)
                    for row in execution.get("derived_measurements") or []
                ]
            else:
                execution = {
                    "required": False,
                    "derived_measurements": [],
                    "criterion_results": [],
                    "evidence_ids": [],
                    "run_ids": [],
                }
                completion_measurements = list(request.measurements)

            if cycle.get("metrology_requirements"):
                metrology = assert_metrology_contract_satisfied(cycle_id, completion_measurements)
            else:
                metrology = {
                    "required": False,
                    "results": [],
                    "evidence_ids": [],
                    "record_ids": [],
                }

            extra_evidence = [
                *artifact_evidence_ids(cycle_id),
                *[str(row) for row in execution.get("evidence_ids") or []],
                *[str(row) for row in metrology.get("evidence_ids") or []],
            ]
            effective_request = request.model_copy(
                update={
                    "measurements": completion_measurements,
                    "evidence_ids": [
                        *request.evidence_ids,
                        *[row for row in extra_evidence if row not in request.evidence_ids],
                    ],
                }
            )
            if sync_graph is not None:
                sync_graph(reason="v600_physical_retest_precomplete")
            result = complete_physical_retest_cycle(cycle_id, effective_request, graph=graph)
            inspection_ids = [str(row) for row in result.get("cycle", {}).get("inspection_ids") or []]
            if artifacts and graph is not None:
                result["artifacts"] = link_cycle_artifacts_to_inspections(cycle_id, inspection_ids, graph)
            else:
                result["artifacts"] = artifacts
            if execution.get("required") and graph is not None:
                result["test_runs"] = link_test_runs_to_inspections(cycle_id, inspection_ids, graph)
                enriched_runs = refresh_specimen_linked_run_evidence(cycle_id, graph)
                if enriched_runs:
                    result["test_runs"] = enriched_runs
            else:
                result["test_runs"] = physical_test_execution(cycle_id)["items"]
            if metrology.get("required") and graph is not None:
                result["metrology_records"] = link_metrology_to_inspections(cycle_id, inspection_ids, graph)
            else:
                result["metrology_records"] = physical_metrology(cycle_id)["items"]
            result["test_execution_evaluation"] = execution
            result["metrology_evaluation"] = metrology
            result["specimen_lineage"] = physical_specimens(cycle_id)
            result["fabrication_packages"] = physical_fabrication_packages(cycle_id)
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
