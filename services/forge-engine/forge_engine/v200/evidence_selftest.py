from __future__ import annotations

"""Regression gate for branch-linked physical evidence in ForgeCAD 2.0."""

from ..engineering_state import PROJECT
from ..v110 import core
from . import physical_evidence


def run() -> dict[str, object]:
    PROJECT.new_project()
    source_branch = core.ACTIVE_DESIGN
    PROJECT.execute(
        "set_requirement",
        {
            "id": "R-PHYSICAL-1",
            "statement": "Printed latch must engage and release reliably in the physical assembly.",
            "priority": "must",
            "verification": "Print the latch, install it, and perform an engagement/release test.",
        },
        actor="human",
        reason="Create qualitative physical requirement",
    )
    before = PROJECT.snapshot()
    assert before["branches"][0]["status"] == "unverified"
    assert before["branches"][0]["physical_verified"] is False

    package_hash = "ab" * 32
    manufacture = physical_evidence.record_manufacturing_evidence(
        physical_evidence.ManufacturingEvidenceRequest(
            package_sha256=package_hash,
            outcome="success",
            material="PETG",
            machine_profile="P2S 0.4 nozzle",
            process_profile="0.20 mm Standard",
            filament_profiles=["Generic PETG"],
            slicer="Bambu Studio",
            slicer_version="test",
            estimated_duration_s=3600,
            actual_duration_s=3725,
            estimated_material_g=42.0,
            actual_material_g=43.1,
            measurements=[physical_evidence.Measurement(name="latch width", value=19.98, unit="mm", tolerance=0.15)],
            observations=["No visible warping", "Latch installed without rework"],
            note="First physical prototype",
        )
    )
    assert manufacture["branch"] == source_branch
    assert manufacture["package_sha256"] == package_hash
    assert manufacture["changes_design_status"] is False
    assert len(manufacture["design_fingerprint"]) == 64

    verification = physical_evidence.verify_requirement(
        "R-PHYSICAL-1",
        physical_evidence.RequirementEvidenceRequest(
            status="passed",
            method="physical prototype functional test",
            note="20 engagement/release cycles completed without a missed latch.",
            evidence_ids=[manufacture["id"]],
            measurements=[physical_evidence.Measurement(name="cycles", value=20, unit="cycles")],
        ),
    )
    assert verification["branch"] == source_branch
    assert verification["status"] == "passed"
    assert verification["design_fingerprint"] == manufacture["design_fingerprint"]
    checks = core.requirement_checks()
    requirement = next(row for row in checks if row["id"] == "R-PHYSICAL-1")
    assert requirement["passed"] is True
    assert requirement["verification_status"] == "passed"
    assert requirement["verification_method"] == "physical prototype functional test"
    assert requirement["physical_verification_current"] is True

    evidence = physical_evidence.evidence_rows()
    assert {row["kind"] for row in evidence} == {"manufacturing_evidence", "requirement_verification"}
    assert len(evidence) == 2
    assert all(row["applies_to_current_design"] for row in evidence)

    # Recording evidence must not silently turn an unverified design into a protected
    # known-good branch. That promotion remains an explicit branch-status user action.
    after = PROJECT.snapshot()
    branch = next(row for row in after["branches"] if row["name"] == source_branch)
    assert branch["status"] == "unverified"
    assert branch["physical_verified"] is False
    assert branch["protected"] is False

    # A branch copied without engineering changes has the exact same design fingerprint,
    # so its inherited evidence is still valid. The first real CAD/code/electrical change
    # must stale that evidence automatically rather than letting a modified design inherit
    # a physical pass from its parent.
    PROJECT.create_branch("physical-redesign", "Change the tested design")
    inherited = next(row for row in core.requirement_checks() if row["id"] == "R-PHYSICAL-1")
    assert inherited["passed"] is True
    assert inherited["physical_verification_current"] is True
    PROJECT.execute(
        "add",
        {
            "name": "Changed latch geometry",
            "kind": "box",
            "params": {"x": 20.0, "y": 8.0, "z": 3.0},
            "material": "abs",
            "semantic": {"role": "latch", "tags": ["fabricated", "redesign"]},
        },
        actor="human",
        reason="Mutate geometry after physical verification",
    )
    stale = next(row for row in core.requirement_checks() if row["id"] == "R-PHYSICAL-1")
    assert stale["passed"] is None
    assert stale["verification_status"] == "stale"
    assert stale["verification_method"] is None
    assert stale["physical_verification_current"] is False
    assert stale["stale_evidence_count"] == 1
    child_rows = physical_evidence.evidence_rows()
    assert len(child_rows) == 2
    assert not any(row["applies_to_current_design"] for row in child_rows)

    # The source branch still points at the exact tested state and therefore keeps its
    # evidence current. Evidence staleness is design-content based rather than global.
    PROJECT.activate_branch(source_branch)
    restored = next(row for row in core.requirement_checks() if row["id"] == "R-PHYSICAL-1")
    assert restored["passed"] is True
    assert restored["physical_verification_current"] is True

    # A quantitative deterministic failure cannot be overridden by manual evidence.
    PROJECT.execute(
        "set_requirement",
        {"id": "R-MASS", "statement": "Mass must remain below zero kilograms.", "metric": "mass_kg", "op": "<=", "target": -1.0, "verification": "Project mass calculation."},
        actor="human",
        reason="Create impossible quantitative gate",
    )
    physical_evidence.verify_requirement(
        "R-MASS",
        physical_evidence.RequirementEvidenceRequest(status="passed", method="manual note", note="Must not override the metric gate."),
    )
    mass_check = next(row for row in core.requirement_checks() if row["id"] == "R-MASS")
    assert mass_check["passed"] is False
    assert mass_check["verification_status"] == "passed"

    return {
        "branch": source_branch,
        "evidence_count": len(physical_evidence.evidence_rows()),
        "qualitative_requirement_passed": requirement["passed"],
        "evidence_stales_after_mutation": stale["verification_status"] == "stale",
        "source_evidence_survives_child_mutation": restored["passed"] is True,
        "quantitative_override_blocked": mass_check["passed"] is False,
        "physical_auto_verified": branch["physical_verified"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 physical evidence self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
