from __future__ import annotations

"""Revision-bound prediction-versus-observation diagnostics for milestone 5.

A physical result can disagree with a simulation for many reasons: model assumptions,
boundary conditions, material properties, manufacturing variation, instrumentation, or
test execution. This module freezes explicit numeric outputs from a current canonical
simulation before retest completion, then compares the corresponding physical
observations to those frozen predictions. A large residual is recorded as model/test
discrepancy evidence only; it is never treated as causal attribution or permission to
silently tune the model.
"""

from copy import deepcopy
import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..v110 import core
from ..v200.physical_evidence import design_fingerprint
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PredictionBinding(BaseModel):
    measurement: str = Field(min_length=1, max_length=128)
    object_id: str | None = None
    unit: str = Field(default="", max_length=64)
    simulation_id: str = Field(min_length=1, max_length=256)
    result_path: str = Field(min_length=1, max_length=512)
    max_abs_residual: float | None = Field(default=None, ge=0.0)
    max_relative_residual_fraction: float | None = Field(default=None, ge=0.0)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_error_budget(self) -> "PredictionBinding":
        if self.max_abs_residual is None and self.max_relative_residual_fraction is None:
            raise ValueError("Prediction binding requires max_abs_residual and/or max_relative_residual_fraction")
        return self


class PredictionResidualContractRequest(BaseModel):
    bindings: list[PredictionBinding] = Field(min_length=1, max_length=16)


def _cycle(cycle_id: str) -> dict[str, Any]:
    row = next(
        (item for item in core.PROJECT.get("physical_retest_cycles") or [] if str(item.get("id")) == cycle_id),
        None,
    )
    if row is None:
        raise KeyError(cycle_id)
    return row


def _assert_pending_current_cycle(cycle: dict[str, Any]) -> None:
    if cycle.get("status") != "pending_retest":
        raise ValueError(f"Prediction residual contract requires a pending retest cycle, got {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or ""):
        raise ValueError("Prediction residual contract must be locked on the redesign branch")
    expected = str(cycle.get("redesign_design_fingerprint") or "")
    if not expected or design_fingerprint() != expected:
        raise ValueError("Prediction residual contract rejected because the redesign fingerprint changed")


def _criterion_map(cycle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("measurement") or "").strip().casefold(): deepcopy(row)
        for row in cycle.get("test_criteria") or []
        if str(row.get("measurement") or "").strip()
    }


def _simulation(simulation_id: str) -> dict[str, Any]:
    row = next(
        (item for item in core.PROJECT.get("simulations") or [] if str(item.get("id")) == simulation_id),
        None,
    )
    if row is None:
        raise KeyError(simulation_id)
    return row


def _extract_numeric(root: Any, path: str) -> tuple[float, dict[str, Any] | None]:
    parts = [part for part in path.split(".") if part]
    if not parts:
        raise ValueError("Prediction result_path cannot be empty")
    current = root
    parent = None
    for part in parts:
        parent = current if isinstance(current, dict) else None
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"Prediction result_path {path!r} does not exist in the simulation result")
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index < 0 or index >= len(current):
                raise ValueError(f"Prediction result_path {path!r} indexes outside the simulation result")
            current = current[index]
        else:
            raise ValueError(f"Prediction result_path {path!r} cannot traverse component {part!r}")
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        raise ValueError(f"Prediction result_path {path!r} must resolve to a numeric scalar")
    value = float(current)
    if not math.isfinite(value):
        raise ValueError(f"Prediction result_path {path!r} resolved to a non-finite value")
    return value, parent if isinstance(parent, dict) else None


def set_prediction_residual_contract(
    cycle_id: str,
    request: PredictionResidualContractRequest,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("prediction_residual_contract"):
        raise ValueError("Prediction residual contract is already locked for this retest cycle")
    criteria = _criterion_map(cycle)
    seen: set[str] = set()
    frozen: list[dict[str, Any]] = []
    for binding in request.bindings:
        key = binding.measurement.strip().casefold()
        if key in seen:
            raise ValueError(f"Prediction binding for measurement {binding.measurement!r} is duplicated")
        seen.add(key)
        criterion = criteria.get(key)
        if criterion is None:
            raise ValueError(f"Prediction binding measurement {binding.measurement!r} is not a retest criterion")
        object_id = str(binding.object_id or criterion.get("object_id") or "")
        if not object_id:
            raise ValueError(f"Prediction binding {binding.measurement!r} requires an object_id")
        if object_id != str(criterion.get("object_id") or ""):
            raise ValueError(f"Prediction binding {binding.measurement!r} targets a different CAD object than its physical criterion")
        core.object_by_id(object_id)
        expected_unit = str(criterion.get("unit") or "").strip()
        if binding.unit.strip().casefold() != expected_unit.casefold():
            raise ValueError(
                f"Prediction binding {binding.measurement!r} uses unit {binding.unit!r}; physical criterion requires {expected_unit!r}"
            )
        try:
            simulation = _simulation(binding.simulation_id)
        except KeyError as exc:
            raise ValueError(f"Unknown canonical simulation {binding.simulation_id!r}") from exc
        if bool(simulation.get("stale")):
            raise ValueError(f"Prediction binding cannot use stale simulation {binding.simulation_id!r}")
        if str(simulation.get("design") or "") != core.ACTIVE_DESIGN:
            raise ValueError(f"Prediction simulation {binding.simulation_id!r} belongs to a different design branch")
        sim_object_id = str(simulation.get("object_id") or "")
        if sim_object_id and sim_object_id != object_id:
            raise ValueError(
                f"Prediction simulation {binding.simulation_id!r} targets object {sim_object_id}, not criterion object {object_id}"
            )
        predicted, parent = _extract_numeric(simulation.get("result") or {}, binding.result_path)
        solver_metadata = {}
        if isinstance(parent, dict):
            for metadata_key in ("solver", "solver_version", "solver_grade", "method", "limitations", "provenance"):
                if metadata_key in parent:
                    solver_metadata[metadata_key] = deepcopy(parent[metadata_key])
        frozen.append({
            "measurement": binding.measurement.strip(),
            "object_id": object_id,
            "unit": binding.unit.strip(),
            "simulation_id": str(simulation["id"]),
            "simulation_kind": simulation.get("kind"),
            "simulation_record_sha256": _canonical_sha(simulation),
            "simulation_result_path": binding.result_path,
            "predicted_value": predicted,
            "max_abs_residual": binding.max_abs_residual,
            "max_relative_residual_fraction": binding.max_relative_residual_fraction,
            "solver_metadata": solver_metadata,
            "note": binding.note,
            "design_fingerprint": design_fingerprint(),
            "interpretation_policy": "prediction snapshot for later comparison; not physical evidence",
        })
    contract = {
        "design_fingerprint": design_fingerprint(),
        "bindings": frozen,
        "causality_policy": "residual magnitude can identify disagreement but cannot establish why prediction and observation differ",
        "automatic_model_tuning": False,
    }
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["prediction_residual_contract"] = deepcopy(contract)
        cycle["prediction_residual_ids"] = []
        core.push_history(
            "v6 physical prediction residual contract",
            "human",
            f"locked {len(frozen)} simulation-to-observation comparison(s) for cycle {cycle_id}",
        )
        core.persist()
    return {"ok": True, "cycle_id": cycle_id, "locked": True, "contract": deepcopy(contract)}


def prediction_residual_contract(cycle_id: str) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    return {
        "cycle_id": cycle_id,
        "contract": deepcopy(cycle.get("prediction_residual_contract")),
        "items": [
            deepcopy(row)
            for row in core.PROJECT.get("physical_prediction_residuals") or []
            if str(row.get("cycle_id")) == cycle_id
        ],
    }


def _residual_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    return EngineeringEvidence(
        id=f"physical-prediction-residual:{row['id']}",
        kind="physical_prediction_residual",
        subject_node_ids=[f"cad:{row['object_id']}"],
        requirement_ids=[str(row.get("requirement_id"))] if row.get("requirement_id") else [],
        value=float(row["residual"]),
        unit=str(row.get("unit") or ""),
        status=str(row.get("status") or "informational"),
        method="simulation_vs_physical_observation",
        source_ids=[
            str(row.get("simulation_id") or ""),
            *[str(value) for value in row.get("inspection_ids") or []],
        ],
        assumptions=[
            "the declared unit mapping between simulation output and physical criterion is correct",
            "residual magnitude does not identify whether disagreement comes from model assumptions, manufacturing, instrumentation, environment, or test execution",
            "ForgeCAD does not automatically tune a model from this residual",
        ],
        confidence=0.9,
        metadata=deepcopy(row),
    )


def evaluate_prediction_residuals(
    cycle_id: str,
    criterion_results: list[dict[str, Any]],
    graph: EngineeringGraphStore,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    contract = deepcopy(cycle.get("prediction_residual_contract") or {})
    if not contract:
        return {"required": False, "items": [], "count": 0, "discrepancy_count": 0}
    expected = str(cycle.get("retest_design_fingerprint") or cycle.get("redesign_design_fingerprint") or "")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or "") or design_fingerprint() != expected:
        raise ValueError("Prediction residual evaluation requires the exact redesign fingerprint that was physically tested")
    if str(contract.get("design_fingerprint") or "") != expected:
        raise ValueError("Prediction residual contract belongs to a different engineering fingerprint")
    by_measurement = {
        str(row.get("measurement") or "").strip().casefold(): row
        for row in criterion_results
    }
    inspection_ids = [str(row) for row in cycle.get("inspection_ids") or []]
    prepared: list[dict[str, Any]] = []
    for binding in contract.get("bindings") or []:
        key = str(binding.get("measurement") or "").strip().casefold()
        observed_row = by_measurement.get(key)
        if observed_row is None or observed_row.get("value") is None:
            raise ValueError(f"Physical observation for prediction binding {binding.get('measurement')!r} is unavailable")
        predicted = float(binding["predicted_value"])
        observed = float(observed_row["value"])
        residual = observed - predicted
        absolute = abs(residual)
        relative = absolute / max(abs(predicted), 1e-12)
        checks: list[dict[str, Any]] = []
        if binding.get("max_abs_residual") is not None:
            limit = float(binding["max_abs_residual"])
            checks.append({"kind": "absolute", "value": absolute, "limit": limit, "within": absolute <= limit})
        if binding.get("max_relative_residual_fraction") is not None:
            limit = float(binding["max_relative_residual_fraction"])
            checks.append({"kind": "relative_fraction", "value": relative, "limit": limit, "within": relative <= limit})
        within = bool(checks) and all(bool(row["within"]) for row in checks)
        record = {
            "id": core.uid(),
            "kind": "physical_prediction_residual",
            "cycle_id": cycle_id,
            "requirement_id": str(cycle.get("requirement_id") or ""),
            "branch": core.ACTIVE_DESIGN,
            "design_fingerprint": expected,
            "measurement": binding.get("measurement"),
            "object_id": binding.get("object_id"),
            "unit": binding.get("unit"),
            "simulation_id": binding.get("simulation_id"),
            "simulation_kind": binding.get("simulation_kind"),
            "simulation_record_sha256": binding.get("simulation_record_sha256"),
            "simulation_result_path": binding.get("simulation_result_path"),
            "solver_metadata": deepcopy(binding.get("solver_metadata") or {}),
            "predicted_value": predicted,
            "observed_value": observed,
            "residual": residual,
            "absolute_residual": absolute,
            "relative_residual_fraction": relative,
            "error_budget_checks": checks,
            "status": "within_declared_model_error_budget" if within else "model_test_discrepancy",
            "within_declared_model_error_budget": within,
            "inspection_ids": inspection_ids,
            "causality_status": "unattributed_discrepancy",
            "automatic_model_tuning": False,
            "physical_evidence": True,
        }
        prepared.append(record)

    evidence_rows: list[dict[str, Any]] = []
    with core.LOCK:
        collection = core.PROJECT.setdefault("physical_prediction_residuals", [])
        collection.extend(deepcopy(prepared))
        cycle = _cycle(cycle_id)
        cycle["prediction_residual_ids"] = [str(row["id"]) for row in prepared]
        core.push_history(
            "v6 physical prediction residuals",
            "forgecad",
            f"compared {len(prepared)} physical observation(s) with frozen simulation predictions for cycle {cycle_id}",
        )
        core.persist()
    for row in prepared:
        evidence_rows.append(graph.add_evidence(_residual_evidence(row)).model_dump(mode="json"))
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["prediction_residual_evidence_ids"] = [str(row["id"]) for row in evidence_rows]
        core.persist()
    return {
        "required": True,
        "items": deepcopy(prepared),
        "count": len(prepared),
        "discrepancy_count": sum(row["status"] == "model_test_discrepancy" for row in prepared),
        "all_within_declared_model_error_budget": all(bool(row["within_declared_model_error_budget"]) for row in prepared),
        "graph_evidence": evidence_rows,
        "causality_policy": contract.get("causality_policy"),
        "automatic_model_tuning": False,
    }
