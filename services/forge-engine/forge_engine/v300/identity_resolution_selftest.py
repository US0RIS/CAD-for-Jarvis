from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .identity_resolution import resolve_entity_reference
from .world_model import PhysicalWorldStore, ProvenanceRecord, ROOT_WORLD_ID, WorldCapability, WorldEntity, WorldPose


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = PhysicalWorldStore(Path(temp_dir) / "world.json")
        room_a = store.upsert_entity(
            WorldEntity(
                id="room:lab-a",
                name="Prototype Lab",
                kind="room",
                parent_id=ROOT_WORLD_ID,
                pose=WorldPose(frame_id=ROOT_WORLD_ID),
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )
        room_b = store.upsert_entity(
            WorldEntity(
                id="room:lab-b",
                name="Robot Lab",
                kind="room",
                parent_id=ROOT_WORLD_ID,
                pose=WorldPose(frame_id=ROOT_WORLD_ID),
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )
        robot_a = store.upsert_entity(
            WorldEntity(
                id="machine:bench-robot-a",
                name="Bench Robot",
                kind="machine",
                parent_id=room_a.id,
                capabilities=[WorldCapability(name="motion.rotate", mode="actuate")],
                source_links={"serial": "BR-A-001", "forgecad_object_id": "robot-a"},
                metadata={"aliases": ["Atlas Bench Arm"]},
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )
        robot_b = store.upsert_entity(
            WorldEntity(
                id="machine:bench-robot-b",
                name="Bench Robot",
                kind="machine",
                parent_id=room_b.id,
                capabilities=[WorldCapability(name="motion.rotate", mode="actuate")],
                source_links={"serial": "BR-B-002", "forgecad_object_id": "robot-b"},
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )

        exact_id = resolve_entity_reference(store, robot_a.id)
        assert exact_id.status == "resolved" and exact_id.entity_id == robot_a.id
        assert exact_id.reason == "entity_id"

        serial = resolve_entity_reference(store, "BR-B-002")
        assert serial.status == "resolved" and serial.entity_id == robot_b.id
        assert serial.reason == "source_link:serial"

        alias = resolve_entity_reference(store, "Atlas Bench Arm")
        assert alias.status == "resolved" and alias.entity_id == robot_a.id
        assert alias.reason == "alias"

        path = resolve_entity_reference(store, "Prototype Lab / Bench Robot")
        assert path.status == "resolved" and path.entity_id == robot_a.id
        assert path.reason == "hierarchy_path"

        duplicate_name = resolve_entity_reference(store, "Bench Robot")
        assert duplicate_name.status == "ambiguous", duplicate_name
        assert duplicate_name.entity_id is None
        assert len(duplicate_name.candidates) == 2

        fuzzy = resolve_entity_reference(store, "prototype bench")
        assert fuzzy.status == "ambiguous", fuzzy
        assert fuzzy.exact is False
        assert fuzzy.entity_id is None
        assert fuzzy.candidates and fuzzy.candidates[0].entity_id == robot_a.id

        scoped = resolve_entity_reference(store, "Bench Robot", capability="motion.rotate")
        assert scoped.status == "ambiguous"
        not_found = resolve_entity_reference(store, "nonexistent welding drone")
        assert not_found.status == "not_found"

        return {
            "identity_resolution_selftest": "PASS",
            "exact_id": exact_id.entity_id,
            "source_link_resolution": serial.entity_id,
            "hierarchy_path_resolution": path.entity_id,
            "duplicate_name_failed_closed": True,
            "fuzzy_match_failed_closed": True,
            "not_found_preserved": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
