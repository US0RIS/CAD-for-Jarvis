from __future__ import annotations

"""ForgeCAD 6.0 replacement semantics.

Mate compatibility and replacement compatibility answer different questions:
- mate compatibility: can interface A physically/electrically connect to B?
- replacement compatibility: can candidate interface B occupy the same external
  engineering role as old interface A without breaking existing connections?

Using mate compatibility for substitution rejects legitimate same-gender outputs
(e.g. 5 mm male shaft -> 5 mm male shaft). This module keeps those semantics
separate and intentionally does not alter the validated 3.1 mating rules.
"""

from copy import deepcopy
from typing import Any

from ..v110 import component_registry as registry
from ..v110 import core
from ..v310.engineering_graph import EngineeringGraphStore


_NUMERIC_EQUIVALENCE_KEYS = {
    "diameter_mm",
    "phases",
    "nominal_voltage_v",
    "voltage_v",
    "pitch_mm",
    "pin_count",
}


def interface_substitutability(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    old_kind = str(old.get("kind") or "")
    new_kind = str(new.get("kind") or "")
    if not old_kind or old_kind != new_kind:
        reasons.append(f"interface kind differs: {old_kind!r} -> {new_kind!r}")

    old_gender = str(old.get("gender") or "neutral")
    new_gender = str(new.get("gender") or "neutral")
    if old_gender != new_gender:
        reasons.append(f"interface gender differs: {old_gender!r} -> {new_gender!r}")

    old_standard = str(old.get("standard") or "")
    new_standard = str(new.get("standard") or "")
    if old_standard and old_standard != new_standard:
        reasons.append(f"interface standard differs: {old_standard!r} -> {new_standard!r}")

    old_mates = {str(value) for value in old.get("mate") or [] if str(value)}
    new_mates = {str(value) for value in new.get("mate") or [] if str(value)}
    if old_mates and not old_mates.issubset(new_mates):
        reasons.append(f"candidate loses external mate roles: {sorted(old_mates - new_mates)}")

    old_meta = old.get("metadata") or {}
    new_meta = new.get("metadata") or {}
    for key in sorted(_NUMERIC_EQUIVALENCE_KEYS):
        if key not in old_meta:
            continue
        if key not in new_meta:
            reasons.append(f"candidate omits required interface metadata {key!r}")
            continue
        old_value = old_meta[key]
        new_value = new_meta[key]
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            tolerance = max(1e-9, abs(float(old_value)) * 1e-6)
            if abs(float(old_value) - float(new_value)) > tolerance:
                reasons.append(f"interface metadata {key} differs: {old_value!r} -> {new_value!r}")
        elif old_value != new_value:
            reasons.append(f"interface metadata {key} differs: {old_value!r} -> {new_value!r}")

    return {
        "substitutable": not reasons,
        "reasons": reasons,
        "old_interface_id": str(old.get("id") or ""),
        "new_interface_id": str(new.get("id") or ""),
    }


def substitution_interface_mapping(current: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    failures: list[str] = []
    candidate_interfaces = candidate.get("interfaces") or []
    for old in current.get("interfaces") or []:
        old_id = str(old.get("id") or "")
        ranked: list[tuple[int, str]] = []
        rejected: list[str] = []
        for new in candidate_interfaces:
            result = interface_substitutability(old, new)
            if result["substitutable"]:
                score = 0
                if old_id and old_id == str(new.get("id") or ""):
                    score += 8
                if old.get("kind") == new.get("kind"):
                    score += 4
                if old.get("standard") and old.get("standard") == new.get("standard"):
                    score += 4
                ranked.append((-score, str(new.get("id") or "")))
            elif old.get("required"):
                rejected.extend(result["reasons"])
        ranked.sort()
        if ranked:
            mapping[old_id] = ranked[0][1]
        elif old.get("required"):
            summary = "; ".join(sorted(set(rejected))) if rejected else "no candidate interface"
            failures.append(f"required replacement interface {old_id} ({old.get('kind')}) has no equivalent candidate interface: {summary}")
    return mapping, failures


def apply_equivalent_substitution(
    object_id: str,
    component_id: str,
    graph: EngineeringGraphStore,
    *,
    actor: str = "jarvis",
    reason: str = "bounded v6 component substitution",
) -> dict[str, Any]:
    obj = core.object_by_id(object_id)
    if obj.get("kind") != "component" or not obj.get("component_ref"):
        raise ValueError("Target is not a purchased component")
    current = registry.component_by_id(str(obj["component_ref"]))
    candidate = registry.component_by_id(component_id)
    if current.get("category") != candidate.get("category"):
        raise ValueError(f"Component category mismatch: {current.get('category')} -> {candidate.get('category')}")

    mapping, failures = substitution_interface_mapping(current, candidate)
    if failures:
        raise ValueError("Replacement would break required external interfaces: " + "; ".join(failures))

    before_impact = graph.impact(f"cad:{object_id}")
    core.execute("replace_component", {"id": object_id, "component_id": component_id}, actor=actor, reason=reason)
    unresolved: list[str] = []
    with core.LOCK:
        for connection in core.PROJECT.get("connections") or []:
            for endpoint_name in ("a", "b"):
                endpoint = connection.get(endpoint_name) or {}
                if str(endpoint.get("object_id")) != object_id:
                    continue
                old_interface = str(endpoint.get("interface_id") or "")
                if old_interface in mapping:
                    endpoint["interface_id"] = mapping[old_interface]
                elif old_interface:
                    unresolved.append(old_interface)
        core.persist()

    graph.mark_dirty([f"cad:{object_id}"], reason=f"v6 equivalent component substituted {current.get('id')} -> {component_id}")
    return {
        "ok": not unresolved,
        "object_id": object_id,
        "old_component_id": current.get("id"),
        "new_component_id": component_id,
        "interface_mapping": mapping,
        "unresolved_connection_interfaces": sorted(set(unresolved)),
        "pre_change_impact": before_impact,
        "replacement_semantics": "external_interface_equivalence",
    }
