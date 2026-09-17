from __future__ import annotations

"""Validate the already-accepted ForgeCAD 6.2 runtime after native packaging."""

import argparse
import json
import time
from typing import Any

import httpx


def _request(client: httpx.Client, path: str, token: str) -> dict[str, Any]:
    response = client.get(path, headers={"X-ForgeCAD-Session": token})
    response.raise_for_status()
    return response.json()


def validate(base_url: str, token: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    fidelity: dict[str, Any] | None = None
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        while time.monotonic() < deadline:
            try:
                candidate = _request(client, "/v6/component-fidelity/health", token)
                if candidate.get("version") == "6.2.0":
                    fidelity = candidate
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if fidelity is None:
            raise RuntimeError(f"ForgeCAD 6.2 runtime never became ready at {base_url}")

        assert fidelity["version"] == "6.2.0", fidelity
        assert fidelity["release_complete"] is True, fidelity
        assert fidelity["schema_version"] == 2, fidelity

        revision = _request(client, "/v6/component-fidelity/revision", token)
        assert revision.get("epoch"), revision
        assert isinstance(revision.get("generation"), int), revision

        simulation = _request(client, "/v6/simulation/health", token)
        assert simulation["version"] == "6.1.0", simulation
        assert simulation["assembly"]["ok"] is True, simulation
        assert simulation["domains"]["multibody_kinematics"]["available"] is True, simulation
        assert simulation["domains"]["transient_thermal"]["available"] is True, simulation

        runtime = _request(client, "/v2/runtime", token)
        assert runtime["engine"] == "ready", runtime

        scene_response = client.get("/v2/scene", headers={"X-ForgeCAD-Session": token})
        scene_response.raise_for_status()
        scene = scene_response.json()
        pi = next(row for row in scene["parts"] if row["name"] == "Raspberry Pi 5 8GB")
        groups = pi["mesh"].get("groups") or []
        assert len(groups) >= 4, pi
        assert all("material" in group for group in groups), groups

        return {
            "ok": True,
            "version": fidelity["version"],
            "release_complete": fidelity["release_complete"],
            "component_geometry_schema": fidelity["schema_version"],
            "render_groups": len(groups),
            "simulation_runtime": simulation["version"],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    print(json.dumps(validate(args.url, args.token, args.timeout), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
