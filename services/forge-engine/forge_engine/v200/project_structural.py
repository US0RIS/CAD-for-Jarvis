from __future__ import annotations

"""Canonical project boundary conditions for ForgeCAD 2.0 solid FEA.

The first SolidFEA path used an implicit cantilever: local x-min fixed and a force on
local x-max. That is useful as a preview, but a real engineering project already has a
canonical ``loads`` and ``constraints`` graph. This layer makes those records drive the
3D solver when they are present.

Scope remains deliberately explicit and fail-closed: exact unfeatured box geometry,
face-distributed force vectors, and fixed/partially-fixed orthogonal faces. Unsupported
boundary-condition records targeting the analyzed part block the project-BC solve rather
than being silently ignored. The reduced-order/implicit-cantilever result is retained for
comparison, never mislabeled as the project-defined solution.
"""

from copy import deepcopy
import math
from types import MethodType
from typing import Any
import warnings

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import MatrixRankWarning, spsolve

from ..v110 import core
from . import structural_fea


_INSTALLED = False
_ORIGINAL_RUN_SIMULATION = None
_AXES = {"x": 0, "y": 1, "z": 2}
_FACE_ALIASES = {
    "xmin": "x_min", "x-min": "x_min", "x_min": "x_min", "local x-min": "x_min", "local_x_min": "x_min",
    "xmax": "x_max", "x-max": "x_max", "x_max": "x_max", "local x-max": "x_max", "local_x_max": "x_max",
    "ymin": "y_min", "y-min": "y_min", "y_min": "y_min", "local y-min": "y_min", "local_y_min": "y_min",
    "ymax": "y_max", "y-max": "y_max", "y_max": "y_max", "local y-max": "y_max", "local_y_max": "y_max",
    "zmin": "z_min", "z-min": "z_min", "z_min": "z_min", "local z-min": "z_min", "local_z_min": "z_min",
    "zmax": "z_max", "z-max": "z_max", "z_max": "z_max", "local z-max": "z_max", "local_z_max": "z_max",
}
_SUPPORT_TYPES = {"fixed", "fixed_support", "support", "clamp", "clamped", "encastre"}
_FORCE_TYPES = {"force", "face_force", "distributed_force", "force_vector"}


def _target_id(row: dict[str, Any]) -> str | None:
    for key in ("object_id", "part_id", "target_id", "body_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _face(value: Any) -> str:
    key = " ".join(str(value or "").strip().lower().split())
    key = key.replace("+", "max").replace("−", "-")
    if key in _FACE_ALIASES:
        return _FACE_ALIASES[key]
    compact = key.replace(" ", "_")
    if compact in _FACE_ALIASES:
        return _FACE_ALIASES[compact]
    if compact in {"+x", "x+"}:
        return "x_max"
    if compact in {"-x", "x-"}:
        return "x_min"
    if compact in {"+y", "y+"}:
        return "y_max"
    if compact in {"-y", "y-"}:
        return "y_min"
    if compact in {"+z", "z+"}:
        return "z_max"
    if compact in {"-z", "z-"}:
        return "z_min"
    raise ValueError(f"Unsupported boundary-condition face {value!r}; use x_min/x_max/y_min/y_max/z_min/z_max")


def _dofs(row: dict[str, Any]) -> list[str]:
    raw = row.get("dofs", row.get("axes", row.get("fixed_axes")))
    if raw in (None, "", "all", "xyz"):
        return ["x", "y", "z"]
    if isinstance(raw, str):
        raw = [token for token in raw.lower().replace(",", " ").split() if token]
    if not isinstance(raw, list):
        raise ValueError("Fixed-support dofs must be a list containing x, y and/or z")
    axes = []
    for value in raw:
        axis = str(value).strip().lower()
        if axis not in _AXES:
            raise ValueError(f"Unsupported fixed degree of freedom {value!r}; use x, y or z")
        if axis not in axes:
            axes.append(axis)
    if not axes:
        raise ValueError("Fixed support must constrain at least one translational degree of freedom")
    return axes


def _force_vector(row: dict[str, Any]) -> np.ndarray:
    raw = row.get("vector_n", row.get("force_vector_n", row.get("vector")))
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        vector = np.asarray([float(value) for value in raw], dtype=float)
    elif any(key in row for key in ("fx_n", "fy_n", "fz_n")):
        vector = np.asarray([float(row.get("fx_n", 0.0)), float(row.get("fy_n", 0.0)), float(row.get("fz_n", 0.0))], dtype=float)
    else:
        force = float(row.get("force_n", row.get("magnitude_n", row.get("value", 0.0))))
        direction = str(row.get("direction", row.get("axis", "z"))).strip().lower().replace(" ", "")
        sign = -1.0 if direction.startswith("-") or direction.endswith("-") else 1.0
        axis = direction.replace("+", "").replace("-", "")
        if axis not in _AXES:
            raise ValueError(f"Force direction {direction!r} must be x, y or z (optionally signed)")
        vector = np.zeros(3, dtype=float)
        vector[_AXES[axis]] = sign * force
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError("Force vector must contain three finite Newton components")
    if float(np.linalg.norm(vector)) <= 1e-12:
        raise ValueError("Force vector must be non-zero")
    return vector


def project_boundary_conditions(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    supports: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    targeted = 0

    for row in project.get("constraints") or []:
        if not isinstance(row, dict) or _target_id(row) != object_id:
            continue
        targeted += 1
        typ = str(row.get("type", row.get("kind", "fixed"))).strip().lower()
        try:
            if typ not in _SUPPORT_TYPES:
                raise ValueError(f"Constraint type {typ!r} is not supported by project SolidFEA")
            supports.append({
                "id": str(row.get("id") or ""),
                "type": "fixed",
                "face": _face(row.get("face", row.get("region"))),
                "dofs": _dofs(row),
            })
        except (TypeError, ValueError) as exc:
            unsupported.append({"kind": "constraint", "id": str(row.get("id") or ""), "reason": str(exc)})

    for row in project.get("loads") or []:
        if not isinstance(row, dict) or _target_id(row) != object_id:
            continue
        targeted += 1
        typ = str(row.get("type", row.get("kind", "force"))).strip().lower()
        try:
            if typ not in _FORCE_TYPES:
                raise ValueError(f"Load type {typ!r} is not supported by project SolidFEA")
            vector = _force_vector(row)
            loads.append({
                "id": str(row.get("id") or ""),
                "type": "force",
                "face": _face(row.get("face", row.get("region"))),
                "vector_n": vector.tolist(),
            })
        except (TypeError, ValueError) as exc:
            unsupported.append({"kind": "load", "id": str(row.get("id") or ""), "reason": str(exc)})

    return {
        "object_id": object_id,
        "targeted_record_count": targeted,
        "supports": supports,
        "loads": loads,
        "unsupported": unsupported,
        "complete": targeted > 0 and bool(supports) and bool(loads) and not unsupported,
    }


def _face_nodes(nodes: np.ndarray, face: str, dims_m: tuple[float, float, float]) -> np.ndarray:
    lx, ly, lz = dims_m
    targets = {
        "x_min": (0, 0.0), "x_max": (0, lx),
        "y_min": (1, -ly / 2.0), "y_max": (1, ly / 2.0),
        "z_min": (2, -lz / 2.0), "z_max": (2, lz / 2.0),
    }
    axis, target = targets[face]
    tolerance = max(max(dims_m), 1.0) * 1e-12
    return np.flatnonzero(np.isclose(nodes[:, axis], target, atol=tolerance))


def solve_project_box(
    obj: dict[str, Any],
    project: dict[str, Any] | None = None,
    *,
    mesh_counts: tuple[int, int, int] | None = None,
) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    object_id = str(obj.get("id") or "")
    boundary = project_boundary_conditions(source, object_id)
    if not boundary["targeted_record_count"]:
        return {"supported": False, "reason": "No canonical project loads or constraints target this object.", "solver_grade": "not_requested", "boundary_conditions": boundary}
    if boundary["unsupported"]:
        return {"supported": False, "reason": "One or more project boundary conditions targeting this object are outside the supported SolidFEA scope.", "solver_grade": "unsupported_boundary_conditions", "boundary_conditions": boundary}
    if not boundary["supports"]:
        return {"supported": False, "reason": "Project SolidFEA requires at least one fixed-face support targeting this object.", "solver_grade": "incomplete_boundary_conditions", "boundary_conditions": boundary}
    if not boundary["loads"]:
        return {"supported": False, "reason": "Project SolidFEA requires at least one face force targeting this object.", "solver_grade": "incomplete_boundary_conditions", "boundary_conditions": boundary}

    ok, reason = structural_fea.supported_object(obj)
    if not ok:
        return {"supported": False, "reason": reason, "solver_grade": "unsupported_geometry", "boundary_conditions": boundary}

    params = obj.get("params") or {}
    dims_mm = [float(params[key]) for key in ("x", "y", "z")]
    dims_m = tuple(value / 1000.0 for value in dims_mm)
    counts = mesh_counts or structural_fea._default_counts(dims_mm)
    counts = tuple(max(1, min(14, int(value))) for value in counts)
    node_limit = (counts[0] + 1) * (counts[1] + 1) * (counts[2] + 1)
    if node_limit > 3500:
        raise ValueError("Requested structured FEA mesh exceeds the 3,500-node interactive safety limit")

    material_id, material = structural_fea._material(obj)
    E = float(material["youngs_modulus_gpa"]) * 1e9
    nu = float(material["poisson"])
    D = structural_fea._constitutive(E, nu)
    nodes, elements = structural_fea._mesh(dims_m, counts)
    ndof = len(nodes) * 3
    rows: list[int] = []
    cols: list[int] = []
    values: list[float] = []
    element_cache: list[tuple[list[int], np.ndarray, np.ndarray]] = []

    for connectivity in elements:
        coords = nodes[np.asarray(connectivity)]
        ke = structural_fea._element_stiffness(coords, D)
        dofs = np.asarray([3 * node + axis for node in connectivity for axis in range(3)], dtype=int)
        rows.extend(np.repeat(dofs, 24).tolist())
        cols.extend(np.tile(dofs, 24).tolist())
        values.extend(ke.reshape(-1).tolist())
        element_cache.append((connectivity, coords, dofs))

    stiffness = coo_matrix((values, (rows, cols)), shape=(ndof, ndof)).tocsr()
    force = np.zeros(ndof, dtype=float)
    fixed_dofs: set[int] = set()
    support_rows: list[dict[str, Any]] = []
    for support in boundary["supports"]:
        nodes_on_face = _face_nodes(nodes, support["face"], dims_m)
        if not len(nodes_on_face):
            raise ValueError(f"Support face {support['face']} has no mesh nodes")
        for node in nodes_on_face:
            for axis in support["dofs"]:
                fixed_dofs.add(3 * int(node) + _AXES[axis])
        support_rows.append({**support, "nodes": int(len(nodes_on_face))})

    load_rows: list[dict[str, Any]] = []
    external_vector = np.zeros(3, dtype=float)
    for load in boundary["loads"]:
        nodes_on_face = _face_nodes(nodes, load["face"], dims_m)
        if not len(nodes_on_face):
            raise ValueError(f"Load face {load['face']} has no mesh nodes")
        vector = np.asarray(load["vector_n"], dtype=float)
        external_vector += vector
        per_node = vector / len(nodes_on_face)
        for node in nodes_on_face:
            force[3 * int(node):3 * int(node) + 3] += per_node
        load_rows.append({**load, "nodes": int(len(nodes_on_face)), "distribution": "uniform nodal force over selected face"})

    fixed = np.asarray(sorted(fixed_dofs), dtype=int)
    free_mask = np.ones(ndof, dtype=bool)
    free_mask[fixed] = False
    free = np.arange(ndof, dtype=int)[free_mask]
    if not len(fixed):
        raise ValueError("Project SolidFEA has no constrained degrees of freedom")
    if not len(free):
        raise ValueError("Project SolidFEA has no free degrees of freedom")

    displacement = np.zeros(ndof, dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("error", MatrixRankWarning)
        try:
            displacement[free] = spsolve(stiffness[free][:, free], force[free])
        except MatrixRankWarning as exc:
            raise ValueError("Project boundary conditions leave the finite-element model singular") from exc
    if not np.all(np.isfinite(displacement)):
        raise ValueError("Project boundary conditions produced non-finite displacement; the model is likely under-constrained")

    nodal = displacement.reshape((-1, 3))
    magnitudes = np.linalg.norm(nodal, axis=1)
    max_displacement_m = float(np.max(magnitudes))
    max_vm_pa = 0.0
    stress_rows: list[dict[str, Any]] = []
    for element_index, (connectivity, coords, dofs) in enumerate(element_cache):
        B, _ = structural_fea._b_matrix(coords, 0.0, 0.0, 0.0)
        stress = D @ (B @ displacement[dofs])
        vm = structural_fea._von_mises(stress)
        max_vm_pa = max(max_vm_pa, vm)
        stress_rows.append({
            "element": element_index,
            "von_mises_mpa": vm / 1e6,
            "stress_mpa": [float(value) / 1e6 for value in stress],
        })

    residual = stiffness @ displacement - force
    reaction_vector = np.zeros(3, dtype=float)
    for dof in fixed:
        reaction_vector[int(dof) % 3] += residual[int(dof)]
    external_norm = float(np.linalg.norm(external_vector))
    equilibrium_error = float(np.linalg.norm(reaction_vector + external_vector) / max(external_norm, 1e-12))
    energy = float(0.5 * displacement @ (stiffness @ displacement))
    yield_pa = float(material["yield_mpa"]) * 1e6
    fos = yield_pa / max(max_vm_pa, 1e-12)

    signature = {
        "object_id": object_id,
        "kind": obj.get("kind"),
        "params": obj.get("params"),
        "features": obj.get("features"),
        "material": material_id,
        "supports": boundary["supports"],
        "loads": boundary["loads"],
        "mesh_counts": counts,
    }
    return {
        "supported": True,
        "method": "3D linear-elastic structured hexahedral FEA with canonical project boundary conditions",
        "solver": "ForgeCAD SolidFEA",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "object_id": object_id,
        "boundary_condition_source": "project.loads + project.constraints",
        "supports": support_rows,
        "loads": load_rows,
        "material": {"id": material_id, "youngs_modulus_gpa": material["youngs_modulus_gpa"], "poisson": material["poisson"], "yield_mpa": material["yield_mpa"]},
        "mesh": {"element_type": "C3D8-equivalent trilinear hex", "integration": "2x2x2 Gauss", "counts": list(counts), "nodes": int(len(nodes)), "elements": int(len(elements)), "dof": int(ndof), "fixed_dof": int(len(fixed)), "free_dof": int(len(free))},
        "max_displacement_mm": max_displacement_m * 1000.0,
        "max_von_mises_stress_mpa": max_vm_pa / 1e6,
        "yield_fos": fos,
        "strain_energy_j": energy,
        "external_force_n": external_vector.tolist(),
        "reaction_n": reaction_vector.tolist(),
        "equilibrium_relative_error": equilibrium_error,
        "stress_field": stress_rows,
        "input_sha256": structural_fea._sha(signature),
        "provenance": {
            "geometry_scope": "exact parametric unfeatured box dimensions; local-coordinate analysis",
            "boundary_conditions": "canonical ForgeCAD project records",
            "material_source": "ForgeCAD authoritative material table",
            "formulation": "small-strain 3D isotropic linear elasticity",
        },
        "limitations": [
            "Linear elastic and small strain only; no plasticity or geometric nonlinearity.",
            "Face loads are uniform nodal force distributions; pressure, moments and point loads are not yet supported.",
            "Fixed supports constrain translational DOFs only; joint/contact compliance is not represented.",
            "No contact, bolt preload, residual stress, fracture or fatigue.",
            "Material is homogeneous isotropic; FDM anisotropy is not represented.",
            "Engineering-iteration solver, not certification evidence; validate critical designs independently and physically.",
        ],
    }


def _replace_latest_simulation_result(object_id: str, result: dict[str, Any]) -> None:
    for simulation in reversed(core.PROJECT.get("simulations") or []):
        if simulation.get("kind") == "engineering_screen_v2" and str(simulation.get("object_id")) == object_id and not simulation.get("stale"):
            simulation["result"] = deepcopy(result)
            core.persist()
            return


def _run_simulation(self: Any, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_RUN_SIMULATION is not None
    result = _ORIGINAL_RUN_SIMULATION(selected_object_id, payload)
    object_id = str(result.get("object_id") or "")
    try:
        obj = core.object_by_id(object_id)
    except KeyError:
        return result

    boundary = project_boundary_conditions(core.PROJECT, object_id)
    result["project_boundary_conditions"] = boundary
    if boundary["targeted_record_count"]:
        project_solid = solve_project_box(obj, core.PROJECT)
        result["structural_3d_project"] = project_solid
        provenance = result.setdefault("analysis_provenance", {})
        if project_solid.get("supported"):
            provenance["primary_structural_result"] = "structural_3d_project"
            provenance["boundary_condition_source"] = "canonical_project"
        else:
            provenance["project_boundary_conditions_supported"] = False
            provenance["project_boundary_conditions_reason"] = project_solid.get("reason")
    _replace_latest_simulation_result(object_id, result)
    return result


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_RUN_SIMULATION
    if _INSTALLED:
        return
    _ORIGINAL_RUN_SIMULATION = legacy.PROJECT.run_simulation
    legacy.PROJECT.run_simulation = MethodType(_run_simulation, legacy.PROJECT)
    _INSTALLED = True
