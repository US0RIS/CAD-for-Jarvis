from __future__ import annotations

"""Milestone-4 bounded multi-strategy engineering repair.

This is controlled autonomy, not unrestricted design mutation. ForgeCAD evaluates
only explicitly authorized strategies, each on its own branch, against the same
canonical target requirement and guardrails. Rejected branches and their evidence
remain inspectable. Selection is deterministic and transparent: the lowest explicit
change-cost passing strategy wins, with stable strategy order as the tie-breaker.
"""

from copy import deepcopy
from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, Field

from ..v110 import core
from ..v310.engineering_graph import EngineeringGraphStore
from ..v310.integration_services import apply_substitution, semantic_branch_diff, synchronize_graph, verify_requirements
from .analysis_refresh_repair import AnalysisRefreshingRepairRequest, run_analysis_refreshing_repair


class ParametricStrategy(BaseModel):
    id: str
    kind: Literal["analysis_refresh_parametric"] = "analysis_refresh_parametric"
    change_cost: float = Field(default=1.0, ge=0.0, le=1000.0)
    repair: AnalysisRefreshingRepairRequest


class ComponentSubstitutionStrategy(BaseModel):
    id: str
    kind: Literal["component_substitution"] = "component_substitution"
    change_cost: float = Field(default=1.0, ge=0.0, le=1000.0)
    object_id: str
    allowed_component_ids: list[str] = Field(min_length=1, max_length=12)
    actor: Literal["jarvis", "forgecad", "human"] = "jarvis"


RepairStrategy = Annotated[Union[ParametricStrategy, ComponentSubstitutionStrategy], Field(discriminator="kind")]


class AutonomousRepairRequest(BaseModel):
    requirement_id: str
    guardrail_requirement_ids: list[str] = Field(default_factory=list, max_length=24)
    strategies: list[RepairStrategy] = Field(min_length=2, max_length=8)
    branch_prefix: str = "bounded-autonomous-repair"


def _snapshot() -> dict[str, Any]:
    return {
        "name": str(core.PROJECT.get("name") or "ForgeCAD Project"),
        "revision": f"{core.ACTIVE_DESIGN}:{len(core.PROJECT.get('ledger', []))}:{core.PROJECT.get('updated_at', '')}",
        "active_branch": core.ACTIVE_DESIGN,
        "metrics": core.project_metrics(),
    }


def _sync(graph: EngineeringGraphStore, world: Any | None) -> None:
    synchronize_graph(graph, _snapshot(), world)


def _verification(graph: EngineeringGraphStore, ids: set[str]) -> dict[str, dict[str, Any]]:
    result = verify_requirements(graph)
    rows = {str(row["requirement"].get("id")): row for row in result["items"] if str(row["requirement"].get("id")) in ids}
    missing = ids - set(rows)
    if missing:
        raise KeyError(", ".join(sorted(missing)))
    return rows


def _state(rows: dict[str, dict[str, Any]], target: str, guardrails: list[str]) -> dict[str, Any]:
    target_row = deepcopy(rows[target])
    guard_rows = [deepcopy(rows[rid]) for rid in guardrails]
    failed = [row for row in guard_rows if row["status"] == "fail"]
    unknown = [row for row in guard_rows if row["status"] == "unknown"]
    return {
        "target": target_row,
        "guardrails": guard_rows,
        "guardrails_ok": not failed and not unknown,
        "passed": target_row["status"] == "pass" and not failed and not unknown,
        "failed_guardrail_ids": [str(row["requirement"].get("id")) for row in failed],
        "unknown_guardrail_ids": [str(row["requirement"].get("id")) for row in unknown],
    }


def _validate_strategy_contract(request: AutonomousRepairRequest) -> None:
    ids = [strategy.id for strategy in request.strategies]
    if len(ids) != len(set(ids)):
        raise ValueError("Autonomous repair strategy IDs must be unique")
    if request.requirement_id in request.guardrail_requirement_ids:
        raise ValueError("Target requirement cannot also be a guardrail")
    if len(request.guardrail_requirement_ids) != len(set(request.guardrail_requirement_ids)):
        raise ValueError("Guardrail requirement IDs must be unique")
    for strategy in request.strategies:
        if isinstance(strategy, ParametricStrategy):
            if strategy.repair.requirement_id != request.requirement_id:
                raise ValueError(f"Strategy {strategy.id} targets a different requirement")
            if strategy.repair.guardrail_requirement_ids != request.guardrail_requirement_ids:
                raise ValueError(f"Strategy {strategy.id} must use the exact autonomous-loop guardrails")


def _evaluate_substitution(
    graph: EngineeringGraphStore,
    world: Any | None,
    request: AutonomousRepairRequest,
    strategy: ComponentSubstitutionStrategy,
    baseline_branch: str,
    strategy_index: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    selected_ids = {request.requirement_id, *request.guardrail_requirement_ids}
    for candidate_index, component_id in enumerate(strategy.allowed_component_ids):
        core.switch_branch(baseline_branch)
        core.create_branch(
            f"{request.branch_prefix}-{strategy.id}-{candidate_index + 1}",
            reason=f"Bounded autonomous substitution candidate {strategy.id}: {component_id}",
            prefix=f"{request.branch_prefix}-{strategy.id}-{candidate_index + 1}",
        )
        branch = core.ACTIVE_DESIGN
        try:
            change = apply_substitution(strategy.object_id, component_id, graph, actor=strategy.actor, reason=f"milestone 4 strategy {strategy.id}")
            stale_count = int(core.mark_simulations_stale(strategy.object_id))
            core.persist()
            _sync(graph, world)
            rows = _verification(graph, selected_ids)
            state = _state(rows, request.requirement_id, request.guardrail_requirement_ids)
            accepted = bool(change.get("ok")) and state["passed"]
            error = None
        except (KeyError, ValueError) as exc:
            change = None
            stale_count = 0
            state = None
            accepted = False
            error = str(exc)
        diff = semantic_branch_diff(baseline_branch, branch)
        results.append({
            "strategy_id": strategy.id,
            "strategy_kind": strategy.kind,
            "strategy_index": strategy_index,
            "candidate_index": candidate_index,
            "candidate_component_id": component_id,
            "branch": branch,
            "accepted": accepted,
            "selection_cost": float(strategy.change_cost) + 1.0,
            "declared_change_cost": float(strategy.change_cost),
            "change": deepcopy(change),
            "stale_simulation_count": stale_count,
            "verification": deepcopy(state),
            "error": error,
            "semantic_diff": diff,
        })
    return results


def run_bounded_autonomous_repair(
    graph: EngineeringGraphStore,
    world: Any | None,
    request: AutonomousRepairRequest,
) -> dict[str, Any]:
    _validate_strategy_contract(request)
    selected_ids = {request.requirement_id, *request.guardrail_requirement_ids}
    baseline_branch = core.ACTIVE_DESIGN
    _sync(graph, world)
    baseline_rows = _verification(graph, selected_ids)
    baseline_state = _state(baseline_rows, request.requirement_id, request.guardrail_requirement_ids)
    if baseline_state["target"]["status"] == "unknown":
        raise ValueError("Autonomous repair is blocked because target evidence is unknown")
    if not baseline_state["guardrails_ok"]:
        raise ValueError("Autonomous repair is blocked because baseline guardrails are not all passing")
    if baseline_state["target"]["status"] == "pass":
        return {"ok": True, "status": "already_satisfied", "baseline_branch": baseline_branch, "selected": None, "candidates": []}

    candidates: list[dict[str, Any]] = []
    for strategy_index, strategy in enumerate(request.strategies):
        core.switch_branch(baseline_branch)
        if isinstance(strategy, ParametricStrategy):
            try:
                outcome = run_analysis_refreshing_repair(graph, world, strategy.repair)
                branch = str(outcome.get("repair_branch") or core.ACTIVE_DESIGN)
                accepted = bool(outcome.get("ok"))
                normalized_change = None
                if outcome.get("winner") is not None:
                    normalized_change = float(outcome["winner"].get("normalized_change", 0.0))
                selection_cost = float(strategy.change_cost) + (normalized_change if normalized_change is not None else 100.0)
                candidates.append({
                    "strategy_id": strategy.id,
                    "strategy_kind": strategy.kind,
                    "strategy_index": strategy_index,
                    "candidate_index": 0,
                    "branch": branch,
                    "accepted": accepted,
                    "selection_cost": selection_cost,
                    "declared_change_cost": float(strategy.change_cost),
                    "normalized_parametric_change": normalized_change,
                    "outcome": deepcopy(outcome),
                    "error": None,
                    "semantic_diff": outcome.get("semantic_diff"),
                })
            except (KeyError, ValueError) as exc:
                candidates.append({
                    "strategy_id": strategy.id,
                    "strategy_kind": strategy.kind,
                    "strategy_index": strategy_index,
                    "candidate_index": 0,
                    "branch": core.ACTIVE_DESIGN,
                    "accepted": False,
                    "selection_cost": float(strategy.change_cost) + 100.0,
                    "declared_change_cost": float(strategy.change_cost),
                    "outcome": None,
                    "error": str(exc),
                    "semantic_diff": None,
                })
        else:
            candidates.extend(_evaluate_substitution(graph, world, request, strategy, baseline_branch, strategy_index))

    passing = [row for row in candidates if row["accepted"]]
    if not passing:
        core.switch_branch(baseline_branch)
        _sync(graph, world)
        return {
            "ok": False,
            "status": "no_authorized_strategy_satisfied_requirements",
            "baseline_branch": baseline_branch,
            "selected": None,
            "candidates": candidates,
            "physical_validation_claimed": False,
        }

    passing.sort(key=lambda row: (float(row["selection_cost"]), int(row["strategy_index"]), int(row.get("candidate_index", 0)), str(row["strategy_id"])))
    selected = passing[0]
    core.switch_branch(str(selected["branch"]))
    _sync(graph, world)
    final_rows = _verification(graph, selected_ids)
    final_state = _state(final_rows, request.requirement_id, request.guardrail_requirement_ids)
    if not final_state["passed"]:
        raise RuntimeError("Selected autonomous repair branch did not survive final canonical re-verification")

    record = {
        "schema": "forgecad-bounded-autonomous-repair/1",
        "milestone": 4,
        "baseline_branch": baseline_branch,
        "selected_branch": core.ACTIVE_DESIGN,
        "requirement_id": request.requirement_id,
        "guardrail_requirement_ids": list(request.guardrail_requirement_ids),
        "selected_strategy_id": selected["strategy_id"],
        "selected_strategy_kind": selected["strategy_kind"],
        "selection_cost": selected["selection_cost"],
        "candidate_count": len(candidates),
        "passing_candidate_count": len(passing),
        "physical_validation_claimed": False,
    }
    with core.LOCK:
        core.PROJECT.setdefault("engineering_trials", []).append(deepcopy(record))
        core.DESIGNS.setdefault(core.ACTIVE_DESIGN, {})["analysis_status"] = "bounded_autonomous_repair_passed"
        core.DESIGNS[core.ACTIVE_DESIGN]["physical_verified"] = False
        core.push_history("v6 bounded autonomous repair selected", "jarvis", f"selected strategy {selected['strategy_id']}")
        core.persist()

    return {
        "ok": True,
        "status": "authorized_strategy_selected",
        "baseline_branch": baseline_branch,
        "selected": deepcopy(selected),
        "candidates": candidates,
        "final_verification": final_state,
        "selection_policy": "lowest explicit change cost; stable strategy/candidate order tie-break; only passing canonical requirements eligible",
        "physical_validation_claimed": False,
    }
