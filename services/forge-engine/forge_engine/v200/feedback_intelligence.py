from __future__ import annotations

"""Physical-outcome feedback for ForgeCAD 2.0 design intelligence.

A failed print or physical test is valuable engineering information, but it is not proof
of causality. This layer makes branch-local evidence visible to the planner, branch
comparison, and autonomous campaign reports while keeping those semantics explicit:

- evidence bound to the exact current design may satisfy qualitative gates;
- evidence from an ancestor/other revision is historical feedback only;
- differences between a failed and working branch are candidates for investigation,
  never automatically declared to be the cause of the failure.
"""

from copy import deepcopy
from types import MethodType
from typing import Any

from fastapi import Depends, HTTPException

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import design_intelligence, physical_evidence


_INSTALLED = False
_ORIGINAL_BUILD_CONTEXT = None
_ORIGINAL_COMPARE_BRANCH = None
_ORIGINAL_RUN_CAMPAIGN = None


def _state(branch: str) -> dict[str, Any]:
    if branch == core.ACTIVE_DESIGN:
        return core.PROJECT
    if branch not in core.BRANCHES:
        raise KeyError(branch)
    return core.BRANCHES[branch]


def _verification_status(requirement: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    evidence = [row for row in requirement.get("verification_evidence") or [] if isinstance(row, dict)]
    current = [row for row in evidence if str(row.get("design_fingerprint") or "") == fingerprint]
    latest = current[-1] if current else None
    return {
        "id": str(requirement.get("id") or ""),
        "statement": str(requirement.get("statement") or requirement.get("description") or ""),
        "status": str((latest or {}).get("status") or "unverified"),
        "method": (latest or {}).get("method"),
        "current_evidence_count": len(current),
        "historical_evidence_count": len(evidence) - len(current),
    }


def summarize_state(state: dict[str, Any], branch: str) -> dict[str, Any]:
    fingerprint = physical_evidence.design_fingerprint(state)
    evidence_rows = [
        deepcopy(row)
        for row in state.get("notebook", [])
        if isinstance(row, dict) and row.get("kind") in {"manufacturing_evidence", "requirement_verification"}
    ]
    current_rows: list[dict[str, Any]] = []
    historical_rows: list[dict[str, Any]] = []
    for row in evidence_rows:
        if str(row.get("design_fingerprint") or "") == fingerprint:
            current_rows.append(row)
        else:
            historical_rows.append(row)

    manufacturing = [row for row in evidence_rows if row.get("kind") == "manufacturing_evidence"]
    current_manufacturing = [row for row in manufacturing if str(row.get("design_fingerprint") or "") == fingerprint]
    outcome_counts = {name: 0 for name in ("success", "failure", "partial", "inconclusive")}
    for row in current_manufacturing:
        outcome = str(row.get("outcome") or "inconclusive")
        if outcome in outcome_counts:
            outcome_counts[outcome] += 1

    requirement_rows = [
        _verification_status(row, fingerprint)
        for row in state.get("requirements", [])
        if isinstance(row, dict)
    ]

    observations: list[dict[str, Any]] = []
    for row in reversed(manufacturing):
        binding = "current" if str(row.get("design_fingerprint") or "") == fingerprint else "historical"
        for observation in reversed(row.get("observations") or []):
            observations.append({
                "text": str(observation),
                "binding": binding,
                "outcome": str(row.get("outcome") or "inconclusive"),
                "evidence_id": str(row.get("id") or ""),
                "at": row.get("at"),
            })
            if len(observations) >= 12:
                break
        if len(observations) >= 12:
            break

    failed_requirement_history: list[dict[str, Any]] = []
    for requirement in state.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        for row in reversed(requirement.get("verification_evidence") or []):
            if not isinstance(row, dict) or str(row.get("status") or "") != "failed":
                continue
            failed_requirement_history.append({
                "requirement_id": str(requirement.get("id") or ""),
                "statement": str(requirement.get("statement") or requirement.get("description") or ""),
                "method": row.get("method"),
                "note": row.get("note"),
                "binding": "current" if str(row.get("design_fingerprint") or "") == fingerprint else "historical",
                "evidence_id": str(row.get("id") or ""),
                "at": row.get("at"),
            })
            if len(failed_requirement_history) >= 10:
                break
        if len(failed_requirement_history) >= 10:
            break

    return {
        "branch": branch,
        "design_fingerprint": fingerprint,
        "current_evidence_count": len(current_rows),
        "historical_evidence_count": len(historical_rows),
        "manufacturing_outcomes": outcome_counts,
        "requirements": requirement_rows,
        "observations": observations,
        "failed_requirement_history": failed_requirement_history,
        "latest_manufacturing": deepcopy(manufacturing[-1]) if manufacturing else None,
    }


def branch_feedback(branch: str) -> dict[str, Any]:
    state = _state(branch)
    summary = summarize_state(state, branch)
    meta = deepcopy(core.DESIGNS.get(branch) or {})
    return {
        **summary,
        "branch_status": str(meta.get("status") or "unverified"),
        "physical_verified": bool(meta.get("physical_verified")),
    }


def _planner_feedback() -> dict[str, Any]:
    active = branch_feedback(core.ACTIVE_DESIGN)
    known_good: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for branch, meta in core.DESIGNS.items():
        if branch == core.ACTIVE_DESIGN:
            continue
        status = str(meta.get("status") or "").lower()
        if bool(meta.get("physical_verified")) or status in {"working", "working_in_real_life"}:
            known_good.append(branch_feedback(branch))
        elif status in {"not_working", "failed"}:
            failed.append(branch_feedback(branch))
    return {
        "active": active,
        "known_working_branches": known_good[:6],
        "failed_branches": failed[:6],
        "interpretation_policy": (
            "Treat current evidence as observations tied to the exact current design fingerprint. "
            "Treat historical/other-branch evidence as redesign clues only. A difference between a failed and working branch is not causal proof; propose a test or analysis before attributing cause."
        ),
    }


def _build_context(text: str, architecture: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    assert _ORIGINAL_BUILD_CONTEXT is not None
    context = _ORIGINAL_BUILD_CONTEXT(text, architecture, project)
    context["physical_feedback"] = _planner_feedback()
    return context


def _requirement_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in summary.get("requirements") or [] if row.get("id")}


def _evidence_ids(state: dict[str, Any]) -> set[str]:
    return {
        str(row.get("id"))
        for row in state.get("notebook", [])
        if isinstance(row, dict) and row.get("kind") in {"manufacturing_evidence", "requirement_verification"} and row.get("id")
    }


def _compare_branch(self: EngineeringProject, name: str) -> dict[str, Any]:
    assert _ORIGINAL_COMPARE_BRANCH is not None
    base = _ORIGINAL_COMPARE_BRANCH(self, name)
    source_name = str(base.get("source") or core.ACTIVE_DESIGN)
    target_name = str(base.get("target") or name)
    source_state = _state(source_name)
    target_state = _state(target_name)
    source = summarize_state(source_state, source_name)
    target = summarize_state(target_state, target_name)

    source_requirements = _requirement_map(source)
    target_requirements = _requirement_map(target)
    requirement_differences: list[dict[str, Any]] = []
    for requirement_id in sorted(set(source_requirements) | set(target_requirements)):
        a = source_requirements.get(requirement_id)
        b = target_requirements.get(requirement_id)
        if a != b:
            requirement_differences.append({
                "requirement_id": requirement_id,
                "source": deepcopy(a),
                "target": deepcopy(b),
            })

    source_ids = _evidence_ids(source_state)
    target_ids = _evidence_ids(target_state)
    base["physical_evidence_comparison"] = {
        "source": source,
        "target": target,
        "requirement_differences": requirement_differences,
        "evidence_only_in_source": sorted(source_ids - target_ids),
        "evidence_only_in_target": sorted(target_ids - source_ids),
        "causality": "not_inferred",
        "note": "Physical-outcome differences are evidence for investigation, not automatic causal attribution.",
    }
    return base


def _run_campaign(self: EngineeringProject, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_RUN_CAMPAIGN is not None
    source_branch = core.ACTIVE_DESIGN
    source_feedback = branch_feedback(source_branch)
    # campaign_intelligence installs an instance-bound MethodType so it can coexist with
    # the legacy EngineeringProject class. Wrap that exact installed method; patching the
    # class here would be shadowed by the existing instance attribute.
    result = _ORIGINAL_RUN_CAMPAIGN(selected_object_id, payload)
    result["source_physical_feedback"] = source_feedback
    result["feedback_semantics"] = {
        "current_evidence_gates_exact_source_revision": True,
        "evidence_is_stale_after_candidate_geometry_changes": True,
        "historical_failures_are_redesign_clues_not_causal_proof": True,
    }
    return result


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_BUILD_CONTEXT, _ORIGINAL_COMPARE_BRANCH, _ORIGINAL_RUN_CAMPAIGN
    if _INSTALLED:
        return
    _ORIGINAL_BUILD_CONTEXT = design_intelligence.build_planner_context
    design_intelligence.build_planner_context = _build_context
    _ORIGINAL_COMPARE_BRANCH = EngineeringProject.compare_branch
    EngineeringProject.compare_branch = _compare_branch  # type: ignore[method-assign]
    _ORIGINAL_RUN_CAMPAIGN = legacy.PROJECT.run_campaign
    legacy.PROJECT.run_campaign = MethodType(_run_campaign, legacy.PROJECT)

    app = legacy.app

    @app.get("/v2/branches/{branch_name}/feedback", dependencies=[Depends(legacy.require_session)])
    async def get_branch_feedback(branch_name: str) -> dict[str, Any]:
        try:
            return branch_feedback(branch_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Branch not found") from exc

    _INSTALLED = True
