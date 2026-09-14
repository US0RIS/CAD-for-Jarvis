from __future__ import annotations

"""Acceptance test for ForgeCAD 6.0 milestone 1.

The fixture is a real electromechanical product class rather than a geometry toy:
a networked solenoid characterization/actuation module built from authoritative
purchased components plus custom fabricated structure. It forces CAD, component
identity, interface-constrained assembly, electrical topology, software,
requirements, structural screening, DFM, fabrication packaging, and the
Engineering Graph to agree on the same canonical design.
"""

import io
import json
import os
import zipfile

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core
from ..v200 import structural_fea


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _active_project(client: TestClient) -> dict:
    # /v2/project is intentionally the compact desktop projection, not the raw
    # canonical project. Exercise that public contract, then inspect a detached copy
    # of the canonical store when the acceptance test needs engineering internals.
    projected = _ok(client.get("/v2/project"), "project snapshot").json()
    assert projected["active_branch"] == core.ACTIVE_DESIGN, projected
    return json.loads(json.dumps(core.PROJECT))


def _object_named(project: dict, name: str) -> dict:
    return next(row for row in project["objects"] if row.get("name") == name)


def _add_component(client: TestClient, component_id: str, expected_name_fragment: str) -> str:
    payload = _ok(client.post(f"/v2/components/{component_id}/add"), f"add {component_id}").json()
    instance_id = str(payload["component"]["instance_id"])
    obj = next(row for row in _active_project(client)["objects"] if str(row.get("id")) == instance_id)
    assert expected_name_fragment.lower() in str(obj.get("name") or "").lower(), obj
    assert obj.get("component_ref") == component_id, obj
    assert int((obj.get("component_snapshot") or {}).get("trust_score", 0)) >= 85, obj
    return instance_id


def _connect(client: TestClient, a_id: str, a_interface: str, b_id: str, b_interface: str, net_name: str) -> None:
    _ok(
        client.post(
            "/v2/operations",
            json={
                "op": "connect_interfaces",
                "args": {
                    "a_id": a_id,
                    "a_interface": a_interface,
                    "b_id": b_id,
                    "b_interface": b_interface,
                    "kind": "electrical",
                    "net_name": net_name,
                },
                "reason": f"6.0 milestone wiring {net_name}",
            },
        ),
        f"connect {net_name}",
    )


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        _ok(client.post("/v3.1/graph/sync"), "initial graph sync")
        v31 = _ok(client.get("/v3.1/health"), "3.1 compatibility health").json()
        assert v31["engineering_graph"]["ready"] is True, v31

        deck_name = "V6 Networked Actuator Deck"
        _ok(
            client.post(
                "/v2/operations",
                json={
                    "op": "add",
                    "args": {
                        "name": deck_name,
                        "kind": "box",
                        "params": {"x": 220.0, "y": 160.0, "z": 4.0},
                        "material": "petg",
                        "semantic": {
                            "role": "fabricated_chassis",
                            "manufacturing_process": "fdm",
                            "tags": ["v6-vertical-slice", "editable", "manufactured"],
                        },
                        "interfaces": [
                            {"id": "pi_mount", "kind": "mount_pattern", "position_mm": [-55.0, 35.0, 2.0], "axis": [0.0, 0.0, 1.0], "gender": "neutral", "required": True, "mate": ["mount_pattern"], "metadata": {"max_connections": 1}},
                            {"id": "psu_mount", "kind": "mount_face", "position_mm": [45.0, 25.0, 2.0], "axis": [0.0, 0.0, 1.0], "gender": "neutral", "required": True, "mate": ["mount_face"], "metadata": {"max_connections": 1}},
                            {"id": "regulator_mount", "kind": "mount_pattern", "position_mm": [-35.0, -55.0, 2.0], "axis": [0.0, 0.0, 1.0], "gender": "neutral", "required": True, "mate": ["mount_pattern"], "metadata": {"max_connections": 1}},
                            {"id": "reaction_rail_mount", "kind": "mount_face", "position_mm": [60.0, -55.0, 2.0], "axis": [0.0, 0.0, 1.0], "gender": "neutral", "required": True, "mate": ["mount_face"], "metadata": {"max_connections": 1}},
                        ],
                    },
                    "reason": "Create editable manufactured structure for 6.0 milestone",
                },
            ),
            "create actuator deck",
        )
        deck_id = str(_object_named(_active_project(client), deck_name)["id"])

        _ok(
            client.post(
                f"/v3.1/cad/objects/{deck_id}/features",
                json={"type": "slot", "name": "Harness pass-through", "parameters": {"x": 0.0, "y": 0.0, "length": 24.0, "width": 8.0, "depth": 5.0}},
            ),
            "add harness slot",
        )

        rail_name = "Actuator Reaction Rail"
        _ok(
            client.post(
                "/v2/operations",
                json={
                    "op": "add",
                    "args": {
                        "name": rail_name,
                        "kind": "box",
                        "params": {"x": 80.0, "y": 20.0, "z": 12.0},
                        "material": "aluminum_6061_t6",
                        "semantic": {
                            "role": "load_bearing_actuator_support",
                            "manufacturing_process": "cnc",
                            "tags": ["v6-vertical-slice", "structural", "editable", "manufactured"],
                        },
                        "interfaces": [
                            {"id": "deck_mount", "kind": "mount_face", "position_mm": [0.0, 0.0, -6.0], "axis": [0.0, 0.0, -1.0], "gender": "neutral", "required": True, "mate": ["mount_face"], "metadata": {"max_connections": 1}},
                            {"id": "solenoid_mount", "kind": "mount_face", "position_mm": [0.0, 0.0, 6.0], "axis": [0.0, 0.0, 1.0], "gender": "neutral", "required": True, "mate": ["mount_face"], "metadata": {"max_connections": 1}},
                        ],
                    },
                    "reason": "Create exact load-bearing custom structure for 6.0 milestone",
                },
            ),
            "create reaction rail",
        )
        rail_id = str(_object_named(_active_project(client), rail_name)["id"])

        pi_id = _add_component(client, "compute.raspberry_pi_5_8gb", "Raspberry Pi")
        psu_id = _add_component(client, "power.meanwell.lrs_75_12", "LRS-75-12")
        regulator_id = _add_component(client, "power.pololu.d24v50f5", "D24V50F5")
        mosfet_id = _add_component(client, "driver.adafruit.mosfet_5648", "MOSFET")
        solenoid_id = _add_component(client, "solenoid.adafruit.412", "Solenoid")

        mates = [
            (pi_id, "mount", deck_id, "pi_mount"),
            (psu_id, "chassis", deck_id, "psu_mount"),
            (regulator_id, "mount", deck_id, "regulator_mount"),
            (rail_id, "deck_mount", deck_id, "reaction_rail_mount"),
            (solenoid_id, "mount", rail_id, "solenoid_mount"),
        ]
        for source_id, source_interface, target_id, target_interface in mates:
            solved = _ok(
                client.post(
                    "/v6/assembly/mates/apply",
                    json={"source_id": source_id, "target_id": target_id, "source_interface": source_interface, "target_interface": target_interface, "mate_type": "fixed"},
                ),
                f"mate {source_interface} to {target_interface}",
            ).json()
            assert solved["residual"]["position_error_mm"] < 1e-6, solved
            assert solved["residual"]["axis_error_deg"] < 1e-6, solved

        constraint_validation = _ok(client.get("/v6/assembly/constraints"), "validate mate constraints").json()
        assert constraint_validation["ok"] is True, constraint_validation
        assert constraint_validation["constrained_mechanical_connections"] >= 5, constraint_validation

        # A fixed physical interface is exclusive by default. Prove the solver rejects
        # a second use rather than silently moving a component and corrupting assembly truth.
        connection_count = len(core.PROJECT.get("connections", []))
        occupied = client.post(
            "/v6/assembly/mates/apply",
            json={"source_id": pi_id, "target_id": deck_id, "source_interface": "mount", "target_interface": "regulator_mount", "mate_type": "fixed"},
        )
        assert occupied.status_code == 409, occupied.text
        assert "occupied" in occupied.text.lower(), occupied.text
        assert len(core.PROJECT.get("connections", [])) == connection_count

        _connect(client, psu_id, "dc_out", regulator_id, "vin", "+12V")
        _connect(client, regulator_id, "vout", pi_id, "usb_c_power", "+5V")
        _connect(client, psu_id, "dc_out", mosfet_id, "power_in", "+12V_ACTUATOR")
        _connect(client, mosfet_id, "load_out", solenoid_id, "coil", "SOLENOID_SWITCHED")
        _connect(client, pi_id, "gpio40", mosfet_id, "signal", "SOLENOID_CONTROL")

        code = """from time import monotonic, sleep\n\nMAX_ON_SECONDS = 0.25\n\ndef pulse(set_output):\n    started = monotonic()\n    set_output(True)\n    while monotonic() - started < MAX_ON_SECONDS:\n        sleep(0.005)\n    set_output(False)\n"""
        _ok(
            client.post(
                "/v2/operations",
                json={"op": "code_write", "args": {"id": pi_id, "path": "actuator.py", "content": code}, "reason": "Bind actuator control software to the physical design"},
            ),
            "write device software",
        )

        req = _ok(
            client.post(
                "/v3.1/requirements",
                json={"name": "Portable bench mass", "metric": "mass_kg", "op": "<=", "target": 2.0, "unit": "kg", "criticality": "important", "scope_object_ids": [deck_id, rail_id, pi_id, psu_id, regulator_id, mosfet_id, solenoid_id]},
            ),
            "create mass requirement",
        ).json()
        verified = _ok(client.post("/v3.1/requirements/verify"), "verify product requirements").json()
        mass_row = next(row for row in verified["items"] if row["requirement"]["id"] == req["id"])
        assert mass_row["status"] == "pass", mass_row

        # The existing solid solver is truthful about its validated geometry domain:
        # featured B-reps need a general tetrahedral mesher and must fail closed today.
        deck_obj = core.object_by_id(deck_id)
        unsupported_featured = structural_fea.solve_box(deck_obj, force_n=-1.0, load_direction="z", mesh_counts=(6, 4, 2))
        assert unsupported_featured["supported"] is False, unsupported_featured
        assert unsupported_featured["solver_grade"] == "unsupported", unsupported_featured

        # The load-bearing reaction rail is exact unfeatured solid geometry, so the
        # existing 3D continuum solver can run without pretending to support the slot.
        rail_obj = core.object_by_id(rail_id)
        fea = structural_fea.solve_box(rail_obj, force_n=-10.0, load_direction="z", mesh_counts=(6, 2, 2))
        assert fea["supported"] is True, fea
        assert fea["solver_grade"] == "engineering_iteration", fea
        assert fea["max_von_mises_stress_mpa"] > 0.0, fea
        assert fea["yield_fos"] > 1.0, fea

        dfm = _ok(client.get(f"/v3.1/manufacturing/screen/{deck_id}", params={"process": "fdm"}), "screen fabricated deck").json()
        assert dfm["ok"] is True, dfm
        assert len(dfm["geometry_fingerprint"]) == 64, dfm

        _ok(client.post("/v3.1/graph/sync"), "final graph sync")
        graph = _ok(client.get("/v3.1/graph"), "integrated engineering graph").json()
        ids = {row["id"] for row in graph["nodes"]}
        assert f"cad:{deck_id}" in ids and f"cad:{rail_id}" in ids and f"cad:{pi_id}" in ids, ids
        assert f"software:{pi_id}" in ids, ids
        assert any(row["kind"] == "joint" and row["properties"].get("solver") == "forgecad.v600.interface_mate" for row in graph["nodes"]), graph
        assert any(row["kind"] == "connected_to" for row in graph["edges"]), graph

        archive = _ok(
            client.post(
                "/v3.1/fabrication/archive",
                json={"name": "V6 Networked Actuator Milestone", "processes": {deck_id: "fdm", rail_id: "cnc"}, "include_step": True, "include_stl": True},
            ),
            "create integrated fabrication archive",
        )
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["engineering_graph_revision"], manifest
            assert any(row.get("component_ref") == "compute.raspberry_pi_5_8gb" for row in manifest["bom"]), manifest
            assert any(item.get("object_id") == pi_id for item in manifest["software"]), manifest
            step_files = [name for name in zf.namelist() if name.startswith("parts/") and name.endswith(".step")]
            assert len(step_files) >= 2, zf.namelist()

        v6 = _ok(client.get("/v6/health"), "v6 milestone health").json()
        assert v6["release_complete"] is False, v6
        assert v6["assembly_constraints"]["ok"] is True, v6

        return {
            "milestone": "interface_constrained_electromechanical_assembly",
            "custom_fabricated_parts": 2,
            "purchased_components": 5,
            "mechanical_mates": len(mates),
            "exclusive_interface_rejection": True,
            "electrical_connections": 5,
            "software_bound": True,
            "requirement_verified": True,
            "featured_geometry_fea_fail_closed": True,
            "structural_solver_grade": fea["solver_grade"],
            "dfm_passed": True,
            "fabrication_archive_verified": True,
            "v310_regression_surface_reachable": True,
        }


def main() -> None:
    result = run()
    print("ForgeCAD 6.0 milestone 1 self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
