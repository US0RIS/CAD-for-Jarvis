from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .planner_world_context import build_physical_world_planner_context, install_world_aware_planner
from .world_model import (
    PhysicalWorldStore,
    ProvenanceRecord,
    ROOT_WORLD_ID,
    WorldCapability,
    WorldEntity,
)


def run() -> dict[str, object]:
    from .. import main_v2 as v2
    from ..v200 import design_intelligence

    with tempfile.TemporaryDirectory() as temp_dir:
        store = PhysicalWorldStore(Path(temp_dir) / "world.json")
        room = store.upsert_entity(
            WorldEntity(
                id="room:planner-lab",
                name="Planner Lab",
                kind="room",
                parent_id=ROOT_WORLD_ID,
                provenance=[ProvenanceRecord(source="human", source_id="planner-selftest", authoritative=True)],
            ),
            source="human",
        )
        linked = store.upsert_entity(
            WorldEntity(
                id="machine:linked-arm",
                name="Linked Arm",
                kind="machine",
                parent_id=room.id,
                capabilities=[WorldCapability(name="motion.rotate", mode="actuate")],
                source_links={"forgecad_object_id": "cad-arm-001", "serial": "ARM-001"},
                provenance=[ProvenanceRecord(source="forgecad_project", source_id="baseline", authoritative=True)],
            ),
            source="forgecad_project",
        )
        observed_only = store.upsert_entity(
            WorldEntity(
                id="sensor:ambient",
                name="Ambient Sensor",
                kind="sensor",
                parent_id=room.id,
                capabilities=[WorldCapability(name="sense.temperature", mode="sense")],
                source_links={"serial": "TEMP-001"},
                provenance=[ProvenanceRecord(source="human", source_id="planner-selftest", authoritative=True)],
            ),
            source="human",
        )
        store.observe(
            entity_id=observed_only.id,
            key="temperature_c",
            value=22.4,
            unit="degC",
            source="sensor",
            source_id="TEMP-001",
            confidence=0.97,
        )

        compact = build_physical_world_planner_context(store, "inspect the linked arm")
        by_id = {row["entity_id"]: row for row in compact["entities"]}
        assert by_id[linked.id]["design_addressable"] is True
        assert by_id[linked.id]["forgecad_object_id"] == "cad-arm-001"
        assert by_id[observed_only.id]["design_addressable"] is False
        assert by_id[observed_only.id]["forgecad_object_id"] is None
        assert by_id[observed_only.id]["live_state"]["temperature_c"]["value"] == 22.4
        assert compact["design_links"] == {linked.id: "cad-arm-001"}

        install_world_aware_planner(store)
        project = {
            "name": "Planner World Context Self-test",
            "active_branch": "main",
            "revision": "selftest",
            "parts": [
                {
                    "id": "cad-arm-001",
                    "name": "Linked Arm CAD",
                    "role": "actuator",
                    "mass_g": 1000.0,
                    "material": "Aluminum",
                    "component_ref": None,
                }
            ],
            "requirements": [],
            "connections": [],
        }
        request = "Inspect the Linked Arm and account for the observed ambient temperature."
        architecture = design_intelligence.bootstrap_architecture(request, project)
        context = v2._planner_context(request, architecture, project)
        assert context["physical_world"]["revision"] == store.snapshot().revision
        planner_rows = {row["entity_id"]: row for row in context["physical_world"]["entities"]}
        assert planner_rows[linked.id]["forgecad_object_id"] == "cad-arm-001"
        assert planner_rows[observed_only.id]["design_addressable"] is False

        system = v2._planner_system()
        assert "entity_id values are stable real-world identity, NOT CAD object IDs" in system
        assert "explicit forgecad_object_id" in system
        assert "typed capability/action runtime" in system

        # Updating the installation swaps the backing store instead of stacking wrappers.
        second = PhysicalWorldStore(Path(temp_dir) / "world-2.json")
        second.upsert_entity(
            WorldEntity(
                id="device:replacement",
                name="Replacement Device",
                kind="device",
                parent_id=ROOT_WORLD_ID,
                provenance=[ProvenanceRecord(source="human", source_id="planner-selftest", authoritative=True)],
            ),
            source="human",
        )
        install_world_aware_planner(second)
        swapped = v2._planner_context(request, architecture, project)["physical_world"]
        swapped_ids = {row["entity_id"] for row in swapped["entities"]}
        assert "device:replacement" in swapped_ids
        assert linked.id not in swapped_ids

        return {
            "planner_world_context_selftest": "PASS",
            "world_context_injected": True,
            "live_state_exposed": True,
            "world_id_not_cad_id": True,
            "design_bridge_requires_explicit_source_link": True,
            "planner_system_guardrails": True,
            "reinstall_does_not_stack_wrappers": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
