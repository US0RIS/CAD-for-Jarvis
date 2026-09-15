from __future__ import annotations

import json
import math
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _add_reactor(client: TestClient, name: str) -> str:
    _ok(client.post("/v2/operations", json={
        "op": "add",
        "args": {
            "name": name,
            "kind": "box",
            "params": {"x": 80.0, "y": 60.0, "z": 50.0},
            "material": "steel_304",
            "semantic": {"role": "chemistry_test_vessel", "tags": ["chemistry", "m6-acceptance"]},
        },
        "reason": f"Create {name}",
    }), f"create {name}")
    return str(next(row for row in core.PROJECT["objects"] if row.get("name") == name)["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        inventory = _ok(client.get("/v6/solvers"), "solver inventory").json()
        cantera = next(row for row in inventory["items"] if row["id"] == "cantera")
        assert cantera["available"] is True, cantera
        assert cantera["release_role"] == "validated_external_solver"
        assert cantera["fallback_policy"] == "fail_closed"
        assert str(cantera.get("module_version") or "")
        calculix = next(row for row in inventory["items"] if row["id"] == "calculix")
        assert calculix["fallback_policy"] == "fail_closed"
        assert isinstance(calculix["available"], bool)

        object_id = _add_reactor(client, "M6 Cantera Vessel")

        unsafe_path = client.post("/v6/chemistry/studies", json={
            "name": "Unsafe mechanism path",
            "object_id": object_id,
            "mechanism": "../gri30.yaml",
            "temperature_k": 300.0,
            "pressure_pa": 101325.0,
            "composition": {"CH4": 1.0, "O2": 2.0, "N2": 7.52},
        })
        assert unsafe_path.status_code == 409, unsafe_path.text
        assert "packaged Cantera YAML" in unsafe_path.text, unsafe_path.text

        created = _ok(client.post("/v6/chemistry/studies", json={
            "name": "Adiabatic methane-air equilibrium",
            "object_id": object_id,
            "solver_id": "cantera",
            "mechanism": "gri30.yaml",
            "mode": "equilibrium",
            "temperature_k": 300.0,
            "pressure_pa": 101325.0,
            "composition": {"CH4": 1.0, "O2": 2.0, "N2": 7.52},
            "equilibrium_basis": "HP",
            "assumptions": ["adiabatic equilibrium screening case", "ideal-gas mechanism assumptions apply"],
        }), "create equilibrium chemistry study").json()["study"]
        assert created["solver_id"] == "cantera"
        assert len(created["definition_sha256"]) == 64
        assert len(created["mechanism_provenance"]["sha256"]) == 64
        assert created["physical_validation"] is False

        equilibrium = _ok(
            client.post(f"/v6/chemistry/studies/{created['id']}/run"),
            "run equilibrium chemistry study",
        ).json()
        run_row = equilibrium["run"]
        initial = run_row["initial_state"]
        final = run_row["final_state"]
        assert run_row["solver"]["solver_grade"] == "external_engineering_analysis"
        assert run_row["solver"]["id"] == "cantera"
        assert run_row["physical_validation"] is False
        assert final["temperature_k"] > initial["temperature_k"] + 500.0, run_row
        assert final["mole_fractions"].get("CH4", 0.0) < initial["mole_fractions"].get("CH4", 0.0) * 0.1, run_row
        assert final["mole_fractions"].get("H2O", 0.0) > 0.01, run_row
        assert len(run_row["mechanism_provenance"]["sha256"]) == 64
        assert equilibrium["graph_evidence"]["status"] == "predicted_external_solver"
        assert equilibrium["graph_evidence"]["subject_node_ids"] == [f"cad:{object_id}"]
        assert equilibrium["graph_evidence"]["stale"] is False

        batch = _ok(client.post("/v6/chemistry/studies", json={
            "name": "Hydrogen oxidation batch kinetics",
            "object_id": object_id,
            "solver_id": "cantera",
            "mechanism": "gri30.yaml",
            "mode": "batch_constant_volume",
            "temperature_k": 1100.0,
            "pressure_pa": 101325.0,
            "composition": {"H2": 2.0, "O2": 1.0, "N2": 3.76},
            "duration_s": 0.002,
            "volume_m3": 0.001,
            "energy_enabled": True,
            "assumptions": ["closed homogeneous zero-dimensional constant-volume batch reactor"],
        }), "create batch chemistry study").json()["study"]
        batch_result = _ok(
            client.post(f"/v6/chemistry/studies/{batch['id']}/run"),
            "run batch chemistry study",
        ).json()["run"]
        assert batch_result["mode"] == "batch_constant_volume"
        assert batch_result["solver"]["method"] == "Cantera IdealGasReactor/ReactorNet"
        assert math.isfinite(float(batch_result["final_state"]["temperature_k"]))
        assert float(batch_result["final_state"]["temperature_k"]) > 0.0
        assert float(batch_result["final_state"]["pressure_pa"]) > 0.0

        unknown_species = _ok(client.post("/v6/chemistry/studies", json={
            "name": "Unknown species fail closed",
            "object_id": object_id,
            "solver_id": "cantera",
            "mechanism": "gri30.yaml",
            "mode": "equilibrium",
            "temperature_k": 300.0,
            "pressure_pa": 101325.0,
            "composition": {"THIS_SPECIES_DOES_NOT_EXIST": 1.0},
        }), "create unknown species study").json()["study"]
        rejected = client.post(f"/v6/chemistry/studies/{unknown_species['id']}/run")
        assert rejected.status_code == 409, rejected.text
        assert "rejected" in rejected.text.lower() or "unknown" in rejected.text.lower(), rejected.text

        stale = _ok(client.post("/v6/chemistry/studies", json={
            "name": "Stale chemistry contract",
            "object_id": object_id,
            "solver_id": "cantera",
            "mechanism": "gri30.yaml",
            "mode": "equilibrium",
            "temperature_k": 300.0,
            "pressure_pa": 101325.0,
            "composition": {"CH4": 1.0, "O2": 2.0, "N2": 7.52},
        }), "create stale chemistry study").json()["study"]
        _ok(client.post("/v2/operations", json={
            "op": "update",
            "args": {"id": object_id, "params": {"x": 82.0, "y": 60.0, "z": 50.0}},
            "reason": "Change vessel after chemistry contract was frozen",
        }), "mutate chemistry vessel")
        stale_run = client.post(f"/v6/chemistry/studies/{stale['id']}/run")
        assert stale_run.status_code == 409, stale_run.text
        assert "stale" in stale_run.text.lower(), stale_run.text

        studies = _ok(client.get("/v6/chemistry/studies"), "list chemistry studies").json()
        runs = _ok(client.get("/v6/chemistry/runs"), "list chemistry runs").json()
        assert studies["count"] >= 4
        assert runs["count"] == 2, runs

        return {
            "ok": True,
            "milestone": "external_solver_chemistry",
            "cantera_version": cantera["module_version"],
            "mechanism_sha256": created["mechanism_provenance"]["sha256"],
            "equilibrium_final_temperature_k": final["temperature_k"],
            "batch_final_temperature_k": batch_result["final_state"]["temperature_k"],
            "graph_evidence_id": equilibrium["graph_evidence"]["id"],
            "fail_closed_unknown_species": True,
            "fail_closed_stale_contract": True,
            "physical_validation_claimed": False,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
