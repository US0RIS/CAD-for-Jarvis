from __future__ import annotations

"""Deterministic regression gate for ForgeCAD 2.0 safety/failure-mode state."""

from ..engineering_state import PROJECT
from ..v110 import core
from . import analysis_contracts, design_intelligence, physical_evidence, safety_analysis


def _add_box() -> str:
    before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
    core.execute(
        "add",
        {
            "name": "Actuated mechanism",
            "kind": "box",
            "params": {"x": 30.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        },
        actor="human",
        reason="Safety self-test: add mechanism",
    )
    created = [obj for obj in core.PROJECT.get("objects", []) if str(obj.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    mechanism = _add_box()

    route_result = core.execute(
        "add_route",
        {
            "name": "Safety-relevant harness",
            "kind": "cable",
            "points_mm": [[100.0, 100.0, 100.0], [130.0, 100.0, 100.0]],
            "outer_diameter_mm": 3.0,
        },
        actor="human",
        reason="Safety self-test: canonical harness",
    )
    route_id = str(route_result["route"]["id"])

    add_result = core.execute(
        "add_failure_mode",
        {
            "name": "Unexpected actuator motion",
            "category": "control",
            "cause": "stale command or feedback fault",
            "effect": "pinch/collision hazard",
            "object_ids": [mechanism],
            "severity": 9,
            "occurrence": 2,
            "detection": 3,
            "controls": ["hardware enable interlock", "travel limit"],
            "verification_method": "fault injection and emergency-stop test",
        },
        actor="forge-agent",
        reason="Safety self-test: identify critical hazard",
    )
    failure_id = str(add_result["failure_mode"]["id"])
    assert add_result["failure_mode"].get("verification_evidence") == []

    initial = safety_analysis.analyze_safety(core.PROJECT)
    mode = initial["failure_modes"][0]
    assert mode["rpn"] == 54
    assert mode["verification_status"] == "unverified"
    assert initial["ok"] is False
    assert any(risk.get("code") == "critical_failure_mode_unverified" for risk in initial["risks"])
    assert PROJECT.validation()["ok"] is False

    evidence = safety_analysis.verify_failure_mode(
        failure_id,
        safety_analysis.FailureVerificationRequest(
            status="passed",
            method="fault injection and emergency-stop test",
            note="Interlock removed drive enable under injected stale-command fault.",
            evidence_ids=["bench-test-001"],
        ),
    )
    fingerprint = str(evidence["design_fingerprint"])
    assert len(fingerprint) == 64

    verified = safety_analysis.analyze_safety(core.PROJECT)
    verified_mode = verified["failure_modes"][0]
    assert verified_mode["verification_status"] == "passed"
    assert verified_mode["verification_current"] is True
    assert verified_mode["verified_mitigated"] is True
    assert verified["ok"] is True, verified["risks"]
    assert PROJECT.validation()["ok"] is True

    evidence_rows = physical_evidence.evidence_rows("failure_mode_verification")
    assert len(evidence_rows) == 1
    assert evidence_rows[0]["applies_to_current_design"] is True

    snapshot = PROJECT.snapshot()
    assert len(snapshot["failure_modes"]) == 1
    assert snapshot["safety"]["ok"] is True

    contract = analysis_contracts.contracts()["safety"]
    assert contract["solver"] == "ForgeCAD SafetyRegister"
    assert contract["verification"]["agent_can_self_verify"] is False
    architecture = design_intelligence.bootstrap_architecture(
        "Design a powered mechanism and identify serious failure modes before release.",
        PROJECT.snapshot(),
    )
    context = design_intelligence.build_planner_context(
        "Design a powered mechanism and identify serious failure modes before release.",
        architecture,
        PROJECT.snapshot(),
    )
    assert context["analysis_contracts"]["safety"]["analysis_endpoint"] == "/v2/analysis/safety"

    # Route geometry is part of the physical design fingerprint. Moving the harness after
    # a passed safety test must make that evidence stale and reopen the critical gate.
    core.execute(
        "update_route",
        {"id": route_id, "points_mm": [[100.0, 100.0, 100.0], [140.0, 100.0, 100.0]]},
        actor="human",
        reason="Safety self-test: alter verified physical route",
    )
    assert physical_evidence.design_fingerprint() != fingerprint
    stale = safety_analysis.analyze_safety(core.PROJECT)
    stale_mode = stale["failure_modes"][0]
    assert stale_mode["verification_status"] == "unverified"
    assert stale_mode["stale_verification_count"] == 1
    assert stale["ok"] is False
    assert any(risk.get("code") == "critical_failure_mode_unverified" for risk in stale["risks"])
    stale_evidence = physical_evidence.evidence_rows("failure_mode_verification")
    assert stale_evidence[0]["applies_to_current_design"] is False

    return {
        "solver": initial["solver"],
        "rpn": mode["rpn"],
        "critical_gate_before_verification": True,
        "human_verification_clears_gate": True,
        "agent_cannot_self_verify": True,
        "unified_evidence_listing": True,
        "route_change_invalidates_safety_evidence": True,
        "planner_contract": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 safety self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
