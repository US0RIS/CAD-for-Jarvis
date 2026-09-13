from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 physical-outcome feedback intelligence."""

from ..engineering_state import PROJECT
from ..v110 import core
from . import design_intelligence, feedback_intelligence, physical_evidence


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Latch beam",
            "kind": "box",
            "params": {"x": 70.0, "y": 18.0, "z": 8.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "latch", "tags": ["fabricated", "feedback-selftest"]},
        },
        actor="human",
        reason="Create feedback-loop fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    PROJECT.execute(
        "set_requirement",
        {
            "id": "R-LATCH",
            "statement": "Latch must engage reliably in the physical fixture.",
            "priority": "must",
            "verification": "Install prototype and cycle the latch.",
        },
        actor="human",
        reason="Create physical latch requirement",
    )

    baseline_print = physical_evidence.record_manufacturing_evidence(
        physical_evidence.ManufacturingEvidenceRequest(
            outcome="success",
            resource_id="bambu-lab-p2s",
            material="PETG",
            observations=["Baseline latch installed without rework."],
        )
    )
    physical_evidence.verify_requirement(
        "R-LATCH",
        physical_evidence.RequirementEvidenceRequest(
            status="passed",
            method="physical cycle test",
            note="Baseline completed 20 cycles.",
            evidence_ids=[baseline_print["id"]],
        ),
    )
    PROJECT.set_branch_status("main", "working", "Known-good physical baseline", True)

    PROJECT.create_branch("failed-latch-variant", "Test a thinner latch")
    failed_branch = core.ACTIVE_DESIGN
    PROJECT.execute(
        "update",
        {"id": object_id, "params": {"x": 70.0, "y": 18.0, "z": 5.0}},
        actor="human",
        reason="Thin latch for failed physical experiment",
    )
    failed_print = physical_evidence.record_manufacturing_evidence(
        physical_evidence.ManufacturingEvidenceRequest(
            outcome="failure",
            resource_id="bambu-lab-p2s",
            material="PETG",
            observations=["Latch flexed visibly and skipped the catch on load."],
            note="Failed physical prototype",
        )
    )
    physical_evidence.verify_requirement(
        "R-LATCH",
        physical_evidence.RequirementEvidenceRequest(
            status="failed",
            method="physical cycle test",
            note="Missed engagement on cycle 3 under load.",
            evidence_ids=[failed_print["id"]],
        ),
    )
    PROJECT.set_branch_status(failed_branch, "not_working", "Physical latch failure", False)

    architecture = design_intelligence.bootstrap_architecture("Redesign the latch so it works reliably.", PROJECT.snapshot())
    context = design_intelligence.build_planner_context("Redesign the latch so it works reliably.", architecture, PROJECT.snapshot())
    feedback = context["physical_feedback"]
    assert feedback["active"]["branch"] == failed_branch
    assert feedback["active"]["manufacturing_outcomes"]["failure"] == 1
    assert any("skipped the catch" in row["text"] for row in feedback["active"]["observations"])
    assert any(row["branch"] == "main" and row["physical_verified"] for row in feedback["known_working_branches"])
    assert "not causal proof" in feedback["interpretation_policy"]

    comparison = PROJECT.compare_branch("main")
    physical_compare = comparison["physical_evidence_comparison"]
    assert physical_compare["source"]["branch"] == failed_branch
    assert physical_compare["target"]["branch"] == "main"
    assert physical_compare["source"]["manufacturing_outcomes"]["failure"] == 1
    assert physical_compare["target"]["manufacturing_outcomes"]["success"] == 1
    requirement_delta = next(row for row in physical_compare["requirement_differences"] if row["requirement_id"] == "R-LATCH")
    assert requirement_delta["source"]["status"] == "failed"
    assert requirement_delta["target"]["status"] == "passed"
    assert physical_compare["causality"] == "not_inferred"

    # The failed source evidence is exact for the failed source branch. Candidate CAD
    # mutations must make it historical rather than permanently failing every autonomous
    # redesign before that redesign can be tested.
    campaign = PROJECT.run_campaign(
        object_id,
        {
            "objective": "mass",
            "force_n": 10.0,
            "deflection_max_mm": 100.0,
            "yield_fos_min": 0.1,
            "max_candidates": 3,
            "process": "cnc",
            "variables": [{"name": "z", "min": 5.5, "max": 9.0}],
        },
    )
    assert campaign["source_physical_feedback"]["branch"] == failed_branch
    assert campaign["source_physical_feedback"]["manufacturing_outcomes"]["failure"] == 1
    assert campaign["feedback_semantics"]["evidence_is_stale_after_candidate_geometry_changes"] is True
    assert len(campaign["candidates"]) == 3
    assert all(row["verifier"]["gates"]["requirements"] for row in campaign["candidates"] if "error" not in row)

    feedback_endpoint_model = feedback_intelligence.branch_feedback("main")
    assert feedback_endpoint_model["physical_verified"] is True
    assert feedback_endpoint_model["manufacturing_outcomes"]["success"] == 1

    return {
        "failed_branch": failed_branch,
        "working_branch": "main",
        "failed_observations_visible_to_planner": True,
        "branch_evidence_comparison": True,
        "causality_not_inferred": physical_compare["causality"] == "not_inferred",
        "campaign_candidates": len(campaign["candidates"]),
        "stale_failure_does_not_block_candidates": all(row["verifier"]["gates"]["requirements"] for row in campaign["candidates"] if "error" not in row),
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 physical feedback self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
