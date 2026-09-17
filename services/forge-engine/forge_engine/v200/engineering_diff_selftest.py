from __future__ import annotations

"""Regression gate for complete ForgeCAD 2.0 engineering branch diffs."""

from ..engineering_state import PROJECT
from ..v110 import core


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "set_design_parameter",
        {"name": "wall", "value": 4.0, "unit": "mm", "description": "Nominal wall thickness"},
        actor="human",
        reason="Create baseline design variable",
    )
    PROJECT.execute(
        "add",
        {
            "name": "Diff test body",
            "kind": "box",
            "params": {"x": 80.0, "y": 30.0, "z": {"expr": "wall"}},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "structure", "tags": ["diff-selftest"]},
        },
        actor="human",
        reason="Create baseline body",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    PROJECT.execute(
        "set_requirement",
        {"id": "R1", "statement": "Baseline body shall exist.", "verification": "Inspect CAD."},
        actor="human",
        reason="Create baseline requirement",
    )
    source_branch = core.ACTIVE_DESIGN

    PROJECT.create_branch("engineering-delta", "Exercise complete branch comparison")
    active_branch = core.ACTIVE_DESIGN
    PROJECT.execute(
        "set_design_parameter",
        {"name": "wall", "value": 6.0, "unit": "mm", "description": "Nominal wall thickness"},
        actor="human",
        reason="Thicken wall",
    )
    PROJECT.execute(
        "add_load",
        {"id": "L1", "object_id": object_id, "type": "force", "face": "x_max", "force_n": 120.0, "direction": "-z"},
        actor="human",
        reason="Add structural load case",
    )
    PROJECT.execute(
        "add_constraint",
        {"id": "C1", "object_id": object_id, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Add structural support",
    )
    PROJECT.execute(
        "set_requirement",
        {"id": "R2", "statement": "Loaded design shall pass SolidFEA.", "verification": "Run project boundary-condition SolidFEA."},
        actor="human",
        reason="Add branch-specific requirement",
    )
    PROJECT.execute(
        "add_bom_item",
        {"id": "B1", "description": "M4 test fastener", "qty": 4, "unit_cost_usd": 0.25},
        actor="human",
        reason="Add branch hardware",
    )
    PROJECT.execute(
        "settings",
        {"analysis_note": "project-boundary-condition test"},
        actor="human",
        reason="Record branch analysis setting",
    )

    comparison = PROJECT.compare_branch(source_branch)
    assert comparison["source"] == active_branch
    assert comparison["target"] == source_branch
    # The object itself retains the expression node, so changing a named parameter does
    # not masquerade as a direct geometry-object edit. The design parameter delta carries
    # the engineering change explicitly.
    delta = comparison["engineering_state"]
    categories = delta["categories"]
    assert categories["design_parameters"]["count"] == 1
    assert categories["design_parameters"]["modified"][0]["key"] == "wall"
    assert categories["loads"]["count"] == 1
    assert categories["constraints"]["count"] == 1
    assert categories["requirements"]["count"] == 1
    assert categories["bom"]["count"] == 1
    assert categories["settings"]["count"] == 1
    assert set(delta["changed_categories"]) >= {"design_parameters", "loads", "constraints", "requirements", "bom", "settings"}
    assert set(comparison["changed_domains"]) >= {"design_parameters", "loads", "constraints", "requirements", "bom", "settings"}
    assert comparison["total_engineering_change_count"] >= 6
    assert "physical_evidence_comparison" in comparison
    assert comparison["physical_evidence_comparison"]["causality"] == "not_inferred"

    return {
        "source_branch": active_branch,
        "target_branch": source_branch,
        "object_changes": comparison["count"],
        "non_object_changes": delta["count"],
        "changed_domains": comparison["changed_domains"],
        "physical_evidence_preserved": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 engineering branch diff self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
