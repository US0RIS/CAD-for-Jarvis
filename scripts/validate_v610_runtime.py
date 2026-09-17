from __future__ import annotations

"""Validate the capabilities that must survive ForgeCAD 6.1.0 native packaging."""

import argparse
import json
import time
from typing import Any

import httpx


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, path, headers={"X-ForgeCAD-Session": token}, json=payload)
    response.raise_for_status()
    return response.json()


def validate(base_url: str, token: str, expected_release_complete: bool, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    health: dict[str, Any] | None = None
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        while time.monotonic() < deadline:
            try:
                candidate = _request(client, "GET", "/v6/simulation/health", token=token)
                if candidate.get("version") == "6.1.0":
                    health = candidate
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if health is None:
            raise RuntimeError(f"ForgeCAD 6.1.0 simulation runtime never became ready at {base_url}")

        assert health["version"] == "6.1.0", health
        assert health["release_complete"] is expected_release_complete, health
        assert health["assembly"]["ok"] is True, health
        assert health["domains"]["multibody_kinematics"]["available"] is True, health
        assert health["domains"]["transient_thermal"]["available"] is True, health
        assert health["domains"]["solid_fea"]["available"] is True, health
        assert health["domains"]["integral_aerodynamics"]["is_cfd"] is False, health

        runtime = _request(client, "GET", "/v2/runtime", token=token)
        assert runtime["engine"] == "ready", runtime

        cantera = _request(client, "GET", "/v6/solvers/cantera", token=token)
        assert cantera["available"] is True, cantera
        assert cantera["release_role"] == "validated_external_solver", cantera
        assert cantera["fallback_policy"] == "fail_closed", cantera

        reset = _request(
            client,
            "POST",
            "/v2/operations",
            token=token,
            payload={"op": "new_project", "args": {}, "reason": "ForgeCAD 6.1 native runtime validation"},
        )
        assert reset.get("project"), reset

        added = _request(
            client,
            "POST",
            "/v2/operations",
            token=token,
            payload={
                "op": "add",
                "args": {
                    "name": "Native 6.1 Thermal Coupon",
                    "kind": "box",
                    "params": {"x": 20.0, "y": 12.0, "z": 8.0},
                    "material": "aluminum_6061_t6",
                    "transform": {
                        "position": [0.0, 0.0, 0.0],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                },
                "reason": "Create native 6.1 thermal validation solid",
            },
        )
        object_id = str(next(row["id"] for row in added["project"]["parts"] if row.get("name") == "Native 6.1 Thermal Coupon"))

        field = _request(
            client,
            "POST",
            "/v6/simulation/thermal/field",
            token=token,
            payload={
                "object_id": object_id,
                "duration_s": 0.05,
                "timestep_s": 0.01,
                "initial_temperature_c": 25.0,
                "heat_w": 5.0,
                "convection_h_w_m2k": 10.0,
                "ambient_temperature_c": 25.0,
                "emissivity": 0.8,
                "grid": [4, 4, 4],
                "max_samples": 20,
            },
        )
        assert field["supported"] is True, field
        assert field["solver"] == "ForgeCAD ThermalField3D", field
        assert field["grid"] == [4, 4, 4], field
        assert float(field["temperature"]["maximum_c"]) > 25.0, field
        assert float(field["actual_timestep_s"]) <= float(field["stability_limit_s"]) + 1e-12, field

        runs = _request(client, "GET", "/v6/simulation/runs", token=token)
        assert runs["count"] >= 1, runs
        assert any(str(row.get("kind")) == "thermal_field_3d" for row in runs["items"]), runs

        return {
            "ok": True,
            "version": health["version"],
            "release_complete": health["release_complete"],
            "cantera_version": cantera.get("module_version"),
            "thermal_field_solver": field["solver"],
            "thermal_field_grid": field["grid"],
            "simulation_runs": runs["count"],
            "physical_verification_claimed": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--expect-release-complete", choices=("true", "false"), required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    result = validate(
        args.url,
        args.token,
        expected_release_complete=args.expect_release_complete == "true",
        timeout_s=args.timeout,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
