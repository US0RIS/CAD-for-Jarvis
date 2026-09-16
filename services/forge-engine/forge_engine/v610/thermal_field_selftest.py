from __future__ import annotations

import math

from . import thermal_field


def _project() -> dict:
    return {
        "objects": [{
            "id": "thermal-box",
            "name": "ABS electronics enclosure coupon",
            "kind": "box",
            "params": {"x": 20.0, "y": 12.0, "z": 8.0},
            "material": "abs",
            "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "features": [],
            "visible": True,
        }],
        "joints": [],
        "connections": [],
        "loads": [],
        "constraints": [],
        "requirements": [],
        "bom": [],
        "settings": {},
        "simulations": [],
    }


def run() -> dict:
    project = _project()
    result = thermal_field.solve_box_thermal_field(
        project,
        "thermal-box",
        duration_s=5.0,
        timestep_s=0.1,
        initial_temperature_c=25.0,
        heat_w=20.0,
        convection_h_w_m2k=10.0,
        ambient_temperature_c=25.0,
        emissivity=0.8,
        grid=[8, 6, 4],
        max_samples=30,
    )
    assert result["supported"] is True
    assert result["solver"] == "ForgeCAD ThermalField3D"
    assert result["grid"] == [8, 6, 4]
    assert result["integration_steps"] >= 50
    assert result["actual_timestep_s"] <= 0.1 + 1e-12
    assert result["actual_timestep_s"] <= result["stability_limit_s"] + 1e-12
    assert result["temperature"]["maximum_c"] > 25.0
    assert result["temperature"]["center_c"] >= result["temperature"]["mean_c"]
    assert result["temperature"]["maximum_gradient_k_m"] > 0.0
    assert len(result["final_temperature_field_c"]) == 8
    assert len(result["final_temperature_field_c"][0]) == 6
    assert len(result["final_temperature_field_c"][0][0]) == 4
    generated = float(result["energy_balance"]["generated_heat_j"])
    residual = abs(float(result["energy_balance"]["residual_j"]))
    assert generated > 0.0 and math.isfinite(residual)
    assert residual / generated < 1e-8

    unsupported = _project()
    unsupported["objects"][0]["kind"] = "sphere"
    unsupported["objects"][0]["params"] = {"radius": 10.0}
    rejected = thermal_field.solve_box_thermal_field(
        unsupported,
        "thermal-box",
        duration_s=1.0,
        timestep_s=0.1,
        initial_temperature_c=25.0,
        heat_w=1.0,
        convection_h_w_m2k=10.0,
        ambient_temperature_c=25.0,
    )
    assert rejected["supported"] is False
    assert "box" in str(rejected["reason"]).lower()

    return {
        "ok": True,
        "checks": {
            "spatial_temperature_field": True,
            "explicit_stability_control": True,
            "energy_conservation": True,
            "unsupported_geometry_fails_closed": True,
        },
    }


if __name__ == "__main__":
    print(run())
