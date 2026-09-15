from __future__ import annotations

"""Validate the capabilities that must survive ForgeCAD 6.0.1 native packaging."""

import argparse
import json
import time
from typing import Any

import httpx


def _request(client: httpx.Client, method: str, path: str, *, token: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"X-ForgeCAD-Session": token} if token else {}
    response = client.request(method, path, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


def validate(base_url: str, token: str, expected_release_complete: bool, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    health: dict[str, Any] | None = None
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=15.0) as client:
        while time.monotonic() < deadline:
            try:
                candidate = _request(client, "GET", "/v6/health")
                if candidate.get("ok"):
                    health = candidate
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if health is None:
            raise RuntimeError(f"ForgeCAD 6.0.1 health never became ready at {base_url}")

        assert health["api_version"] == "6.0", health
        assert health["engine_version"] == "6.0.1", health
        assert health["milestone_version"] == "6.0.1", health
        assert health["release_complete"] is expected_release_complete, health
        assert health["validation_truth"]["real_hardware_validation_complete"] is False, health
        assert health["validation_truth"]["release_is_not_certification"] is True, health

        runtime = _request(client, "GET", "/v2/runtime", token=token)
        assert runtime["engine"] == "ready", runtime
        assert runtime["scene"] == "ready", runtime
        assert runtime["api_version"] == "2", runtime
        assert runtime["ollama"] in {"ready", "offline", "failed"}, runtime
        assert str(runtime.get("configured_model") or ""), runtime
        # Native CI does not require a local Ollama daemon. The release requirement is
        # that the packaged engine can execute its 6.0.1 discovery/status contract
        # cleanly; endpoint fallback/model-alias behavior is covered by v601_selftest.
        if runtime["ollama"] == "ready":
            assert str(runtime.get("resolved_model") or ""), runtime

        cantera = _request(client, "GET", "/v6/solvers/cantera", token=token)
        assert cantera["available"] is True, cantera
        assert cantera["release_role"] == "validated_external_solver", cantera
        assert cantera["fallback_policy"] == "fail_closed", cantera
        assert str(cantera.get("module_version") or ""), cantera

        part = _request(
            client,
            "POST",
            "/v3.1/cad/parts",
            token=token,
            payload={
                "name": "Native Package Chemistry Cell",
                "kind": "box",
                "params": {"x": 40.0, "y": 30.0, "z": 20.0},
                "material": "steel_304",
                "semantic": {"role": "native_release_runtime_smoke"},
            },
        )
        object_id = str(next(row["id"] for row in part["project"]["objects"] if row.get("name") == "Native Package Chemistry Cell"))

        study = _request(
            client,
            "POST",
            "/v6/chemistry/studies",
            token=token,
            payload={
                "name": "Native packaged Cantera mechanism smoke",
                "object_id": object_id,
                "solver_id": "cantera",
                "mechanism": "gri30.yaml",
                "mode": "equilibrium",
                "temperature_k": 300.0,
                "pressure_pa": 101325.0,
                "composition": {"CH4": 1.0, "O2": 2.0, "N2": 7.52},
                "equilibrium_basis": "HP",
                "assumptions": ["native release packaging smoke only"],
            },
        )["study"]
        mechanism_sha = str(study["mechanism_provenance"]["sha256"] or "")
        assert len(mechanism_sha) == 64, study

        result = _request(client, "POST", f"/v6/chemistry/studies/{study['id']}/run", token=token)
        run = result["run"]
        assert run["solver"]["id"] == "cantera", run
        assert run["solver"]["solver_grade"] == "external_engineering_analysis", run
        assert run["physical_validation"] is False, run
        assert str(run["mechanism_provenance"]["sha256"]) == mechanism_sha, run
        assert float(run["final_state"]["temperature_k"]) > 800.0, run

        return {
            "ok": True,
            "api_version": health["api_version"],
            "engine_version": health["engine_version"],
            "release_complete": health["release_complete"],
            "ollama_state": runtime["ollama"],
            "configured_model": runtime["configured_model"],
            "resolved_model": runtime.get("resolved_model"),
            "cantera_version": cantera["module_version"],
            "mechanism_sha256": mechanism_sha,
            "chemistry_solver_grade": run["solver"]["solver_grade"],
            "real_hardware_validation_claimed": False,
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
