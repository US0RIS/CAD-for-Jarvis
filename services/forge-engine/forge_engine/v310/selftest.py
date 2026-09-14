from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core
from .. import main_v31


def _assert_ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def run() -> dict[str, object]:
    # Establish a deterministic blank canonical workspace before app startup.
    PROJECT.new_project()
    with TestClient(app) as client:
        _assert_ok(client.post("/v3.1/graph/sync"), "initial graph sync")
        health = _assert_ok(client.get("/v3.1/health"), "v3.1 health").json()
        assert health["api_version"] == "3.1", health
        assert health["engine_version"] == "3.1.0", health
        assert health["engineering_graph"]["ready"] is True, health
        assert health["engineering_graph"]["dirty_node_count"] == 0, health

        # Direct feature-history CAD editing with stable IDs.
        part_response = _assert_ok(
            client.post(
                "/v3.1/cad/parts",
                json={
                    "name": "3.1 Feature Test Block",
                    "kind": "box",
                    "params": {"x": 40.0, "y": 30.0, "z": 8.0},
                    "material": "aluminum_6061_t6",
                    "semantic": {"role": "test_fixture", "manufacturing_process": "cnc"},
                },
            ),
            "create CAD part",
        ).json()
        raw_part = next(row for row in part_response["project"]["objects"] if row["name"] == "3.1 Feature Test Block")
        part_id = raw_part["id"]
        feature = _assert_ok(
            client.post(
                f"/v3.1/cad/objects/{part_id}/features",
                json={"type": "slot", "name": "Cable Slot", "parameters": {"length": 18.0, "width": 5.0, "depth": 8.0}},
            ),
            "add slot feature",
        ).json()["feature"]
        assert feature["id"].startswith("feat-"), feature
        feature_id = feature["id"]
        _assert_ok(client.patch(f"/v3.1/cad/objects/{part_id}/features/{feature_id}", json={"patch": {"width": 6.0}}), "edit feature")
        suppressed = _assert_ok(client.post(f"/v3.1/cad/objects/{part_id}/features/{feature_id}/suppress", json={"suppressed": True}), "suppress feature").json()
        assert suppressed["feature"]["enabled"] is False, suppressed
        _assert_ok(client.post(f"/v3.1/cad/objects/{part_id}/features/{feature_id}/suppress", json={"suppressed": False}), "unsuppress feature")
        duplicated = _assert_ok(client.post(f"/v3.1/cad/objects/{part_id}/features/{feature_id}/duplicate"), "duplicate feature").json()
        assert duplicated["feature"]["id"] != feature_id, duplicated
        listed = _assert_ok(client.get(f"/v3.1/cad/objects/{part_id}/features"), "list features").json()
        assert listed["count"] == 2, listed

        # Loft and pattern geometry contracts execute through the same core.
        loft = _assert_ok(
            client.post(
                "/v3.1/cad/parts",
                json={
                    "name": "Lofted Housing",
                    "kind": "loft",
                    "params": {"sections": [{"z": 0, "type": "rectangle", "width": 20, "height": 16}, {"z": 25, "type": "rectangle", "width": 12, "height": 10}]},
                    "material": "abs",
                },
            ),
            "create loft",
        ).json()
        loft_obj = next(row for row in loft["project"]["objects"] if row["name"] == "Lofted Housing")
        metrics = core.object_metrics(core.object_by_id(loft_obj["id"]))
        assert metrics["volume_mm3"] > 0, metrics

        # Product Lab is a first-class profile on the same project/graph.
        product_lab = _assert_ok(
            client.put(
                "/v3.1/product-profile",
                json={
                    "mode": "product_lab",
                    "name": "Compact wearable prototype",
                    "envelope_mm": [120, 90, 60],
                    "max_mass_g": 2000,
                    "human_contact": True,
                    "wearable": True,
                    "stored_energy_limit_j": 100,
                    "max_surface_temperature_c": 45,
                    "preferred_processes": ["fdm", "cnc"],
                },
            ),
            "set Product Lab profile",
        ).json()
        assert product_lab["profile"]["mode"] == "product_lab", product_lab

        # Requirements are canonical objects backed by provenance-bearing evidence.
        req = _assert_ok(
            client.post(
                "/v3.1/requirements",
                json={"name": "Mass budget", "metric": "mass_kg", "op": "<=", "target": 10.0, "unit": "kg", "criticality": "important", "scope_object_ids": [part_id]},
            ),
            "create requirement",
        ).json()
        requirement_id = req["id"]
        verified = _assert_ok(client.post("/v3.1/requirements/verify"), "verify requirements").json()
        mass_result = next(row for row in verified["items"] if row["requirement"]["id"] == requirement_id)
        assert mass_result["status"] == "pass", mass_result
        evidence = _assert_ok(client.get("/v3.1/evidence", params={"requirement_id": requirement_id}), "requirement evidence").json()
        assert evidence["count"] >= 1, evidence
        assert evidence["items"][-1]["input_fingerprints"], evidence

        # Engineering graph projection and impact traversal.
        graph = _assert_ok(client.get("/v3.1/graph"), "engineering graph").json()
        assert any(row["id"] == f"cad:{part_id}" for row in graph["nodes"]), graph
        assert any(row["kind"] == "requirement" and row["source_id"] == requirement_id for row in graph["nodes"]), graph
        impact = _assert_ok(client.get(f"/v3.1/graph/impact/cad:{part_id}"), "graph impact").json()
        assert isinstance(impact["impacted"], list), impact

        # DFM screening binds findings to exact geometry fingerprints.
        dfm = _assert_ok(client.get(f"/v3.1/manufacturing/screen/{part_id}", params={"process": "cnc"}), "manufacturing screening").json()
        assert len(dfm["geometry_fingerprint"]) == 64, dfm
        assert "limitations" in dfm, dfm

        # Component ecosystem remains factual/local but exposes cross-vendor families.
        ecosystem = _assert_ok(client.get("/v3.1/components/ecosystem"), "component ecosystem").json()
        assert ecosystem["registry"]["total"] >= 1000, ecosystem
        families = _assert_ok(client.get("/v3.1/components/families"), "component families").json()
        assert families["count"] > 0, families

        # Add a programmable real component and verify design/deployment drift.
        added = _assert_ok(client.post("/v2/components/compute.raspberry_pi_5_8gb/add"), "add Raspberry Pi").json()
        pi_object_id = added["component"]["instance_id"]
        assert pi_object_id, added
        drift_record = _assert_ok(
            client.post(
                "/v3.1/hardware/deployments",
                json={"object_id": pi_object_id, "software_sha256": "0" * 64, "device_id": "pi-selftest", "firmware_version": "selftest", "telemetry": {"cpu_temperature_c": 42.0}},
            ),
            "record deployment",
        ).json()
        assert drift_record["status"] == "drift", drift_record
        drift = _assert_ok(client.get("/v3.1/hardware/drift", params={"object_id": pi_object_id}), "hardware drift").json()
        assert any(row["code"] == "software_drift" for row in drift["findings"]), drift

        # Constraint-driven substitution produces impact before any accepted mutation.
        substitutions = _assert_ok(
            client.post(
                "/v3.1/components/substitution/candidates",
                json={"object_id": pi_object_id, "constraints": {}, "allow_envelope_growth_pct": 25, "max_candidates": 5, "min_trust": 0},
            ),
            "substitution candidates",
        ).json()
        assert "impact" in substitutions and isinstance(substitutions["items"], list), substitutions

        # Physical inspection feeds observed reality back into the graph.
        inspection = _assert_ok(
            client.post(
                "/v3.1/physical/inspections",
                json={"object_id": part_id, "metric": "x_mm", "observed": 41.0, "expected": 40.0, "unit": "mm", "tolerance": 0.2, "instrument": "selftest-caliper", "confidence": 0.99},
            ),
            "physical inspection",
        ).json()
        assert inspection["record"]["status"] == "fail", inspection
        dirty_node = _assert_ok(client.get(f"/v3.1/graph/nodes/cad:{part_id}"), "dirty node after physical evidence").json()
        assert dirty_node["node"]["dirty"] is True, dirty_node

        # High-fidelity analyses are explicit solver contracts, never fake local solves.
        solvers = _assert_ok(client.get("/v3.1/solvers"), "solver adapters").json()
        assert any(row["id"] == "external.fea" and row.get("requires_adapter") for row in solvers["items"]), solvers
        solver_job = _assert_ok(
            client.post(
                "/v3.1/solvers/jobs/contract",
                json={"kind": "external_fea", "subject_node_ids": [f"cad:{part_id}"], "requested_fidelity": "high_fidelity", "settings": {"contacts": "explicit"}},
            ),
            "solver job contract",
        ).json()
        assert solver_job["provenance_required"] is True, solver_job

        # Reproducible fabrication archive contains source design, geometry, software,
        # BOM/evidence and member hashes tied to the exact graph revision.
        archive = _assert_ok(
            client.post(
                "/v3.1/fabrication/archive",
                json={"name": "3.1 Selftest Fabrication", "processes": {part_id: "cnc", loft_obj["id"]: "fdm"}, "include_step": True, "include_stl": True},
            ),
            "fabrication archive",
        )
        assert archive.headers.get("x-forgecad-fabrication-sha256"), archive.headers
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names and "design.focad" in names and "bom.csv" in names, names
            assert any(name.endswith(".step") for name in names if name.startswith("parts/")), names
            assert any(name.endswith(".stl") for name in names if name.startswith("parts/")), names
            assert any(name.startswith(f"software/{pi_object_id}/") for name in names), names
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["format"] == "forgecad-fabrication", manifest
            assert manifest["engineering_graph_revision"], manifest

        # Recovery checkpoints preserve complete multi-branch canonical state.
        checkpoint = _assert_ok(client.post("/v3.1/recovery/checkpoints", json={"label": "selftest", "reason": "v3.1 acceptance"}), "create recovery checkpoint").json()
        checkpoint_id = checkpoint["id"]
        checkpoints = _assert_ok(client.get("/v3.1/recovery/checkpoints"), "list recovery checkpoints").json()
        assert any(row.get("id") == checkpoint_id for row in checkpoints["items"]), checkpoints

        # Create divergent non-conflicting branches and merge them onto a new branch.
        base_branch = _assert_ok(client.get("/v2/project"), "project before branch test").json()["active_branch"]
        source_snapshot = _assert_ok(client.post("/v2/branches", json={"name": "v31-source", "reason": "semantic merge source"}), "create source branch").json()
        source_branch = source_snapshot["active_branch"]
        _assert_ok(client.post("/v2/operations", json={"op": "add_note", "args": {"title": "Source note", "text": "source-only"}, "reason": "source change"}), "source change")
        _assert_ok(client.post(f"/v2/branches/{base_branch}/activate"), "return to merge base")
        target_snapshot = _assert_ok(client.post("/v2/branches", json={"name": "v31-target", "reason": "semantic merge target"}), "create target branch").json()
        target_branch = target_snapshot["active_branch"]
        _assert_ok(client.post("/v2/operations", json={"op": "settings", "args": {"selftest_target_flag": True}, "reason": "target change"}), "target change")
        preflight = _assert_ok(client.post("/v3.1/history/merge/preflight", json={"source": source_branch, "target": target_branch}), "merge preflight").json()
        assert preflight["ok"] is True and preflight["conflict_count"] == 0, preflight
        merged = _assert_ok(client.post("/v3.1/history/merge", json={"source": source_branch, "target": target_branch, "branch_name": "v31-merged"}), "apply merge").json()
        assert merged["ok"] is True and merged["merge_branch"].startswith("v31-merged"), merged

        # Closed-loop engine can verify/diagnose without granting arbitrary autonomous mutation.
        loop = _assert_ok(
            client.post(
                "/v3.1/engineering-loop",
                json={"requirement_ids": [requirement_id], "max_iterations": 2, "mode": "propose", "create_checkpoint": True},
            ),
            "bounded engineering loop",
        ).json()
        assert loop["policy"]["arbitrary_geometry_or_physical_actions"] == "never auto-applied by this loop", loop
        assert loop["status"] in {"satisfied", "needs_review"}, loop

        # Jarvis gets one compact semantic context spanning engineering + world state.
        jarvis = _assert_ok(client.get("/v3.1/jarvis/context"), "Jarvis 3.1 context").json()
        assert jarvis["engine_version"] == "3.1.0", jarvis
        assert jarvis["engineering_graph_revision"], jarvis
        assert jarvis["nodes"], jarvis
        assert "hardware_drift" in jarvis and "world" in jarvis, jarvis

        # A restore is intentionally tested last because it rewinds canonical state.
        restored = _assert_ok(client.post(f"/v3.1/recovery/checkpoints/{checkpoint_id}/restore"), "restore recovery checkpoint").json()
        assert restored["ok"] is True, restored

        final_health = _assert_ok(client.get("/v3.1/health"), "final health").json()
        assert final_health["engineering_graph"]["ready"] is True, final_health

        return {
            "v310_selftest": "PASS",
            "engine_version": final_health["engine_version"],
            "engineering_graph": True,
            "feature_history": True,
            "product_lab_profile": True,
            "requirements_evidence": True,
            "component_ecosystem": True,
            "constraint_substitution": True,
            "manufacturing_screening": True,
            "fabrication_archive": True,
            "physical_feedback": True,
            "hardware_drift": True,
            "solver_contracts": True,
            "semantic_merge": True,
            "recovery_checkpoints": True,
            "bounded_engineering_loop": True,
            "jarvis_semantic_context": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
