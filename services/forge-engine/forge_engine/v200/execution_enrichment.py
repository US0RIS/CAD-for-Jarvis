from __future__ import annotations

"""Execution-time enrichment for ForgeCAD 2.0 agent plans.

The systems architect's requirements must become canonical project state rather than
remaining transient language-model context.  This wrapper deterministically prepends
missing requirements before the model's typed operations and preserves the architecture
in the returned result.
"""

from copy import deepcopy
from typing import Any

from ..engineering_state import EngineeringProject

_INSTALLED = False
_ORIGINAL_APPLY = EngineeringProject.apply_agent_plan


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _requirement_command(requirement: dict[str, Any]) -> dict[str, Any] | None:
    statement = str(requirement.get("statement") or "").strip()
    if not statement:
        return None
    args: dict[str, Any] = {
        "statement": statement,
        "priority": str(requirement.get("priority") or "must"),
        "verification": str(requirement.get("verification") or "Verify against the completed design."),
        "source": "forgecad-v2-architecture",
    }
    # Quantitative requirements participate in the deterministic requirement checker.
    if requirement.get("metric") is not None and requirement.get("target") is not None:
        args["metric"] = str(requirement.get("metric"))
        args["op"] = str(requirement.get("op") or "<=")
        args["target"] = requirement.get("target")
    return {"op": "set_requirement", "args": args}


def _apply_with_requirements(self: EngineeringProject, plan: dict[str, Any], text: str) -> dict[str, Any]:
    architecture = plan.get("architecture") if isinstance(plan, dict) else None
    if not isinstance(architecture, dict):
        return _ORIGINAL_APPLY(self, plan, text)

    existing = {
        _key(item.get("statement") or item.get("description") or item.get("text"))
        for item in (self.snapshot().get("requirements") or [])
        if isinstance(item, dict)
    }
    prefix: list[dict[str, Any]] = []
    for requirement in architecture.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        command = _requirement_command(requirement)
        if command is None:
            continue
        statement_key = _key(command["args"]["statement"])
        if statement_key and statement_key not in existing:
            existing.add(statement_key)
            prefix.append(command)

    enriched = deepcopy(plan)
    enriched["commands"] = prefix + list(plan.get("commands") or [])
    result = _ORIGINAL_APPLY(self, enriched, text)
    result["architecture"] = deepcopy(architecture)
    result["requirements_added"] = len(prefix)
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    EngineeringProject.apply_agent_plan = _apply_with_requirements
    _INSTALLED = True
