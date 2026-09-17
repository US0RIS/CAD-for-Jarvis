from __future__ import annotations

"""Named design parameters and safe expression-driven geometry for ForgeCAD 2.0.

ForgeCAD's first geometry layers were editable but predominantly literal: a plate might
store ``x=80`` and ``y=42`` without encoding *why* those dimensions relate. This module
adds the missing parametric-design layer while keeping the deterministic CAD kernel in
control.

Canonical project state may contain::

    design_parameters = {
        "board_width": {"value": 85.0, "unit": "mm"},
        "clearance": {"value": 1.5, "unit": "mm"},
        "enclosure_width": {"expression": "board_width + 2 * clearance", "unit": "mm"},
    }

Custom-part ``params`` and feature values may reference them with expression nodes::

    {"x": {"expr": "enclosure_width"}, "y": 60.0, "z": {"expr": "wall * 2"}}

Expressions are parsed with Python's AST but never executed with ``eval``. Only numeric
operators, named design parameters, constants, and a small mathematical whitelist are
accepted. Parameter updates are branch-safe, participate in undo/history, invalidate
analysis results, and regenerate geometry on demand.
"""

import ast
from copy import deepcopy
import math
import re
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from ..engineering_state import EngineeringProject
from ..v110 import analysis, core


_INSTALLED = False
_ORIGINAL_BUILD_SHAPE: Callable[..., Any] | None = None
_ORIGINAL_TESSELLATE: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_EXECUTE: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_MANUFACTURING_REVIEW: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_GEOMETRY_CACHE_KEY: Callable[[dict[str, Any]], str] | None = None
_ORIGINAL_SOLVE_BOX: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_CONVERGENCE_STUDY: Callable[..., dict[str, Any]] | None = None

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {"pi", "e", "tau"}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": lambda x: abs(float(x)),
    "min": lambda *values: min(float(value) for value in values),
    "max": lambda *values: max(float(value) for value in values),
    "sqrt": lambda x: math.sqrt(float(x)),
    "sin": lambda x: math.sin(float(x)),
    "cos": lambda x: math.cos(float(x)),
    "tan": lambda x: math.tan(float(x)),
    "asin": lambda x: math.asin(float(x)),
    "acos": lambda x: math.acos(float(x)),
    "atan": lambda x: math.atan(float(x)),
    "radians": lambda x: math.radians(float(x)),
    "degrees": lambda x: math.degrees(float(x)),
    "floor": lambda x: float(math.floor(float(x))),
    "ceil": lambda x: float(math.ceil(float(x))),
}
_ALLOWED_EXPR_NODE_KEYS = {"expr", "unit", "description"}


class ParameterRequest(BaseModel):
    value: float | None = None
    expression: str | None = None
    unit: str = ""
    description: str = ""


def _definition_map(project: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    raw = (project or core.PROJECT).get("design_parameters") or {}
    if not isinstance(raw, dict):
        raise ValueError("design_parameters must be an object keyed by parameter name")
    result: dict[str, dict[str, Any]] = {}
    for name, definition in raw.items():
        key = str(name)
        if not _NAME.fullmatch(key):
            raise ValueError(f"Invalid design parameter name: {key!r}")
        if key in _RESERVED or key in _FUNCTIONS:
            raise ValueError(f"Design parameter name {key!r} is reserved")
        if isinstance(definition, (int, float)):
            result[key] = {"value": float(definition), "unit": "", "description": ""}
        elif isinstance(definition, dict):
            result[key] = deepcopy(definition)
        else:
            raise ValueError(f"Design parameter {key!r} must be numeric or an object")
    return result


def _eval_node(node: ast.AST, resolve_name: Callable[[str], float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, resolve_name)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Parametric expressions may contain numeric constants only")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return float(_CONSTANTS[node.id])
        return float(resolve_name(node.id))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand, resolve_name)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, resolve_name)
        right = _eval_node(node.right, resolve_name)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if abs(right) <= 1e-15:
                raise ValueError("Parametric expression divides by zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > 8 or abs(left) > 1e9:
                raise ValueError("Parametric exponent is outside the safe evaluation range")
            return left ** right
        if isinstance(node.op, ast.Mod):
            if abs(right) <= 1e-15:
                raise ValueError("Parametric expression modulo by zero")
            return left % right
        raise ValueError(f"Unsupported parametric operator: {type(node.op).__name__}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError("Parametric expressions may call only the ForgeCAD math whitelist")
        if node.keywords:
            raise ValueError("Parametric math functions do not accept keyword arguments")
        args = [_eval_node(arg, resolve_name) for arg in node.args]
        if not args:
            raise ValueError(f"{node.func.id} requires at least one argument")
        return float(_FUNCTIONS[node.func.id](*args))
    raise ValueError(f"Unsupported syntax in parametric expression: {type(node).__name__}")


def evaluate_expression(expression: str, resolve_name: Callable[[str], float]) -> float:
    text = str(expression).strip()
    if not text:
        raise ValueError("Parametric expression cannot be empty")
    if len(text) > 512:
        raise ValueError("Parametric expression exceeds the 512-character safety limit")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid parametric expression: {exc.msg}") from exc
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise ValueError("Parametric expression is too complex")
    value = float(_eval_node(tree, resolve_name))
    if not math.isfinite(value):
        raise ValueError("Parametric expression produced a non-finite result")
    return value


def resolve_parameters(project: dict[str, Any] | None = None) -> dict[str, float]:
    definitions = _definition_map(project)
    resolved: dict[str, float] = {}
    stack: list[str] = []

    def resolve_name(name: str) -> float:
        if name in resolved:
            return resolved[name]
        if name not in definitions:
            raise ValueError(f"Unknown design parameter: {name}")
        if name in stack:
            cycle = " -> ".join(stack + [name])
            raise ValueError(f"Cyclic design parameter dependency: {cycle}")
        stack.append(name)
        definition = definitions[name]
        expression = definition.get("expression")
        value = definition.get("value")
        try:
            if expression not in (None, ""):
                result = evaluate_expression(str(expression), resolve_name)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                result = float(value)
            else:
                raise ValueError(f"Design parameter {name!r} needs a numeric value or expression")
        finally:
            stack.pop()
        if not math.isfinite(result):
            raise ValueError(f"Design parameter {name!r} resolved to a non-finite value")
        resolved[name] = result
        return result

    for name in definitions:
        resolve_name(name)
    return resolved


def parameter_report(project: dict[str, Any] | None = None) -> dict[str, Any]:
    definitions = _definition_map(project)
    values = resolve_parameters(project)
    return {
        "count": len(definitions),
        "parameters": [
            {
                "name": name,
                "value": values[name],
                "literal_value": definition.get("value"),
                "expression": definition.get("expression"),
                "unit": str(definition.get("unit") or ""),
                "description": str(definition.get("description") or ""),
                "derived": bool(definition.get("expression") not in (None, "")),
            }
            for name, definition in sorted(definitions.items())
        ],
        "values": dict(sorted(values.items())),
    }


def _is_expr_node(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("expr"), str)
        and set(value).issubset(_ALLOWED_EXPR_NODE_KEYS)
    )


def _resolve_tree(value: Any, env: dict[str, float]) -> Any:
    if _is_expr_node(value):
        return evaluate_expression(str(value["expr"]), lambda name: env[name] if name in env else (_raise_unknown(name)))
    if isinstance(value, dict):
        return {key: _resolve_tree(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_tree(item, env) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_tree(item, env) for item in value)
    return value


def _raise_unknown(name: str) -> float:
    raise ValueError(f"Unknown design parameter: {name}")


def resolve_object(obj: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a geometry-resolved copy while preserving canonical symbolic project data."""
    if obj.get("kind") == "component" or obj.get("component_ref"):
        return deepcopy(obj)
    env = resolve_parameters(project)
    resolved = deepcopy(obj)
    # Geometry-defining data may be symbolic. Placement stays literal because the scene
    # contract currently exposes base_transform directly to Three.js.
    resolved["params"] = _resolve_tree(resolved.get("params") or {}, env)
    resolved["features"] = _resolve_tree(resolved.get("features") or [], env)
    return resolved


def _validate_all_parametric_geometry(project: dict[str, Any] | None = None) -> None:
    target = project or core.PROJECT
    resolve_parameters(target)
    for obj in target.get("objects", []):
        if obj.get("kind") == "component" or obj.get("component_ref"):
            continue
        resolved = resolve_object(obj, target)
        # Do not force expensive B-rep regeneration for every object here. The critical
        # transactional validation is expression safety/dependency resolution; geometry
        # construction remains lazy and authoritative when requested.
        for value in _walk_numbers(resolved.get("params") or {}):
            if not math.isfinite(value):
                raise ValueError(f"Object {obj.get('id')} contains a non-finite resolved parameter")


def _walk_numbers(value: Any):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_numbers(item)


def _set_parameter(args: dict[str, Any], actor: str, reason: str) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not _NAME.fullmatch(name) or name in _RESERVED or name in _FUNCTIONS:
        raise ValueError("Design parameter name must be a non-reserved identifier")
    value = args.get("value")
    expression = args.get("expression")
    if expression not in (None, "") and value is not None:
        raise ValueError("Set either value or expression for a design parameter, not both")
    if expression in (None, ""):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("Literal design parameter value must be a finite number")
    else:
        expression = str(expression).strip()

    with core.LOCK:
        core.ensure_mutable(actor, reason or f"set parameter {name}")
        before = deepcopy(core.PROJECT)
        definitions = core.PROJECT.setdefault("design_parameters", {})
        definitions[name] = {
            "value": float(value) if expression in (None, "") else None,
            "expression": expression if expression not in (None, "") else None,
            "unit": str(args.get("unit") or ""),
            "description": str(args.get("description") or ""),
        }
        try:
            _validate_all_parametric_geometry(core.PROJECT)
        except Exception:
            core.PROJECT.clear()
            core.PROJECT.update(before)
            raise
        core.mark_simulations_stale(None)
        core.push_history("set_design_parameter", actor, reason or f"Set design parameter {name}")
        core.persist()
    return {"ok": True, "op": "set_design_parameter", "parameter": name, "parameters": parameter_report(), "project": core.PROJECT, "active_design": core.ACTIVE_DESIGN}


def _delete_parameter(args: dict[str, Any], actor: str, reason: str) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    with core.LOCK:
        core.ensure_mutable(actor, reason or f"delete parameter {name}")
        definitions = core.PROJECT.setdefault("design_parameters", {})
        if name not in definitions:
            raise KeyError(name)
        before = deepcopy(core.PROJECT)
        definitions.pop(name)
        try:
            _validate_all_parametric_geometry(core.PROJECT)
        except Exception:
            core.PROJECT.clear()
            core.PROJECT.update(before)
            raise ValueError(f"Cannot delete design parameter {name!r}; another parameter or geometry expression still depends on it")
        core.mark_simulations_stale(None)
        core.push_history("delete_design_parameter", actor, reason or f"Delete design parameter {name}")
        core.persist()
    return {"ok": True, "op": "delete_design_parameter", "parameter": name, "parameters": parameter_report(), "project": core.PROJECT, "active_design": core.ACTIVE_DESIGN}


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    assert _ORIGINAL_EXECUTE is not None
    if op == "set_design_parameter":
        return _set_parameter(deepcopy(args or {}), actor, reason)
    if op == "delete_design_parameter":
        return _delete_parameter(deepcopy(args or {}), actor, reason)
    return _ORIGINAL_EXECUTE(op, args, actor=actor, reason=reason)


def _build_shape(obj: dict[str, Any]):
    assert _ORIGINAL_BUILD_SHAPE is not None
    return _ORIGINAL_BUILD_SHAPE(resolve_object(obj))


def _tessellate(obj: dict[str, Any], tolerance: float = 0.35) -> dict[str, Any]:
    assert _ORIGINAL_TESSELLATE is not None
    return _ORIGINAL_TESSELLATE(resolve_object(obj), tolerance=tolerance)


def _manufacturing_review(obj: dict[str, Any], process: str = "fdm") -> dict[str, Any]:
    assert _ORIGINAL_MANUFACTURING_REVIEW is not None
    return _ORIGINAL_MANUFACTURING_REVIEW(resolve_object(obj), process)


def _parameterized_cache_key(obj: dict[str, Any]) -> str:
    assert _ORIGINAL_GEOMETRY_CACHE_KEY is not None
    # The canonical object intentionally retains symbolic expressions. Add the resolved
    # environment so a global design-parameter change invalidates every dependent mesh.
    return _ORIGINAL_GEOMETRY_CACHE_KEY(obj) + "|design_parameters=" + repr(sorted(resolve_parameters().items()))


def _install_solver_wrappers() -> None:
    global _ORIGINAL_SOLVE_BOX, _ORIGINAL_CONVERGENCE_STUDY
    try:
        from . import structural_fea
    except Exception:
        return
    if _ORIGINAL_SOLVE_BOX is None:
        _ORIGINAL_SOLVE_BOX = structural_fea.solve_box

        def solve_box(obj: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            assert _ORIGINAL_SOLVE_BOX is not None
            return _ORIGINAL_SOLVE_BOX(resolve_object(obj), **kwargs)

        structural_fea.solve_box = solve_box
    if _ORIGINAL_CONVERGENCE_STUDY is None:
        _ORIGINAL_CONVERGENCE_STUDY = structural_fea.convergence_study

        def convergence_study(obj: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            assert _ORIGINAL_CONVERGENCE_STUDY is not None
            return _ORIGINAL_CONVERGENCE_STUDY(resolve_object(obj), **kwargs)

        structural_fea.convergence_study = convergence_study


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_BUILD_SHAPE, _ORIGINAL_TESSELLATE, _ORIGINAL_EXECUTE
    global _ORIGINAL_MANUFACTURING_REVIEW, _ORIGINAL_GEOMETRY_CACHE_KEY
    if _INSTALLED:
        return

    _ORIGINAL_BUILD_SHAPE = core.build_shape
    _ORIGINAL_TESSELLATE = core.tessellate
    _ORIGINAL_EXECUTE = core.execute
    _ORIGINAL_MANUFACTURING_REVIEW = analysis.manufacturing_review
    core.build_shape = _build_shape
    core.tessellate = _tessellate
    core.execute = _execute
    analysis.manufacturing_review = _manufacturing_review

    # scene_cache is installed before this module in v200.__init__. Its scene function
    # resolves this module-global key dynamically, so replacing it preserves the
    # transform-independent cache while adding a parameter-environment invalidator.
    try:
        from . import scene_cache
        _ORIGINAL_GEOMETRY_CACHE_KEY = scene_cache.geometry_cache_key
        scene_cache.geometry_cache_key = _parameterized_cache_key
        EngineeringProject._mesh_cache_key = staticmethod(_parameterized_cache_key)  # type: ignore[method-assign]
    except Exception:
        _ORIGINAL_GEOMETRY_CACHE_KEY = None

    _install_solver_wrappers()
    app = legacy.app

    @app.get("/v2/parameters", dependencies=[Depends(legacy.require_session)])
    async def parameters() -> dict[str, Any]:
        try:
            return parameter_report()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/v2/parameters/{name}", dependencies=[Depends(legacy.require_session)])
    async def set_parameter(name: str, request: ParameterRequest) -> dict[str, Any]:
        try:
            result = _set_parameter({"name": name, **request.model_dump()}, "human", f"Set design parameter {name}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        legacy.PROJECT._mesh_cache.clear()
        snapshot = legacy.PROJECT.snapshot()
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"parameters": result["parameters"], "project": snapshot}

    @app.delete("/v2/parameters/{name}", dependencies=[Depends(legacy.require_session)])
    async def delete_parameter(name: str) -> dict[str, Any]:
        try:
            result = _delete_parameter({"name": name}, "human", f"Delete design parameter {name}")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Design parameter not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        legacy.PROJECT._mesh_cache.clear()
        snapshot = legacy.PROJECT.snapshot()
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"parameters": result["parameters"], "project": snapshot}

    _INSTALLED = True
