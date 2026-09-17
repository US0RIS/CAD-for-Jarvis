from __future__ import annotations

"""Deterministic 3D linear-elastic finite-element analysis for ForgeCAD 2.0.

This is a genuine displacement-based solid FEA path, not the v1 reduced-order beam
preview. The first production-safe scope is deliberately narrow: unfeatured ``box``
solids with isotropic materials from ForgeCAD's authoritative material table. The mesh
is a structured 8-node hexahedral grid, integrated with 2x2x2 Gauss quadrature and
solved with SciPy sparse linear algebra.

Narrow scope is intentional. ForgeCAD must prefer an explicit unsupported result over
pretending a bounding-box approximation is high-fidelity analysis for arbitrary B-reps.
The solver reports provenance, mesh metrics, equilibrium, strain energy, maximum
von-Mises stress, displacement and yield factor of safety. A convergence helper reruns
successively refined meshes and reports whether the requested quantity stabilizes.

This remains a linear isotropic, small-strain solver. Contact, plasticity, geometric
nonlinearity, anisotropic printed material, fatigue and certification are out of scope.
"""

from copy import deepcopy
import hashlib
import json
import math
from types import MethodType
from typing import Any

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

from ..v110 import core


_INSTALLED = False

_LOCAL_SIGNS = np.asarray([
    [-1.0, -1.0, -1.0],
    [ 1.0, -1.0, -1.0],
    [ 1.0,  1.0, -1.0],
    [-1.0,  1.0, -1.0],
    [-1.0, -1.0,  1.0],
    [ 1.0, -1.0,  1.0],
    [ 1.0,  1.0,  1.0],
    [-1.0,  1.0,  1.0],
], dtype=float)
_GAUSS = (-1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0))


def _sha(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _material(obj: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    material_id = str(obj.get("material") or "")
    material = core.MATERIALS.get(material_id)
    if material is None:
        raise ValueError(f"3D solid FEA requires a known isotropic material; '{material_id}' is not in the ForgeCAD material table")
    for key in ("youngs_modulus_gpa", "poisson", "yield_mpa"):
        if material.get(key) is None:
            raise ValueError(f"Material '{material_id}' is missing required FEA property {key}")
    nu = float(material["poisson"])
    if not (-0.99 < nu < 0.499):
        raise ValueError(f"Material Poisson ratio {nu} is outside the supported linear-isotropic range")
    return material_id, deepcopy(material)


def supported_object(obj: dict[str, Any]) -> tuple[bool, str]:
    if str(obj.get("kind") or "") != "box":
        return False, "The built-in 3D solid FEA currently supports exact unfeatured box solids only."
    if obj.get("features"):
        return False, "Featured box geometry requires a general-purpose tetrahedral mesher before it can use the 3D solid solver."
    params = obj.get("params") or {}
    try:
        dims = [float(params[key]) for key in ("x", "y", "z")]
    except Exception:
        return False, "Box dimensions x/y/z are required."
    if any(not math.isfinite(value) or value <= 0 for value in dims):
        return False, "Box dimensions must be finite and positive."
    scale = (obj.get("transform") or {}).get("scale", [1.0, 1.0, 1.0])
    if any(abs(float(value) - 1.0) > 1e-9 for value in scale):
        return False, "Scaled geometry must be baked into authoritative dimensions before 3D FEA."
    return True, "supported"


def _constitutive(E: float, nu: float) -> np.ndarray:
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    return np.asarray([
        [lam + 2 * mu, lam, lam, 0, 0, 0],
        [lam, lam + 2 * mu, lam, 0, 0, 0],
        [lam, lam, lam + 2 * mu, 0, 0, 0],
        [0, 0, 0, mu, 0, 0],
        [0, 0, 0, 0, mu, 0],
        [0, 0, 0, 0, 0, mu],
    ], dtype=float)


def _shape_derivatives(xi: float, eta: float, zeta: float) -> np.ndarray:
    s = _LOCAL_SIGNS
    out = np.empty((8, 3), dtype=float)
    out[:, 0] = 0.125 * s[:, 0] * (1 + s[:, 1] * eta) * (1 + s[:, 2] * zeta)
    out[:, 1] = 0.125 * s[:, 1] * (1 + s[:, 0] * xi) * (1 + s[:, 2] * zeta)
    out[:, 2] = 0.125 * s[:, 2] * (1 + s[:, 0] * xi) * (1 + s[:, 1] * eta)
    return out


def _b_matrix(coords: np.ndarray, xi: float, eta: float, zeta: float) -> tuple[np.ndarray, float]:
    dlocal = _shape_derivatives(xi, eta, zeta)
    jacobian = coords.T @ dlocal
    det_j = float(np.linalg.det(jacobian))
    if det_j <= 1e-18:
        raise ValueError("Invalid/inverted hexahedral finite element")
    dglobal = dlocal @ np.linalg.inv(jacobian)
    B = np.zeros((6, 24), dtype=float)
    for i, (dx, dy, dz) in enumerate(dglobal):
        j = 3 * i
        B[0, j] = dx
        B[1, j + 1] = dy
        B[2, j + 2] = dz
        B[3, j] = dy
        B[3, j + 1] = dx
        B[4, j + 1] = dz
        B[4, j + 2] = dy
        B[5, j] = dz
        B[5, j + 2] = dx
    return B, det_j


def _element_stiffness(coords: np.ndarray, D: np.ndarray) -> np.ndarray:
    stiffness = np.zeros((24, 24), dtype=float)
    for xi in _GAUSS:
        for eta in _GAUSS:
            for zeta in _GAUSS:
                B, det_j = _b_matrix(coords, xi, eta, zeta)
                stiffness += B.T @ D @ B * det_j
    return stiffness


def _mesh(dims_m: tuple[float, float, float], counts: tuple[int, int, int]) -> tuple[np.ndarray, list[list[int]]]:
    lx, ly, lz = dims_m
    nx, ny, nz = counts
    xs = np.linspace(0.0, lx, nx + 1)
    ys = np.linspace(-ly / 2.0, ly / 2.0, ny + 1)
    zs = np.linspace(-lz / 2.0, lz / 2.0, nz + 1)
    nodes = np.asarray([[x, y, z] for z in zs for y in ys for x in xs], dtype=float)

    def nid(i: int, j: int, k: int) -> int:
        return k * (ny + 1) * (nx + 1) + j * (nx + 1) + i

    elements: list[list[int]] = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                elements.append([
                    nid(i, j, k), nid(i + 1, j, k), nid(i + 1, j + 1, k), nid(i, j + 1, k),
                    nid(i, j, k + 1), nid(i + 1, j, k + 1), nid(i + 1, j + 1, k + 1), nid(i, j + 1, k + 1),
                ])
    return nodes, elements


def _default_counts(dims_mm: list[float], target_longest: int = 8) -> tuple[int, int, int]:
    longest = max(dims_mm)
    counts = []
    for dim in dims_mm:
        scaled = int(round(target_longest * dim / longest))
        counts.append(max(2, min(target_longest, scaled)))
    return tuple(counts)  # type: ignore[return-value]


def _von_mises(stress: np.ndarray) -> float:
    sx, sy, sz, txy, tyz, txz = [float(value) for value in stress]
    return math.sqrt(max(0.0, 0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3.0 * (txy * txy + tyz * tyz + txz * txz)))


def solve_box(
    obj: dict[str, Any],
    *,
    force_n: float = 100.0,
    support_axis: str = "x",
    load_direction: str = "z",
    mesh_counts: tuple[int, int, int] | None = None,
) -> dict[str, Any]:
    ok, reason = supported_object(obj)
    if not ok:
        return {"supported": False, "reason": reason, "solver_grade": "unsupported"}
    if support_axis.lower() != "x":
        return {"supported": False, "reason": "The current structured solid solver constrains the local x-min face; other support faces are not yet implemented.", "solver_grade": "unsupported"}
    direction = load_direction.lower()
    if direction not in {"x", "y", "z"}:
        raise ValueError("load_direction must be x, y, or z")

    params = obj.get("params") or {}
    dims_mm = [float(params[key]) for key in ("x", "y", "z")]
    dims_m = tuple(value / 1000.0 for value in dims_mm)
    counts = mesh_counts or _default_counts(dims_mm)
    counts = tuple(max(1, min(14, int(value))) for value in counts)
    node_limit = (counts[0] + 1) * (counts[1] + 1) * (counts[2] + 1)
    if node_limit > 3500:
        raise ValueError("Requested structured FEA mesh exceeds the 3,500-node interactive safety limit")

    material_id, material = _material(obj)
    E = float(material["youngs_modulus_gpa"]) * 1e9
    nu = float(material["poisson"])
    D = _constitutive(E, nu)
    nodes, elements = _mesh(dims_m, counts)
    ndof = len(nodes) * 3
    rows: list[int] = []
    cols: list[int] = []
    values: list[float] = []
    element_cache: list[tuple[list[int], np.ndarray, np.ndarray]] = []

    for connectivity in elements:
        coords = nodes[np.asarray(connectivity)]
        ke = _element_stiffness(coords, D)
        dofs = np.asarray([3 * node + axis for node in connectivity for axis in range(3)], dtype=int)
        rr = np.repeat(dofs, 24)
        cc = np.tile(dofs, 24)
        rows.extend(rr.tolist())
        cols.extend(cc.tolist())
        values.extend(ke.reshape(-1).tolist())
        element_cache.append((connectivity, coords, dofs))

    K = coo_matrix((values, (rows, cols)), shape=(ndof, ndof)).tocsr()
    F = np.zeros(ndof, dtype=float)
    lx = dims_m[0]
    support_nodes = np.flatnonzero(np.isclose(nodes[:, 0], 0.0, atol=max(lx, 1.0) * 1e-12))
    load_nodes = np.flatnonzero(np.isclose(nodes[:, 0], lx, atol=max(lx, 1.0) * 1e-12))
    component = {"x": 0, "y": 1, "z": 2}[direction]
    signed_force = float(force_n)
    per_node = signed_force / max(len(load_nodes), 1)
    F[3 * load_nodes + component] = per_node
    fixed = np.asarray([3 * node + axis for node in support_nodes for axis in range(3)], dtype=int)
    all_dofs = np.arange(ndof, dtype=int)
    free_mask = np.ones(ndof, dtype=bool)
    free_mask[fixed] = False
    free = all_dofs[free_mask]
    if not len(free):
        raise ValueError("Finite-element model has no free degrees of freedom")

    u = np.zeros(ndof, dtype=float)
    u[free] = spsolve(K[free][:, free], F[free])
    if not np.all(np.isfinite(u)):
        raise ValueError("3D finite-element stiffness solve produced non-finite displacement; model may be singular")

    nodal = u.reshape((-1, 3))
    magnitudes = np.linalg.norm(nodal, axis=1)
    max_displacement_m = float(np.max(magnitudes))
    max_component_m = float(np.max(np.abs(nodal[:, component])))
    max_vm_pa = 0.0
    stress_rows: list[dict[str, Any]] = []
    for element_index, (connectivity, coords, dofs) in enumerate(element_cache):
        B, _ = _b_matrix(coords, 0.0, 0.0, 0.0)
        stress = D @ (B @ u[dofs])
        vm = _von_mises(stress)
        max_vm_pa = max(max_vm_pa, vm)
        stress_rows.append({
            "element": element_index,
            "von_mises_mpa": vm / 1e6,
            "stress_mpa": [float(value) / 1e6 for value in stress],
        })

    residual = K @ u - F
    reaction_vector = np.zeros(3, dtype=float)
    for node in support_nodes:
        reaction_vector += residual[3 * node:3 * node + 3]
    force_vector = np.zeros(3, dtype=float)
    force_vector[component] = signed_force
    equilibrium_error = float(np.linalg.norm(reaction_vector + force_vector) / max(abs(signed_force), 1e-12))
    energy = float(0.5 * u @ (K @ u))
    yield_pa = float(material["yield_mpa"]) * 1e6
    fos = yield_pa / max(max_vm_pa, 1e-12)
    input_signature = {
        "object_id": obj.get("id"),
        "kind": obj.get("kind"),
        "params": obj.get("params"),
        "features": obj.get("features"),
        "material": material_id,
        "force_n": signed_force,
        "support_axis": support_axis,
        "load_direction": direction,
        "mesh_counts": counts,
    }
    return {
        "supported": True,
        "method": "3D linear-elastic structured hexahedral finite element analysis",
        "solver": "ForgeCAD SolidFEA",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "object_id": str(obj.get("id")),
        "material": {"id": material_id, "youngs_modulus_gpa": material["youngs_modulus_gpa"], "poisson": material["poisson"], "yield_mpa": material["yield_mpa"]},
        "load": {"force_n": signed_force, "direction": direction, "distribution": "uniform over local x-max face nodes"},
        "support": {"face": "local x-min", "type": "fixed", "nodes": int(len(support_nodes))},
        "mesh": {"element_type": "C3D8-equivalent trilinear hex", "integration": "2x2x2 Gauss", "counts": list(counts), "nodes": int(len(nodes)), "elements": int(len(elements)), "dof": int(ndof), "free_dof": int(len(free))},
        "max_displacement_mm": max_displacement_m * 1000.0,
        "max_loaded_component_displacement_mm": max_component_m * 1000.0,
        "max_von_mises_stress_mpa": max_vm_pa / 1e6,
        "yield_fos": fos,
        "strain_energy_j": energy,
        "reaction_n": reaction_vector.tolist(),
        "equilibrium_relative_error": equilibrium_error,
        "stress_field": stress_rows,
        "input_sha256": _sha(input_signature),
        "provenance": {
            "geometry_scope": "exact parametric unfeatured box dimensions; local-coordinate analysis",
            "material_source": "ForgeCAD authoritative material table",
            "formulation": "small-strain 3D isotropic linear elasticity",
            "stiffness_matrix": "sparse assembled trilinear-hexahedral displacement formulation",
        },
        "limitations": [
            "Linear elastic and small strain only; no plasticity or geometric nonlinearity.",
            "No contact, bolt preload, joint compliance, residual stress, fracture or fatigue.",
            "Material is homogeneous isotropic; FDM anisotropy is not represented.",
            "Stress is sampled at element centers; local peak stress requires mesh refinement and a general B-rep mesher.",
            "Engineering-iteration solver, not certification evidence; validate critical designs independently and physically.",
        ],
    }


def convergence_study(
    obj: dict[str, Any],
    *,
    force_n: float = 100.0,
    load_direction: str = "z",
    levels: tuple[int, ...] = (4, 6, 8),
    tolerance_fraction: float = 0.05,
) -> dict[str, Any]:
    ok, reason = supported_object(obj)
    if not ok:
        return {"supported": False, "reason": reason, "converged": False}
    dims = [float((obj.get("params") or {})[key]) for key in ("x", "y", "z")]
    rows = []
    for longest in levels:
        counts = _default_counts(dims, target_longest=max(2, int(longest)))
        result = solve_box(obj, force_n=force_n, load_direction=load_direction, mesh_counts=counts)
        rows.append({
            "mesh_counts": list(counts),
            "nodes": result["mesh"]["nodes"],
            "elements": result["mesh"]["elements"],
            "max_displacement_mm": result["max_displacement_mm"],
            "max_von_mises_stress_mpa": result["max_von_mises_stress_mpa"],
            "yield_fos": result["yield_fos"],
            "equilibrium_relative_error": result["equilibrium_relative_error"],
        })
    displacement_change = None
    stress_change = None
    if len(rows) >= 2:
        prev, final = rows[-2], rows[-1]
        displacement_change = abs(final["max_displacement_mm"] - prev["max_displacement_mm"]) / max(abs(final["max_displacement_mm"]), 1e-12)
        stress_change = abs(final["max_von_mises_stress_mpa"] - prev["max_von_mises_stress_mpa"]) / max(abs(final["max_von_mises_stress_mpa"]), 1e-12)
    converged = displacement_change is not None and stress_change is not None and displacement_change <= tolerance_fraction and stress_change <= tolerance_fraction
    return {
        "supported": True,
        "method": "successive structured-mesh refinement",
        "levels": rows,
        "tolerance_fraction": tolerance_fraction,
        "final_displacement_change_fraction": displacement_change,
        "final_stress_change_fraction": stress_change,
        "converged": converged,
        "note": "Mesh convergence reduces discretization uncertainty but does not remove modeling assumptions or validate boundary conditions.",
    }


def _run_simulation(self: Any, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    if not core.PROJECT.get("objects"):
        raise ValueError("Add or import geometry before running an engineering simulation")
    obj = None
    if selected_object_id:
        try:
            obj = core.object_by_id(selected_object_id)
        except KeyError:
            pass
    if obj is None:
        obj = next((row for row in core.PROJECT.get("objects", []) if row.get("kind") != "component"), core.PROJECT["objects"][0])
    from ..v110 import analysis
    force = float(payload.get("force_n", 100.0))
    thermal_w = float(payload.get("heat_w", 10.0))
    reduced = analysis.linear_fea(obj, force_n=force)
    solid = solve_box(obj, force_n=force, load_direction=str(payload.get("load_direction", "z")))
    convergence = convergence_study(obj, force_n=force, load_direction=str(payload.get("load_direction", "z"))) if solid.get("supported") and bool(payload.get("convergence", True)) else None
    result = {
        "object_id": obj["id"],
        "structural": reduced,
        "structural_3d": solid,
        "structural_convergence": convergence,
        "modal": analysis.modal_analysis(obj),
        "thermal": analysis.thermal_analysis(obj, heat_w=thermal_w),
        "manufacturing": analysis.manufacturing_review(obj, str(payload.get("process", "cnc"))),
        "system": self.validation(),
        "analysis_provenance": {
            "primary_structural_result": "structural_3d" if solid.get("supported") else "structural",
            "reduced_order_result_retained": True,
            "physical_verification": False,
        },
    }
    core.record_simulation("engineering_screen_v2", str(obj["id"]), payload, result)
    return result


def install(legacy: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    legacy.PROJECT.run_simulation = MethodType(_run_simulation, legacy.PROJECT)
    _INSTALLED = True
