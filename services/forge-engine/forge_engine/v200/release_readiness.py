from __future__ import annotations

"""Release-contract smoke gate for ForgeCAD 2.0.0.

This is intentionally broader than an import/version check and much faster than the full
numerical regression suite. Packaged installers and desktop vertical-slice workflows use
it to prove that the shipped v2 entrypoint exposes every canonical system-engineering
domain that the planner and desktop claim to support.
"""

import json

from ..engineering_state import PROJECT
from . import DESIGN_INTELLIGENCE_VERSION, analysis_contracts, design_intelligence


EXPECTED_ANALYSIS_DOMAINS = {
    "electrical",
    "thermal",
    "fluid",
    "routing",
    "safety",
    "kinematics",
}


def run() -> dict[str, object]:
    assert DESIGN_INTELLIGENCE_VERSION == "2.0.0"

    snapshot = PROJECT.snapshot()
    assert snapshot.get("engineering_state", {}).get("version") == "2.0.0", snapshot.keys()
    assert isinstance(snapshot.get("routes"), list), snapshot.keys()
    assert isinstance(snapshot.get("failure_modes"), list), snapshot.keys()
    assert isinstance(snapshot.get("routing"), dict), snapshot.keys()
    assert isinstance(snapshot.get("safety"), dict), snapshot.keys()

    validation = PROJECT.validation()
    missing_validation = sorted(EXPECTED_ANALYSIS_DOMAINS - set(validation))
    assert not missing_validation, missing_validation

    contracts = analysis_contracts.contracts()
    missing_contracts = sorted(EXPECTED_ANALYSIS_DOMAINS - set(contracts))
    assert not missing_contracts, missing_contracts
    for name in EXPECTED_ANALYSIS_DOMAINS:
        contract = contracts[name]
        assert isinstance(contract, dict) and contract.get("solver"), (name, contract)
        assert contract.get("analysis_endpoint"), (name, contract)

    architecture = design_intelligence.bootstrap_architecture(
        "Design a powered moving mechanism with wiring, cooling, routed tubing, and safety verification.",
        snapshot,
    )
    context = design_intelligence.build_planner_context(
        "Design a powered moving mechanism with wiring, cooling, routed tubing, and safety verification.",
        architecture,
        snapshot,
    )
    planner_contracts = context.get("analysis_contracts") or {}
    missing_planner = sorted(EXPECTED_ANALYSIS_DOMAINS - set(planner_contracts))
    assert not missing_planner, missing_planner

    return {
        "version": DESIGN_INTELLIGENCE_VERSION,
        "analysis_domains": sorted(EXPECTED_ANALYSIS_DOMAINS),
        "validation_domains_present": True,
        "planner_contracts_present": True,
        "project_surface_present": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 release readiness: PASS")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
