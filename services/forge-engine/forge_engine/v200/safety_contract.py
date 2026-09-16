from __future__ import annotations

"""Planner-visible safety/failure-mode contract for ForgeCAD 2.0."""

from copy import deepcopy
from typing import Any, Callable

from . import analysis_contracts


_INSTALLED = False
_ORIGINAL_CONTRACTS: Callable[..., dict[str, Any]] | None = None


SAFETY_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-safety-register-2.0",
    "solver": "ForgeCAD SafetyRegister",
    "grade": "engineering_process",
    "analysis_endpoint": "/v2/analysis/safety",
    "failure_modes_endpoint": "/v2/safety/failure-modes",
    "canonical_operations": {
        "add": {
            "operation": "add_failure_mode",
            "schema": {
                "name": "Unexpected actuator motion",
                "category": "control",
                "cause": "stale command or sensor fault",
                "effect": "pinch or collision hazard",
                "object_ids": ["$actuator"],
                "severity": 9,
                "occurrence": 3,
                "detection": 4,
                "controls": ["hardware enable interlock", "travel limit switch"],
                "verification_method": "fault injection and emergency-stop test",
            },
        },
        "update": "update_failure_mode",
        "delete": "delete_failure_mode",
    },
    "verification": {
        "endpoint": "/v2/safety/failure-modes/{failure_mode_id}/verify",
        "agent_can_self_verify": False,
        "policy": "Verification is an explicit human/evidence action bound to the exact current design fingerprint. Ordinary agent plan operations may propose controls but cannot create verification evidence.",
    },
    "rankings": {
        "severity": "required integer 1–10",
        "occurrence": "optional integer 1–10; unknown stays unknown",
        "detection": "optional integer 1–10; unknown stays unknown",
        "rpn": "severity × occurrence × detection only when all three explicit rankings exist",
    },
    "fail_closed": [
        "severity 8–10 failure mode without explicit controls and current-design passed verification",
        "current-design failure-mode verification explicitly failed",
        "malformed failure-mode records or unknown referenced objects",
    ],
    "outputs": [
        "canonical failure-mode register",
        "severity and optional RPN ranking",
        "risk controls and verification methods",
        "current versus stale verification evidence",
        "release-blocking high-severity safety risks",
    ],
    "unknown_policy": "Do not invent occurrence rates, detection confidence, severity reductions, standards compliance or test results. Missing occurrence/detection remains unknown and RPN remains unavailable.",
    "limitations": [
        "hazard discovery is not guaranteed exhaustive",
        "ordinal FMEA rankings are prioritization inputs, not measured probabilities",
        "RPN is not absolute proof of safety",
        "domain standards and specialist review remain external requirements where applicable",
        "not certification evidence",
    ],
}


def _contracts() -> dict[str, Any]:
    assert _ORIGINAL_CONTRACTS is not None
    result = _ORIGINAL_CONTRACTS()
    result["safety"] = deepcopy(SAFETY_ANALYSIS_CONTRACT)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_CONTRACTS
    if _INSTALLED:
        return
    _ORIGINAL_CONTRACTS = analysis_contracts.contracts
    analysis_contracts.contracts = _contracts
    _INSTALLED = True
