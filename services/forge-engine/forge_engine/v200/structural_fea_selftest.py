from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 3D solid finite-element analysis."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import structural_fea


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Solid FEA beam",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 20.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "structural_test", "tags": ["fabricated", "fea-selftest"]},
        },
        actor="human",
        reason="Create exact rectangular FEA fixture",
    )
    obj = core.PROJECT["objects"][-1]
    result = structural_fea.solve_box(obj, force_n=-100.0, load_direction="z", mesh_counts=(6, 2, 2))
    assert result["supported"] is True
    assert result["solver"] == "ForgeCAD SolidFEA"
    assert result["solver_grade"] == "engineering_iteration"
    assert result["mesh"]["elements"] == 24
    assert result["mesh"]["nodes"] == 63
    assert result["max_displacement_mm"] > 0.0
    assert result["max_von_mises_stress_mpa"] > 0.0
    assert result["yield_fos"] > 1.0
    assert result["strain_energy_j"] > 0.0
    assert result["equilibrium_relative_error"] < 1e-7
    assert len(result["input_sha256"]) == 64
    assert abs(float(result["reaction_n"][2]) - 100.0) < 1e-5

    # Compare order-of-magnitude behavior against the closed-form beam screen without
    # pretending the two models are equivalent. The 3D hex model includes shear and
    # Poisson effects while the analytical result assumes Euler-Bernoulli bending.
    E_mpa = 68.9e3
    I_mm4 = 20.0 * 20.0**3 / 12.0
    analytical_mm = 100.0 * 100.0**3 / (3.0 * E_mpa * I_mm4)
    ratio = float(result["max_loaded_component_displacement_mm"]) / analytical_mm
    assert 0.35 < ratio < 2.5, (ratio, result["max_loaded_component_displacement_mm"], analytical_mm)

    convergence = structural_fea.convergence_study(
        obj,
        force_n=-100.0,
        load_direction="z",
        levels=(3, 5, 7),
        tolerance_fraction=0.20,
    )
    assert convergence["supported"] is True
    assert len(convergence["levels"]) == 3
    assert convergence["final_displacement_change_fraction"] is not None
    assert convergence["final_stress_change_fraction"] is not None
    assert all(row["equilibrium_relative_error"] < 1e-7 for row in convergence["levels"])

    unsupported = dict(obj)
    unsupported["kind"] = "cylinder"
    rejected = structural_fea.solve_box(unsupported)
    assert rejected["supported"] is False
    assert rejected["solver_grade"] == "unsupported"

    # EngineeringProject.run_simulation is upgraded by v2 to preserve the old screen
    # while adding the real solid result and explicit provenance.
    simulation = PROJECT.run_simulation(str(obj["id"]), {"force_n": -100.0, "load_direction": "z", "convergence": False})
    assert simulation["structural_3d"]["supported"] is True
    assert simulation["analysis_provenance"]["primary_structural_result"] == "structural_3d"
    assert simulation["analysis_provenance"]["physical_verification"] is False

    return {
        "elements": result["mesh"]["elements"],
        "nodes": result["mesh"]["nodes"],
        "max_displacement_mm": round(float(result["max_displacement_mm"]), 6),
        "max_von_mises_stress_mpa": round(float(result["max_von_mises_stress_mpa"]), 6),
        "yield_fos": round(float(result["yield_fos"]), 4),
        "equilibrium_relative_error": result["equilibrium_relative_error"],
        "analytical_displacement_ratio": round(ratio, 4),
        "converged_at_20pct": bool(convergence["converged"]),
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 3D solid FEA self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
