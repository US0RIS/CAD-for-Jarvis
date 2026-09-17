from __future__ import annotations

"""Integrate ForgeCAD 2.0 electrical analysis into deterministic design validation."""

from copy import deepcopy
from typing import Any, Callable

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import electrical_design


_INSTALLED = False
_ORIGINAL_VALIDATION: Callable[..., dict[str, Any]] | None = None


def _risk_key(risk: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(risk.get("code") or ""),
        str(risk.get("connection_id") or ""),
        str(risk.get("object_id") or risk.get("net_id") or ""),
        str(risk.get("message") or ""),
    )


def _validation(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_VALIDATION is not None
    base = deepcopy(_ORIGINAL_VALIDATION(self))
    electrical = electrical_design.analyze_electrical(core.PROJECT)

    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for risk in list(base.get("risks") or []) + list(electrical.get("risks") or []):
        if isinstance(risk, dict):
            deduped[_risk_key(risk)] = risk
    risks = sorted(
        deduped.values(),
        key=lambda risk: (
            {"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3),
            str(risk.get("code") or ""),
            str(risk.get("message") or ""),
        ),
    )
    counts = {
        level: sum(1 for risk in risks if str(risk.get("severity") or "") == level)
        for level in ("error", "warning", "info")
    }
    base["risks"] = risks
    base["counts"] = counts
    base["ok"] = counts["error"] == 0
    base["electrical"] = electrical
    return base


def install() -> None:
    global _INSTALLED, _ORIGINAL_VALIDATION
    if _INSTALLED:
        return
    _ORIGINAL_VALIDATION = EngineeringProject.validation
    EngineeringProject.validation = _validation
    _INSTALLED = True
