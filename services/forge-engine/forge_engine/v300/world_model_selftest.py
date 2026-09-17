from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from .world_model import (
    PhysicalWorldStore,
    ProvenanceRecord,
    ROOT_WORLD_ID,
    WorldCapability,
    WorldEntity,
    WorldPose,
    sync_forgecad_project,
)


def run() -> dict[str, object]:
    from ..v110 import acceptance_design

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "world.json"
        store = PhysicalWorldStore(path)

        root = store.entity(ROOT_WORLD_ID)
        assert root.kind == "world"
        assert root.parent_id is None

        room = store.upsert_entity(
            WorldEntity(
                id="room:lab",
                name="Prototype Lab",
                kind="room",
                parent_id=ROOT_WORLD_ID,
                pose=WorldPose(frame_id=ROOT_WORLD_ID, position_m=[1.0, 2.0, 0.0]),
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )
        machine = store.upsert_entity(
            WorldEntity(
                id="machine:bench-robot",
                name="Bench Robot",
                kind="machine",
                parent_id=room.id,
                pose=WorldPose(frame_id=room.id, position_m=[0.5, 0.2, 0.8]),
                capabilities=[WorldCapability(name="motion.rotate", mode="actuate")],
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )
        assert store.entity(machine.id).parent_id == room.id

        cycle_rejected = False
        try:
            room.parent_id = machine.id
            store.upsert_entity(room, source="human")
        except ValueError:
            cycle_rejected = True
        assert cycle_rejected

        sample = store.observe(
            entity_id=machine.id,
            key="joint_1_deg",
            value=34.7,
            unit="deg",
            source="sensor",
            source_id="encoder:j1",
            confidence=0.98,
        )
        assert sample.value == 34.7
        assert store.entity(machine.id).live_state["joint_1_deg"].source_id == "encoder:j1"

        project = acceptance_design.build_project()
        project_snapshot = {
            "name": project["name"],
            "active_branch": "baseline",
            "revision": "baseline:selftest",
            "connections": deepcopy(project["connections"]),
        }
        first = sync_forgecad_project(
            store,
            project_snapshot=project_snapshot,
            raw_objects=deepcopy(project["objects"]),
            parent_id=room.id,
        )
        assert first["project_object_count"] >= 6

        project_entity_id = str(first["project_entity_id"])
        assert store.entity(project_entity_id).parent_id == room.id

        pi_world_id = f"forgecad:object:{acceptance_design.IDS['pi']}"
        pi = store.entity(pi_world_id)
        capability_names = {row.name for row in pi.capabilities}
        assert "compute.execute" in capability_names
        assert "software.deploy" in capability_names
        assert pi.source_links["component_ref"] == acceptance_design.COMPONENTS["pi"]
        assert pi.pose.position_m == [value / 1000.0 for value in acceptance_design.POSITIONS["pi"]]
        assert pi.interfaces, "Frozen component interfaces were not projected"

        relation_ids = {row.id for row in store.relations()}
        assert len(relation_ids) >= 5
        assert all(row_id.startswith("forgecad:connection:") for row_id in relation_ids)

        entity_ids_before = {row.id for row in store.entities()}
        second = sync_forgecad_project(
            store,
            project_snapshot=project_snapshot,
            raw_objects=deepcopy(project["objects"]),
            parent_id=room.id,
        )
        entity_ids_after = {row.id for row in store.entities()}
        assert entity_ids_after == entity_ids_before
        assert second["project_entity_id"] == first["project_entity_id"]

        reduced_objects = [row for row in deepcopy(project["objects"]) if row["id"] != acceptance_design.IDS["solenoid"]]
        reduced_connections = [
            row for row in deepcopy(project["connections"])
            if (row.get("a") or {}).get("object_id") != acceptance_design.IDS["solenoid"]
            and (row.get("b") or {}).get("object_id") != acceptance_design.IDS["solenoid"]
        ]
        reduced_snapshot = {**project_snapshot, "revision": "baseline:selftest:reduced", "connections": reduced_connections}
        sync_forgecad_project(store, project_snapshot=reduced_snapshot, raw_objects=reduced_objects, parent_id=room.id)
        removed_world_id = f"forgecad:object:{acceptance_design.IDS['solenoid']}"
        assert removed_world_id not in {row.id for row in store.entities()}
        assert all(row.a_id != removed_world_id and row.b_id != removed_world_id for row in store.relations())

        reloaded = PhysicalWorldStore(path)
        assert reloaded.entity(machine.id).live_state["joint_1_deg"].value == 34.7
        assert reloaded.entity(project_entity_id).id == project_entity_id
        assert {row.id for row in reloaded.entities()} == {row.id for row in store.entities()}

        summary = reloaded.summary()
        assert summary["entity_count"] >= 8, summary
        assert summary["relation_count"] >= 1, summary

        return {
            "world_model_selftest": "PASS",
            "schema_version": summary["schema_version"],
            "entity_count": summary["entity_count"],
            "relation_count": summary["relation_count"],
            "event_count": summary["event_count"],
            "cycle_rejected": cycle_rejected,
            "stable_project_identity": second["project_entity_id"] == first["project_entity_id"],
            "observation_persisted": True,
            "millimeter_to_meter_projection": True,
            "stale_project_entity_removed": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
