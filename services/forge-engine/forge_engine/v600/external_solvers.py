from __future__ import annotations

"""External engineering-solver capability registry for ForgeCAD 6.0.

The registry reports what is actually available in the running Forge Engine. Missing
solvers are never replaced with fabricated results or a silent lower-fidelity fallback.
Adapters may use a Python library or an executable, but each capability must expose its
real implementation/version and the domains it can solve.
"""

from copy import deepcopy
import importlib
import importlib.util
import shutil
from typing import Any


_SOLVERS: dict[str, dict[str, Any]] = {
    "cantera": {
        "name": "Cantera",
        "kind": "python_library",
        "module": "cantera",
        "domains": ["thermochemistry", "chemical_equilibrium", "reaction_kinetics", "zero_dimensional_reactors"],
        "release_role": "validated_external_solver",
        "limitations": [
            "No multidimensional CFD or turbulent reacting-flow solution is implied.",
            "Results remain conditional on the selected mechanism, phase model, initial state and reactor assumptions.",
        ],
    },
    "calculix": {
        "name": "CalculiX CrunchiX",
        "kind": "executable",
        "executables": ["ccx", "calculix-ccx"],
        "domains": ["structural_fea"],
        "release_role": "optional_external_solver",
        "limitations": [
            "ForgeCAD 6.0 does not claim a general B-rep-to-CalculiX production meshing path unless the corresponding adapter reports supported input geometry.",
        ],
    },
    "openfoam": {
        "name": "OpenFOAM",
        "kind": "executable",
        "executables": ["foamRun", "simpleFoam", "reactingFoam"],
        "domains": ["cfd", "reacting_flow", "heat_transfer"],
        "release_role": "optional_external_solver",
        "limitations": [
            "Availability does not imply that a given ForgeCAD model has a validated OpenFOAM case generator.",
        ],
    },
    "gmsh": {
        "name": "Gmsh",
        "kind": "python_or_executable",
        "module": "gmsh",
        "executables": ["gmsh"],
        "domains": ["surface_meshing", "volume_meshing"],
        "release_role": "optional_external_mesher",
        "limitations": [
            "Gmsh is a mesher, not by itself a structural/thermal/CFD solver.",
        ],
    },
}


def _module_status(module_name: str) -> tuple[bool, str | None]:
    if importlib.util.find_spec(module_name) is None:
        return False, None
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False, None
    version = getattr(module, "__version__", None)
    return True, str(version) if version is not None else "available"


def _executable_status(names: list[str]) -> tuple[bool, str | None]:
    for name in names:
        path = shutil.which(name)
        if path:
            return True, path
    return False, None


def solver_status(solver_id: str) -> dict[str, Any]:
    if solver_id not in _SOLVERS:
        raise KeyError(solver_id)
    spec = deepcopy(_SOLVERS[solver_id])
    kind = str(spec["kind"])
    module_available = False
    module_version = None
    executable_available = False
    executable_path = None
    if spec.get("module"):
        module_available, module_version = _module_status(str(spec["module"]))
    if spec.get("executables"):
        executable_available, executable_path = _executable_status([str(x) for x in spec["executables"]])
    if kind == "python_library":
        available = module_available
    elif kind == "executable":
        available = executable_available
    else:
        available = module_available or executable_available
    return {
        "id": solver_id,
        **spec,
        "available": bool(available),
        "module_available": module_available,
        "module_version": module_version,
        "executable_available": executable_available,
        "executable_path": executable_path,
        "fallback_policy": "fail_closed",
    }


def solver_inventory() -> dict[str, Any]:
    items = [solver_status(solver_id) for solver_id in sorted(_SOLVERS)]
    return {
        "items": items,
        "count": len(items),
        "available_count": sum(bool(item["available"]) for item in items),
        "validated_release_solver_ids": [
            item["id"]
            for item in items
            if item["release_role"] == "validated_external_solver" and item["available"]
        ],
        "policy": "missing external solvers fail closed; availability is not proof that a model/case is supported",
    }


def require_solver(solver_id: str) -> dict[str, Any]:
    status = solver_status(solver_id)
    if not status["available"]:
        raise RuntimeError(f"External solver {solver_id!r} is not available in this Forge Engine runtime")
    return status
