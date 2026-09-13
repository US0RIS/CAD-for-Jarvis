from __future__ import annotations

"""ForgeCAD 2.0 autonomous multi-branch engineering campaigns.

The campaign engine is intentionally deterministic and branch-safe. It does not let a
language model silently mutate a known-good design. Instead it:

1. freezes the active design as the campaign source;
2. generates bounded parametric alternatives on sibling branches;
3. runs structural, thermal, manufacturing, requirement, and system checks;
4. applies an independent deterministic verifier to each candidate;
5. ranks only candidates that pass the requested engineering gates;
6. activates the best unverified candidate while preserving the source branch exactly.

Campaign variables may address ordinary top-level object parameters, named dimensions
inside constrained sketches, or literal project-level design parameters that feed the
selected object's expression tree. Derived expressions themselves are preserved; the
optimizer changes their independent inputs rather than replacing design intent with a
literal number.

The built-in structural/thermal analyses remain screening models. A campaign result is
never promoted to physical verification automatically.
"""

import ast
from copy import deepcopy
import itertools
import math
import re
from types import MethodType
from typing import Any

from ..v110 import analysis, core
from . import manufacturing


_INSTALLED = False


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return cleaned or "campaign"


def _numeric_params(obj: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (obj.get("params") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            out[str(key)] = float(value)
    return out


def _expression_names(expression: str) -> set[str]:
    try:
        tree = ast.parse(str(expression), mode="eval")
    except SyntaxError:
        return set()
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _object_expression_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("expr"), str):
            names.update(_expression_names(str(value["expr"])))
        for item in value.values():
            names.update(_object_expression_names(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            names.update(_object_expression_names(item))
    return names


def _dependent_literal_design_parameters(obj: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions = core.PROJECT.get("design_parameters") or {}
    if not isinstance(definitions, dict) or not definitions:
        return {}
    referenced = _object_expression_names(obj.get("params") or {}) | _object_expression_names(obj.get("features") or [])
    pending = [name for name in referenced if name in definitions]
    visited: set[str] = set()
    literals: dict[str, dict[str, Any]] = {}
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        raw = definitions.get(name)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            literals[name] = {"value": float(raw), "unit": "", "description": ""}
            continue
        if not isinstance(raw, dict):
            continue
        expression = raw.get("expression")
        if expression not in (None, ""):
            for dependency in _expression_names(str(expression)):
                if dependency in definitions and dependency not in visited:
                    pending.append(dependency)
            continue
        value = raw.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            literals[name] = {
                "value": float(value),
                "unit": str(raw.get("unit") or ""),
                "description": str(raw.get("description") or ""),
            }
    return literals


def _dimension_variables(obj: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return optimizable design variables with an explicit mutation path."""
    variables: dict[str, dict[str, Any]] = {}
    for name, value in _numeric_params(obj).items():
        variables[name] = {
            "name": name,
            "start": value,
            "path": ["params", name],
            "kind": "parameter",
        }

    if str(obj.get("kind") or "") == "constrained_sketch_extrude":
        params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
        sketch = params.get("sketch") if isinstance(params.get("sketch"), dict) else {}
        constraints = sketch.get("constraints") if isinstance(sketch.get("constraints"), list) else []
        supported = {"distance", "x_distance", "y_distance", "angle"}
        for index, raw in enumerate(constraints):
            if not isinstance(raw, dict):
                continue
            constraint_type = str(raw.get("type") or "").lower().strip()
            if constraint_type not in supported:
                continue
            field = "angle_deg" if constraint_type == "angle" else "value"
            value = raw.get(field)
            # Expression-driven dimensions are optimized through their independent named
            # design parameters below; never overwrite an expression node with a literal.
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                continue
            semantic_name = str(raw.get("name") or raw.get("dimension") or raw.get("id") or "").strip()
            key = f"sketch.{semantic_name}" if semantic_name else f"sketch.constraint_{index}"
            if key in variables:
                key = f"sketch.constraint_{index}"
            variables[key] = {
                "name": key,
                "start": float(value),
                "path": ["params", "sketch", "constraints", index, field],
                "kind": "sketch_dimension",
                "constraint_index": index,
                "constraint_type": constraint_type,
                "field": field,
            }

    for parameter_name, definition in _dependent_literal_design_parameters(obj).items():
        key = f"design.{parameter_name}"
        variables[key] = {
            "name": key,
            "start": float(definition["value"]),
            "path": ["design_parameters", parameter_name, "value"],
            "kind": "design_parameter",
            "parameter_name": parameter_name,
            "unit": str(definition.get("unit") or ""),
            "description": str(definition.get("description") or ""),
        }
    return variables


def _select_object(selected_object_id: str | None) -> dict[str, Any]:
    if selected_object_id:
        candidate = core.object_by_id(selected_object_id)
        if candidate.get("kind") == "component" or candidate.get("component_ref"):
            raise ValueError("Autonomous geometry campaigns require a fabricated/custom part, not immutable purchased hardware")
        return candidate
    candidate = next(
        (
            obj
            for obj in core.PROJECT.get("objects", [])
            if obj.get("kind") != "component" and not obj.get("component_ref")
        ),
        None,
    )
    if candidate is None:
        raise ValueError("Autonomous campaign requires at least one fabricated/custom part")
    return candidate


def _default_variable(params: dict[str, dict[str, Any]]) -> str:
    for name in ("thickness", "z", "height", "x", "y", "radius", "diameter", "width", "depth"):
        row = params.get(name)
        if row and float(row["start"]) > 0:
            return name
    for name, row in params.items():
        if row.get("kind") == "design_parameter" and float(row["start"]) > 0:
            return name
    for name, row in params.items():
        if row.get("kind") == "sketch_dimension" and float(row["start"]) > 0:
            return name
    for name, row in params.items():
        if float(row["start"]) > 0:
            return name
    raise ValueError("Selected fabricated part has no numeric parameter, sketch dimension, or independent design parameter suitable for optimization")


def _resolve_variable_name(name: str, available: dict[str, dict[str, Any]]) -> str | None:
    if name in available:
        return name
    normalized = name.strip().lower().replace(" ", "_")
    exact = next((key for key in available if key.lower() == normalized), None)
    if exact:
        return exact
    # Permit concise semantic references when the suffix is unambiguous: `width` may
    # address sketch.width or design.width depending on what actually drives the object.
    suffix_matches = [
        key for key in available
        if key.lower().removeprefix("sketch.").removeprefix("design.") == normalized
    ]
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def _default_bounds(row: dict[str, Any]) -> tuple[float, float]:
    start = float(row["start"])
    if row.get("constraint_type") == "angle":
        return max(1.0, start - 20.0), min(179.0, start + 20.0)
    if start > 0:
        return max(0.1, start * 0.65), max(0.2, start * 1.35)
    span = max(1.0, abs(start) * 0.35)
    return start - span, start + span


def _variables(obj: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    available = _dimension_variables(obj)
    requested = payload.get("variables")
    rows: list[dict[str, Any]] = []
    if isinstance(requested, list):
        for raw in requested[:3]:
            if not isinstance(raw, dict):
                continue
            requested_name = str(raw.get("name") or "")
            name = _resolve_variable_name(requested_name, available)
            if not name:
                continue
            definition = available[name]
            start = float(definition["start"])
            default_lo, default_hi = _default_bounds(definition)
            lo = float(raw.get("min", default_lo))
            hi = float(raw.get("max", default_hi))
            if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
                continue
            if definition.get("constraint_type") == "angle":
                lo, hi = max(0.1, lo), min(179.9, hi)
                if hi <= lo:
                    continue
            rows.append({**deepcopy(definition), "name": name, "start": start, "min": lo, "max": hi})
    if rows:
        return rows
    name = _default_variable(available)
    definition = available[name]
    start = float(definition["start"])
    lo, hi = _default_bounds(definition)
    return [{**deepcopy(definition), "name": name, "start": start, "min": lo, "max": hi}]


def _candidate_parameter_sets(variables: list[dict[str, Any]], max_candidates: int) -> list[dict[str, float]]:
    max_candidates = max(3, min(int(max_candidates), 24))
    count = len(variables)
    levels = max(2, min(5, int(math.ceil(max_candidates ** (1.0 / max(count, 1))))))
    grids: list[list[float]] = []
    for row in variables:
        lo = float(row["min"])
        hi = float(row["max"])
        start = float(row["start"])
        values = [lo + (hi - lo) * index / (levels - 1) for index in range(levels)]
        values.append(start)
        unique = sorted({round(value, 9) for value in values})
        unique.sort(key=lambda value: (abs(value - start), value))
        grids.append(unique)

    combos = list(itertools.product(*grids))
    baseline = tuple(float(row["start"]) for row in variables)
    combos.sort(key=lambda combo: (sum(abs(v - b) / max(abs(b), 1e-9) for v, b in zip(combo, baseline)), combo))
    result: list[dict[str, float]] = []
    for combo in combos:
        result.append({str(row["name"]): float(value) for row, value in zip(variables, combo)})
        if len(result) >= max_candidates:
            break
    return result


def _write_path(root: Any, path: list[Any], value: float) -> None:
    cursor = root
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = float(value)


def _candidate_changes(obj: dict[str, Any], variables: list[dict[str, Any]], values: dict[str, float]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    params = deepcopy(obj.get("params") or {})
    wrapper = {"params": params}
    by_name = {str(row["name"]): row for row in variables}
    design_updates: list[dict[str, Any]] = []
    for name, value in values.items():
        definition = by_name.get(name)
        if definition is None:
            raise ValueError(f"Campaign variable {name!r} is not defined for the selected object")
        if definition.get("kind") == "design_parameter":
            design_updates.append({
                "name": str(definition["parameter_name"]),
                "value": float(value),
                "unit": str(definition.get("unit") or ""),
                "description": str(definition.get("description") or ""),
            })
            continue
        path = list(definition.get("path") or [])
        if not path or path[0] != "params":
            raise ValueError(f"Campaign variable {name!r} has an invalid mutation path")
        _write_path(wrapper, path, value)
    return params, design_updates


def _failed_requirement_count(validation: dict[str, Any]) -> int:
    count = 0
    for row in validation.get("requirements") or []:
        if not isinstance(row, dict):
            continue
        if row.get("passed") is False or row.get("ok") is False or str(row.get("status") or "").lower() in {"failed", "fail", "not_met"}:
            count += 1
    return count


def _objective_score(objective: str, metrics: dict[str, Any], structural: dict[str, Any], thermal: dict[str, Any]) -> float:
    objective = objective.lower().strip()
    if objective in {"deflection", "displacement", "stiffness"}:
        return float(structural.get("max_displacement_mm", structural.get("max_deflection_mm", float("inf"))))
    if objective in {"safety", "safety_margin", "fos"}:
        return -float(structural.get("yield_fos", 0.0))
    if objective in {"temperature", "thermal"}:
        return float(thermal.get("max_temperature_c", float("inf")))
    return float(metrics.get("mass_kg", float("inf")))


def _independent_verifier(
    obj: dict[str, Any],
    structural: dict[str, Any],
    validation: dict[str, Any],
    manufacturing_check: dict[str, Any],
    *,
    force_n: float,
    deflection_max_mm: float,
    yield_fos_min: float,
    max_temperature_c: float | None,
    thermal: dict[str, Any],
) -> dict[str, Any]:
    independent = analysis.quick_cantilever(obj, force_n=force_n)
    linear_deflection = float(structural.get("max_deflection_mm", structural.get("max_displacement_mm", float("inf"))))
    independent_deflection = float(independent.get("max_deflection_mm", float("inf")))
    structural_consistent = math.isfinite(linear_deflection) and math.isfinite(independent_deflection) and abs(linear_deflection - independent_deflection) <= max(1e-6, abs(independent_deflection) * 0.02)

    gates = {
        "system_validation": int((validation.get("counts") or {}).get("error", 0)) == 0,
        "requirements": _failed_requirement_count(validation) == 0,
        "deflection": linear_deflection <= deflection_max_mm,
        "yield_fos": float(structural.get("yield_fos", 0.0)) >= yield_fos_min,
        "structural_consistency": structural_consistent,
        "manufacturing": bool(manufacturing_check.get("ok", True)),
    }
    if max_temperature_c is not None:
        gates["temperature"] = float(thermal.get("max_temperature_c", float("inf"))) <= max_temperature_c
    return {
        "role": "verifier",
        "passed": all(gates.values()),
        "gates": gates,
        "independent_structural": independent,
        "limitations": [
            "Built-in structural and thermal solvers are screening models, not certification solvers.",
            "A passing campaign candidate remains physically unverified until tested in the real world.",
        ],
    }


def _run_campaign(self: Any, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = deepcopy(payload or {})
    if not core.PROJECT.get("objects"):
        raise ValueError("Add or import a fabricated part before running an autonomous campaign")

    source_branch = core.ACTIVE_DESIGN
    source_object = _select_object(selected_object_id)
    object_id = str(source_object["id"])
    variables = _variables(source_object, payload)
    objective = str(payload.get("objective") or "mass").lower().strip()
    max_candidates = max(3, min(int(payload.get("max_candidates", payload.get("max_evals", 7))), 24))
    force_n = float(payload.get("force_n", 100.0))
    heat_w = float(payload.get("heat_w", 10.0))
    deflection_max_mm = float(payload.get("deflection_max_mm", 1.0))
    yield_fos_min = float(payload.get("yield_fos_min", 1.5))
    max_temperature = payload.get("max_temperature_c")
    max_temperature_c = float(max_temperature) if max_temperature is not None else None
    process = str(payload.get("process") or ("fdm" if str(payload.get("manufacturing_resource") or "").lower() in {"p2s", "bambu", "bambu-lab-p2s"} else "cnc")).lower()
    candidate_sets = _candidate_parameter_sets(variables, max_candidates)

    source_state = deepcopy(core.PROJECT)
    source_params = deepcopy(source_object.get("params") or {})
    source_design_parameters = deepcopy(core.PROJECT.get("design_parameters") or {})
    candidates: list[dict[str, Any]] = []

    for index, values in enumerate(candidate_sets, start=1):
        core.switch_branch(source_branch)
        branch_seed = f"campaign-{_slug(objective)}-{index:02d}"
        core.create_branch(branch_seed, reason=f"Autonomous {objective} campaign candidate {index}")
        branch_name = core.ACTIVE_DESIGN
        candidate_obj = core.object_by_id(object_id)
        params, design_updates = _candidate_changes(candidate_obj, variables, values)

        try:
            for update in design_updates:
                existing = (core.PROJECT.get("design_parameters") or {}).get(update["name"])
                current_value = existing.get("value") if isinstance(existing, dict) else existing
                if isinstance(current_value, (int, float)) and abs(float(current_value) - float(update["value"])) <= 1e-12:
                    continue
                core.execute(
                    "set_design_parameter",
                    update,
                    actor="forge-optimizer",
                    reason=f"Campaign candidate {index}: set {update['name']}={update['value']}",
                )
            if params != (candidate_obj.get("params") or {}):
                core.execute(
                    "update",
                    {"id": object_id, "params": params},
                    actor="forge-optimizer",
                    reason=f"Campaign candidate {index}: {values}",
                )
            candidate_obj = core.object_by_id(object_id)
            metrics = core.object_metrics(candidate_obj)
            structural = analysis.linear_fea(candidate_obj, force_n=force_n)
            thermal = analysis.thermal_analysis(candidate_obj, heat_w=heat_w)
            process_review = analysis.manufacturing_review(candidate_obj, process=process)
            p2s = None
            if process in {"fdm", "fff"} or str(payload.get("manufacturing_resource") or "").lower() in {"p2s", "bambu", "bambu-lab-p2s"}:
                p2s = manufacturing.analyze_object(candidate_obj, core.build_shape)
                if not p2s.get("fits_build_volume", False) or not p2s.get("eligible", False):
                    process_review = deepcopy(process_review)
                    process_review["ok"] = False
                    process_review.setdefault("issues", []).append({"severity": "error", "message": "Candidate does not satisfy the P2S build-volume/solid eligibility gate."})

            validation = self.validation()
            verifier = _independent_verifier(
                candidate_obj,
                structural,
                validation,
                process_review,
                force_n=force_n,
                deflection_max_mm=deflection_max_mm,
                yield_fos_min=yield_fos_min,
                max_temperature_c=max_temperature_c,
                thermal=thermal,
            )
            score = _objective_score(objective, metrics, structural, thermal)
            feasible = bool(verifier["passed"])
            core.set_design_status(
                branch_name,
                "unverified" if feasible else "not_working",
                note=("Passed deterministic campaign gates; physical verification still required" if feasible else "Rejected by deterministic campaign gates"),
                physical_verified=False,
            )
            row = {
                "branch": branch_name,
                "parameters": values,
                "parameter_paths": {str(item["name"]): deepcopy(item.get("path")) for item in variables if str(item["name"]) in values},
                "metrics": metrics,
                "structural": structural,
                "thermal": thermal,
                "manufacturing": process_review,
                "p2s": p2s,
                "validation": {
                    "ok": validation.get("ok"),
                    "counts": validation.get("counts"),
                    "requirements": validation.get("requirements"),
                },
                "verifier": verifier,
                "feasible": feasible,
                "score": score,
            }
        except Exception as exc:
            core.set_design_status(branch_name, "not_working", note=f"Campaign evaluation failed: {exc}", physical_verified=False)
            row = {
                "branch": branch_name,
                "parameters": values,
                "parameter_paths": {str(item["name"]): deepcopy(item.get("path")) for item in variables if str(item["name"]) in values},
                "feasible": False,
                "score": float("inf"),
                "error": str(exc),
                "verifier": {"role": "verifier", "passed": False, "gates": {"evaluation_completed": False}},
            }
        candidates.append(row)

    feasible = [row for row in candidates if row.get("feasible") and math.isfinite(float(row.get("score", float("inf"))))]
    feasible.sort(key=lambda row: (float(row["score"]), str(row["branch"])))
    winner = feasible[0] if feasible else None

    if winner is not None:
        core.switch_branch(str(winner["branch"]))
    else:
        core.switch_branch(source_branch)
        current_source = core.object_by_id(object_id)
        if current_source.get("params") != source_params or (core.PROJECT.get("design_parameters") or {}) != source_design_parameters:
            core.PROJECT.clear()
            core.PROJECT.update(deepcopy(source_state))
            core.BRANCHES[source_branch] = deepcopy(core.PROJECT)
            core.persist()

    ranked = sorted(
        candidates,
        key=lambda row: (not bool(row.get("feasible")), float(row.get("score", float("inf"))), str(row.get("branch"))),
    )
    result = {
        "campaign_version": "2.0.0",
        "source_branch": source_branch,
        "source_object_id": object_id,
        "objective": objective,
        "variables": variables,
        "constraints": {
            "force_n": force_n,
            "heat_w": heat_w,
            "deflection_max_mm": deflection_max_mm,
            "yield_fos_min": yield_fos_min,
            "max_temperature_c": max_temperature_c,
            "process": process,
        },
        "roles": {
            "designer": {"generated_candidates": len(candidates), "strategy": "bounded parametric sibling branches"},
            "analyst": {"analyses": ["structural", "thermal", "manufacturing", "system", "requirements"]},
            "verifier": {"independent_gate": True, "physical_verification_required": True},
            "optimizer": {"objective": objective, "ranked_branches": [row["branch"] for row in ranked]},
        },
        "candidates": ranked,
        "winner": deepcopy(winner),
        "winner_branch": winner.get("branch") if winner else None,
        "active_branch": core.ACTIVE_DESIGN,
        "status": "candidate_selected" if winner else "no_feasible_candidate",
    }

    core.record_simulation("autonomous_campaign", object_id, payload, result)
    result["project"] = self.snapshot()
    return result


def install(legacy: Any) -> None:
    """Install the v2 campaign engine onto the authoritative EngineeringProject instance."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    legacy.PROJECT.run_campaign = MethodType(_run_campaign, legacy.PROJECT)
