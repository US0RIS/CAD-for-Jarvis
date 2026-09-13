from __future__ import annotations

"""Git-style engineering-state comparison for ForgeCAD 2.0 branches.

The legacy branch comparison correctly showed object-level geometry changes, but a real
engineering revision can fail without changing a body: load cases, constraints,
requirements, BOM, wiring and named design parameters all matter. This layer enriches
the existing comparison instead of replacing it, preserving physical-evidence feedback
while adding deterministic deltas for the rest of canonical project state.
"""

from copy import deepcopy
import json
from typing import Any, Callable

from ..engineering_state import EngineeringProject
from ..v110 import core


_INSTALLED = False
_ORIGINAL_COMPARE_BRANCH = None


def _state(branch: str) -> dict[str, Any]:
    if branch == core.ACTIVE_DESIGN:
        return core.PROJECT
    if branch not in core.BRANCHES:
        raise KeyError(branch)
    return core.BRANCHES[branch]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _identity(row: dict[str, Any], index: int, *, hints: tuple[str, ...]) -> str:
    for key in ("id", *hints):
        value = row.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return f"row:{index}:{_canonical(row)}"


def _row_map(rows: Any, *, hints: tuple[str, ...] = ()) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            continue
        key = _identity(raw, index, hints=hints)
        # Duplicate semantic identities still need independent visibility rather than
        # silently overwriting each other in the diff.
        if key in out:
            suffix = 2
            candidate = f"{key}#{suffix}"
            while candidate in out:
                suffix += 1
                candidate = f"{key}#{suffix}"
            key = candidate
        out[key] = raw
    return out


def _row_diff(source: Any, target: Any, *, hints: tuple[str, ...] = ()) -> dict[str, Any]:
    a = _row_map(source, hints=hints)
    b = _row_map(target, hints=hints)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    for key in sorted(set(a) | set(b)):
        if key not in a:
            added.append({"key": key, "value": deepcopy(b[key])})
        elif key not in b:
            removed.append({"key": key, "value": deepcopy(a[key])})
        elif _canonical(a[key]) != _canonical(b[key]):
            modified.append({"key": key, "source": deepcopy(a[key]), "target": deepcopy(b[key])})
    return {"added": added, "removed": removed, "modified": modified, "count": len(added) + len(removed) + len(modified)}


def _mapping_diff(source: Any, target: Any) -> dict[str, Any]:
    a = source if isinstance(source, dict) else {}
    b = target if isinstance(target, dict) else {}
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    for key in sorted(set(a) | set(b)):
        if key not in a:
            added.append({"key": key, "value": deepcopy(b[key])})
        elif key not in b:
            removed.append({"key": key, "value": deepcopy(a[key])})
        elif _canonical(a[key]) != _canonical(b[key]):
            modified.append({"key": key, "source": deepcopy(a[key]), "target": deepcopy(b[key])})
    return {"added": added, "removed": removed, "modified": modified, "count": len(added) + len(removed) + len(modified)}


def _scalar_diff(source: Any, target: Any) -> dict[str, Any]:
    changed = _canonical(source) != _canonical(target)
    return {"changed": changed, "source": deepcopy(source), "target": deepcopy(target), "count": 1 if changed else 0}


def engineering_state_diff(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {
        "design_parameters": _mapping_diff(source.get("design_parameters"), target.get("design_parameters")),
        "requirements": _row_diff(source.get("requirements"), target.get("requirements"), hints=("statement", "description")),
        "loads": _row_diff(source.get("loads"), target.get("loads"), hints=("object_id", "type")),
        "constraints": _row_diff(source.get("constraints"), target.get("constraints"), hints=("object_id", "type")),
        "connections": _row_diff(source.get("connections"), target.get("connections"), hints=("kind",)),
        "bom": _row_diff(source.get("bom"), target.get("bom"), hints=("component_ref", "model", "description")),
        "joints": _row_diff(source.get("joints"), target.get("joints"), hints=("object_id", "type")),
        "settings": _mapping_diff(source.get("settings"), target.get("settings")),
        "project_name": _scalar_diff(source.get("name"), target.get("name")),
    }
    changed_categories = [name for name, delta in categories.items() if int(delta.get("count", 0)) > 0]
    total = sum(int(delta.get("count", 0)) for delta in categories.values())
    return {
        "categories": categories,
        "changed_categories": changed_categories,
        "count": total,
        "canonical_scope": [
            "objects",
            "design_parameters",
            "requirements",
            "loads",
            "constraints",
            "connections",
            "bom",
            "joints",
            "settings",
            "project_name",
            "physical_evidence",
        ],
        "note": "Object geometry changes are reported by the top-level comparison; this engineering delta covers non-object canonical state. Physical evidence remains a separate evidence comparison and never implies causality.",
    }


def _compare_branch(self: EngineeringProject, name: str) -> dict[str, Any]:
    assert _ORIGINAL_COMPARE_BRANCH is not None
    result = _ORIGINAL_COMPARE_BRANCH(self, name)
    source_name = str(result.get("source") or core.ACTIVE_DESIGN)
    target_name = str(result.get("target") or name)
    source = _state(source_name)
    target = _state(target_name)
    delta = engineering_state_diff(source, target)
    result["engineering_state"] = delta
    result["total_engineering_change_count"] = int(result.get("count", 0)) + int(delta["count"])
    result["changed_domains"] = [
        *( ["objects"] if int(result.get("count", 0)) else [] ),
        *delta["changed_categories"],
        *( ["physical_evidence"] if (result.get("physical_evidence_comparison") or {}).get("evidence_only_in_source") or (result.get("physical_evidence_comparison") or {}).get("evidence_only_in_target") or (result.get("physical_evidence_comparison") or {}).get("requirement_differences") else [] ),
    ]
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_COMPARE_BRANCH
    if _INSTALLED:
        return
    _ORIGINAL_COMPARE_BRANCH = EngineeringProject.compare_branch
    EngineeringProject.compare_branch = _compare_branch  # type: ignore[method-assign]
    _INSTALLED = True
