from __future__ import annotations

"""Deterministic 1D tolerance-stack analysis for ForgeCAD 2.0.

Tolerance is canonical engineering data, not prose attached to a drawing. This module
supports direct stack calculations and project-backed stacks whose contributors can be
linked to literal dimensions, named design parameters, or resolved custom-part fields.

The analysis deliberately separates three different questions:

* worst case: every contributor lands at the adverse limit simultaneously;
* RSS: independent tolerance-width accumulation for design iteration;
* statistical yield: available only when every active contributor has an explicit
  standard deviation. ForgeCAD never silently converts a drawing tolerance into sigma.

All results are engineering-iteration estimates. Distribution shape, process centering,
correlation, measurement system capability and real production data remain external
validation inputs.
"""

from copy import deepcopy
import math
from types import MethodType
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from . import parametric_expressions, project_structural


_INSTALLED = False
_ORIGINAL_RUN_SIMULATION: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_PROJECT_BOUNDARY_CONDITIONS: Callable[..., dict[str, Any]] | None = None

_TOLERANCE_CONSTRAINT_TYPES = {"dimension_tolerance", "tolerance", "tolerance_contributor"}
_TOLERANCE_SPEC_TYPES = {"tolerance_spec", "stack_spec"}
_TOLERANCE_TYPES = _TOLERANCE_CONSTRAINT_TYPES | _TOLERANCE_SPEC_TYPES


class ToleranceContributorRequest(BaseModel):
    id: str | None = None
    name: str = "Dimension"
    nominal_mm: float
    minus_mm: float = 0.0
    plus_mm: float = 0.0
    sigma_mm: float | None = None
    coefficient: float = 1.0
    source: str | None = None


class ToleranceStackRequest(BaseModel):
    name: str = "Tolerance stack"
    contributors: list[ToleranceContributorRequest] = Field(min_length=1)
    lower_spec_mm: float | None = None
    upper_spec_mm: float | None = None
    record: bool = False


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def analyze_stack(
    contributors: list[dict[str, Any]],
    *,
    name: str = "Tolerance stack",
    lower_spec_mm: float | None = None,
    upper_spec_mm: float | None = None,
) -> dict[str, Any]:
    if not contributors:
        raise ValueError("Tolerance stack requires at least one contributor")

    rows: list[dict[str, Any]] = []
    nominal = 0.0
    worst_min = 0.0
    worst_max = 0.0
    rss_minus_sq = 0.0
    rss_plus_sq = 0.0
    variance = 0.0
    statistical_ready = True

    for index, raw in enumerate(contributors):
        if not isinstance(raw, dict):
            raise ValueError(f"Tolerance contributor {index + 1} must be an object")
        value = _finite(raw.get("nominal_mm"), f"contributor {index + 1} nominal_mm")
        minus = _finite(raw.get("minus_mm", 0.0), f"contributor {index + 1} minus_mm")
        plus = _finite(raw.get("plus_mm", 0.0), f"contributor {index + 1} plus_mm")
        coefficient = _finite(raw.get("coefficient", 1.0), f"contributor {index + 1} coefficient")
        if minus < 0.0 or plus < 0.0:
            raise ValueError("Tolerance minus_mm and plus_mm must be non-negative magnitudes")

        sigma_raw = raw.get("sigma_mm")
        sigma = None if sigma_raw is None else _finite(sigma_raw, f"contributor {index + 1} sigma_mm")
        if sigma is not None and sigma < 0.0:
            raise ValueError("Tolerance sigma_mm must be non-negative")
        if abs(coefficient) > 1e-15 and sigma is None:
            statistical_ready = False

        dimension_low = value - minus
        dimension_high = value + plus
        term_low = min(coefficient * dimension_low, coefficient * dimension_high)
        term_high = max(coefficient * dimension_low, coefficient * dimension_high)
        term_nominal = coefficient * value
        negative_width = term_nominal - term_low
        positive_width = term_high - term_nominal

        nominal += term_nominal
        worst_min += term_low
        worst_max += term_high
        rss_minus_sq += negative_width * negative_width
        rss_plus_sq += positive_width * positive_width
        if sigma is not None:
            variance += (abs(coefficient) * sigma) ** 2

        rows.append({
            "id": str(raw.get("id") or f"C{index + 1}"),
            "name": str(raw.get("name") or f"Dimension {index + 1}"),
            "source": raw.get("source"),
            "nominal_mm": value,
            "minus_mm": minus,
            "plus_mm": plus,
            "sigma_mm": sigma,
            "coefficient": coefficient,
            "stack_nominal_contribution_mm": term_nominal,
            "stack_min_contribution_mm": term_low,
            "stack_max_contribution_mm": term_high,
            "negative_width_mm": negative_width,
            "positive_width_mm": positive_width,
            "worst_case_span_contribution_mm": term_high - term_low,
        })

    rss_minus = math.sqrt(rss_minus_sq)
    rss_plus = math.sqrt(rss_plus_sq)
    combined_sigma = math.sqrt(variance) if statistical_ready else None

    total_wc_span = max(worst_max - worst_min, 0.0)
    for row in rows:
        row["worst_case_span_share"] = (
            row["worst_case_span_contribution_mm"] / total_wc_span if total_wc_span > 1e-15 else 0.0
        )
        if combined_sigma is not None and combined_sigma > 1e-15 and row["sigma_mm"] is not None:
            row["statistical_variance_share"] = (
                (abs(row["coefficient"]) * row["sigma_mm"]) ** 2 / (combined_sigma * combined_sigma)
            )
        else:
            row["statistical_variance_share"] = None

    lower_spec = None if lower_spec_mm is None else _finite(lower_spec_mm, "lower_spec_mm")
    upper_spec = None if upper_spec_mm is None else _finite(upper_spec_mm, "upper_spec_mm")
    if lower_spec is not None and upper_spec is not None and lower_spec > upper_spec:
        raise ValueError("lower_spec_mm cannot exceed upper_spec_mm")

    worst_case_pass = None
    rss_pass = None
    lower_wc_margin = None
    upper_wc_margin = None
    if lower_spec is not None or upper_spec is not None:
        lower_wc_margin = None if lower_spec is None else worst_min - lower_spec
        upper_wc_margin = None if upper_spec is None else upper_spec - worst_max
        worst_case_pass = (lower_spec is None or worst_min >= lower_spec) and (upper_spec is None or worst_max <= upper_spec)
        rss_min = nominal - rss_minus
        rss_max = nominal + rss_plus
        rss_pass = (lower_spec is None or rss_min >= lower_spec) and (upper_spec is None or rss_max <= upper_spec)

    statistical: dict[str, Any] = {
        "available": statistical_ready,
        "combined_sigma_mm": combined_sigma,
        "three_sigma_min_mm": None if combined_sigma is None else nominal - 3.0 * combined_sigma,
        "three_sigma_max_mm": None if combined_sigma is None else nominal + 3.0 * combined_sigma,
        "yield_fraction": None,
        "defect_ppm": None,
        "cp": None,
        "cpk": None,
        "assumption": "Independent, centered normal contributors; every active contributor must provide explicit sigma_mm.",
    }
    if statistical_ready and combined_sigma is not None:
        if combined_sigma <= 1e-15:
            inside = (lower_spec is None or nominal >= lower_spec) and (upper_spec is None or nominal <= upper_spec)
            if lower_spec is not None or upper_spec is not None:
                statistical["yield_fraction"] = 1.0 if inside else 0.0
                statistical["defect_ppm"] = 0.0 if inside else 1_000_000.0
        else:
            lower_probability = 0.0 if lower_spec is None else _normal_cdf((lower_spec - nominal) / combined_sigma)
            upper_probability = 1.0 if upper_spec is None else _normal_cdf((upper_spec - nominal) / combined_sigma)
            if lower_spec is not None or upper_spec is not None:
                yield_fraction = max(0.0, min(1.0, upper_probability - lower_probability))
                statistical["yield_fraction"] = yield_fraction
                statistical["defect_ppm"] = (1.0 - yield_fraction) * 1_000_000.0
            if lower_spec is not None and upper_spec is not None:
                statistical["cp"] = (upper_spec - lower_spec) / (6.0 * combined_sigma)
                statistical["cpk"] = min(
                    (upper_spec - nominal) / (3.0 * combined_sigma),
                    (nominal - lower_spec) / (3.0 * combined_sigma),
                )

    ranked = sorted(
        deepcopy(rows),
        key=lambda row: (-float(row["worst_case_span_contribution_mm"]), str(row["name"])),
    )

    return {
        "name": str(name or "Tolerance stack"),
        "method": "deterministic 1D worst-case + independent RSS tolerance stack",
        "solver": "ForgeCAD ToleranceStack",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "nominal_mm": nominal,
        "worst_case": {
            "min_mm": worst_min,
            "max_mm": worst_max,
            "span_mm": worst_max - worst_min,
            "minus_from_nominal_mm": nominal - worst_min,
            "plus_from_nominal_mm": worst_max - nominal,
            "passes_spec": worst_case_pass,
            "lower_margin_mm": lower_wc_margin,
            "upper_margin_mm": upper_wc_margin,
        },
        "rss": {
            "min_mm": nominal - rss_minus,
            "max_mm": nominal + rss_plus,
            "minus_from_nominal_mm": rss_minus,
            "plus_from_nominal_mm": rss_plus,
            "passes_spec": rss_pass,
            "note": "RSS accumulates stated tolerance widths; it is not a probability statement unless process distributions are independently characterized.",
        },
        "statistical": statistical,
        "spec": {"lower_mm": lower_spec, "upper_mm": upper_spec},
        "contributors": rows,
        "sensitivity_ranked": ranked,
        "assumptions": [
            "One-dimensional linear stack with constant signed coefficients.",
            "Worst-case limits assume every contributor reaches its adverse limit simultaneously.",
            "RSS assumes contributors are independent for design-iteration screening.",
            "Statistical yield is reported only from explicit sigma values and assumes centered independent normal contributors.",
            "Correlation, thermal expansion, deformation under load, geometric tolerancing and measurement-system uncertainty require separate treatment unless encoded as contributors.",
        ],
        "physical_verification": False,
    }


def _path_value(root: Any, path: str) -> Any:
    value = root
    for token in [part for part in path.split(".") if part]:
        if isinstance(value, dict):
            if token not in value:
                raise KeyError(path)
            value = value[token]
        elif isinstance(value, list):
            value = value[int(token)]
        else:
            raise KeyError(path)
    return value


def _project_contributor(row: dict[str, Any], project: dict[str, Any], env: dict[str, float]) -> dict[str, Any]:
    resolved_row = parametric_expressions._resolve_tree(deepcopy(row), env)
    object_id = resolved_row.get("object_id") or resolved_row.get("part_id") or resolved_row.get("target_id")
    parameter = str(resolved_row.get("parameter") or resolved_row.get("path") or "").strip()
    design_parameter = str(resolved_row.get("design_parameter") or "").strip()

    source = "literal"
    if resolved_row.get("nominal_mm") is not None:
        nominal = _finite(resolved_row.get("nominal_mm"), "nominal_mm")
    elif design_parameter:
        if design_parameter not in env:
            raise ValueError(f"Unknown design parameter {design_parameter!r} in tolerance contributor")
        nominal = env[design_parameter]
        source = f"design_parameter:{design_parameter}"
    elif object_id and parameter:
        obj = core.object_by_id(str(object_id))
        resolved_obj = parametric_expressions.resolve_object(obj, project)
        path = parameter if "." in parameter else f"params.{parameter}"
        try:
            nominal = _finite(_path_value(resolved_obj, path), f"{object_id}.{path}")
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"Tolerance contributor cannot resolve {object_id}.{path}") from exc
        source = f"object:{object_id}:{path}"
    else:
        raise ValueError("Tolerance contributor needs nominal_mm, design_parameter, or object_id + parameter")

    return {
        "id": str(resolved_row.get("id") or core.uid()),
        "name": str(resolved_row.get("name") or parameter or design_parameter or "Dimension"),
        "nominal_mm": nominal,
        "minus_mm": resolved_row.get("minus_mm", 0.0),
        "plus_mm": resolved_row.get("plus_mm", 0.0),
        "sigma_mm": resolved_row.get("sigma_mm"),
        "coefficient": resolved_row.get("coefficient", 1.0),
        "source": source,
    }


def project_stacks(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    env = parametric_expressions.resolve_parameters(source)
    contributor_rows: dict[str, list[dict[str, Any]]] = {}
    specs: dict[str, dict[str, Any]] = {}

    for raw in source.get("constraints") or []:
        if not isinstance(raw, dict):
            continue
        typ = str(raw.get("type") or raw.get("kind") or "").strip().lower()
        if typ not in _TOLERANCE_TYPES:
            continue
        stack = str(raw.get("stack") or raw.get("stack_id") or "default").strip() or "default"
        if typ in _TOLERANCE_SPEC_TYPES:
            resolved = parametric_expressions._resolve_tree(deepcopy(raw), env)
            specs[stack] = {
                "lower_spec_mm": resolved.get("lower_spec_mm", resolved.get("lower_mm")),
                "upper_spec_mm": resolved.get("upper_spec_mm", resolved.get("upper_mm")),
                "name": str(resolved.get("name") or stack),
            }
        else:
            contributor_rows.setdefault(stack, []).append(raw)

    items: list[dict[str, Any]] = []
    for stack, rows in sorted(contributor_rows.items()):
        spec = specs.get(stack, {})
        try:
            contributors = [_project_contributor(row, source, env) for row in rows]
            result = analyze_stack(
                contributors,
                name=str(spec.get("name") or stack),
                lower_spec_mm=spec.get("lower_spec_mm"),
                upper_spec_mm=spec.get("upper_spec_mm"),
            )
            result.update({"id": stack, "source": "project.constraints", "ok": True})
        except Exception as exc:
            result = {
                "id": stack,
                "name": str(spec.get("name") or stack),
                "source": "project.constraints",
                "ok": False,
                "error": str(exc),
                "physical_verification": False,
            }
        items.append(result)

    orphan_specs = sorted(set(specs) - set(contributor_rows))
    for stack in orphan_specs:
        items.append({
            "id": stack,
            "name": str(specs[stack].get("name") or stack),
            "source": "project.constraints",
            "ok": False,
            "error": "Tolerance spec has no contributors.",
            "physical_verification": False,
        })

    return {
        "version": "2.0.0",
        "count": len(items),
        "ok": all(bool(item.get("ok")) for item in items),
        "items": items,
        "design_parameter_values": dict(sorted(env.items())),
    }


def _project_boundary_conditions_without_tolerance(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    """Keep manufacturing/tolerance metadata from masquerading as unsupported FEA BCs."""
    assert _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS is not None
    filtered = deepcopy(project)
    filtered["constraints"] = [
        row
        for row in filtered.get("constraints") or []
        if not isinstance(row, dict)
        or str(row.get("type") or row.get("kind") or "").strip().lower() not in _TOLERANCE_TYPES
    ]
    return _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS(filtered, object_id)


def _replace_latest_simulation_result(object_id: str, result: dict[str, Any]) -> None:
    for simulation in reversed(core.PROJECT.get("simulations") or []):
        if str(simulation.get("object_id") or "") == object_id and not simulation.get("stale"):
            simulation["result"] = deepcopy(result)
            core.persist()
            return


def _run_simulation(self: Any, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_RUN_SIMULATION is not None
    result = _ORIGINAL_RUN_SIMULATION(selected_object_id, payload)
    stacks = project_stacks(core.PROJECT)
    if stacks["count"]:
        result["tolerance_stacks"] = stacks
        result.setdefault("analysis_provenance", {})["tolerance_result"] = "canonical_project_constraints"
        object_id = str(result.get("object_id") or "")
        if object_id:
            _replace_latest_simulation_result(object_id, result)
    return result


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_RUN_SIMULATION, _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS
    if _INSTALLED:
        return
    _ORIGINAL_RUN_SIMULATION = legacy.PROJECT.run_simulation
    _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS = project_structural.project_boundary_conditions
    legacy.PROJECT.run_simulation = MethodType(_run_simulation, legacy.PROJECT)
    project_structural.project_boundary_conditions = _project_boundary_conditions_without_tolerance

    app = legacy.app

    @app.post("/v2/analysis/tolerance-stack", dependencies=[Depends(legacy.require_session)])
    async def tolerance_stack(request: ToleranceStackRequest) -> dict[str, Any]:
        try:
            result = analyze_stack(
                [row.model_dump() for row in request.contributors],
                name=request.name,
                lower_spec_mm=request.lower_spec_mm,
                upper_spec_mm=request.upper_spec_mm,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if request.record:
            core.record_simulation("tolerance_stack", None, request.model_dump(), result)
        return result

    @app.get("/v2/analysis/tolerance-stacks", dependencies=[Depends(legacy.require_session)])
    async def tolerance_stacks() -> dict[str, Any]:
        try:
            return project_stacks(core.PROJECT)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    _INSTALLED = True
