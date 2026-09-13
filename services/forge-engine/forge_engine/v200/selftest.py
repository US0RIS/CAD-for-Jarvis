from __future__ import annotations

"""Deterministic ForgeCAD 2.0 design-intelligence regression test.

This deliberately exercises the pieces that distinguish 2.0 from the v1 planner:
functional decomposition, capability resolution, exact catalog selection, symbolic
references to newly created objects, custom parametric CAD, embedded code, canonical
requirements/architecture persistence, and bounded validation-repair decisions.
"""

from copy import deepcopy

from ..engineering_state import PROJECT
from ..v110 import core
from . import DESIGN_INTELLIGENCE_VERSION
from . import agent_loop
from . import design_intelligence


def run() -> dict[str, object]:
    assert DESIGN_INTELLIGENCE_VERSION == "2.0.0"
    PROJECT.new_project()

    request = "Create a tool that sends a Discord DM whenever the door it is placed on is opened."
    architecture = design_intelligence.bootstrap_architecture(request, PROJECT.snapshot())
    context = design_intelligence.build_planner_context(request, architecture, PROJECT.snapshot())
    capabilities = {str(row.get("capability")) for row in context["functions"]}
    for required in {"physical_state_sensing", "remote_notification", "network_connectivity", "programmable_compute", "software_integration"}:
        assert required in capabilities, (required, capabilities)
    candidates = {str(row.get("id")) for row in context["candidate_components"]}
    assert "sensor.adafruit.magnetic_contact_375" in candidates

    canonical_architecture = {
        "goal": request,
        "requirements": [
            {
                "id": "R1",
                "statement": "Opening the door must trigger a remote Discord notification.",
                "priority": "must",
                "verification": "Open the contact and verify the configured Discord API call succeeds.",
            }
        ],
        "functions": deepcopy(context["functions"]),
        "assumptions": ["Network connectivity is available at the installation location."],
        "open_questions": ["DISCORD_BOT_TOKEN and DISCORD_USER_ID are deployment configuration values."],
        "design_intelligence_version": DESIGN_INTELLIGENCE_VERSION,
    }
    code = """import os\n\nDISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')\nDISCORD_USER_ID = os.environ.get('DISCORD_USER_ID', '')\n\ndef on_door_open():\n    # Runtime integration uses configured credentials; never bake secrets into .focad.\n    return bool(DISCORD_BOT_TOKEN and DISCORD_USER_ID)\n"""
    plan = {
        "summary": "Build a door-contact + Raspberry Pi notification system with a fabricated sensor mount.",
        "architecture": canonical_architecture,
        "checks": ["Configure Discord credentials before deployment."],
        "commands": [
            {"op": "add_component", "as": "controller", "args": {"component_id": "compute.raspberry_pi_5_8gb", "name": "Door monitor controller"}},
            {"op": "add_component", "as": "door_contact", "args": {"component_id": "sensor.adafruit.magnetic_contact_375", "name": "Door magnetic contact"}},
            {"op": "transform", "args": {"id": "$door_contact", "position": [55.0, 0.0, 5.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}},
            {"op": "connect_interfaces", "args": {"a_id": "$door_contact", "a_interface": "contact", "b_id": "$controller", "b_interface": "gpio40", "kind": "signal"}},
            {"op": "code_write", "args": {"id": "$controller", "path": "main.py", "content": code}},
            {"op": "add", "as": "sensor_mount", "args": {"name": "Door sensor mounting plate", "kind": "box", "params": {"x": 42.0, "y": 22.0, "z": 3.0}, "material": "abs", "transform": {"position": [55.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}, "semantic": {"role": "sensor_mount", "tags": ["custom", "fabricated", "door"]}}},
            {"op": "add_feature", "args": {"id": "$sensor_mount", "feature": {"type": "hole", "diameter": 3.2, "axis": "z", "x": -15.0, "y": 0.0, "z": 0.0}}},
            {"op": "add_feature", "args": {"id": "$sensor_mount", "feature": {"type": "hole", "diameter": 3.2, "axis": "z", "x": 15.0, "y": 0.0, "z": 0.0}}},
        ],
    }

    result = PROJECT.apply_agent_plan(plan, request)
    handles = result["handles"]
    assert set(handles) == {"controller", "door_contact", "sensor_mount"}
    assert len(set(handles.values())) == 3

    objects = {str(obj["id"]): obj for obj in core.PROJECT["objects"]}
    controller = objects[handles["controller"]]
    contact = objects[handles["door_contact"]]
    mount = objects[handles["sensor_mount"]]
    assert controller["component_ref"] == "compute.raspberry_pi_5_8gb"
    assert contact["component_ref"] == "sensor.adafruit.magnetic_contact_375"
    assert contact["transform"]["position"] == [55.0, 0.0, 5.0]
    assert "DISCORD_BOT_TOKEN" in controller["code"]["files"]["main.py"]
    assert mount["kind"] == "box" and len(mount["features"]) == 2
    assert any(connection["a"]["object_id"] == contact["id"] and connection["b"]["object_id"] == controller["id"] for connection in core.PROJECT["connections"])

    architecture_notes = [note for note in core.PROJECT["notebook"] if note.get("kind") == "design_architecture"]
    assert len(architecture_notes) == 1
    assert architecture_notes[0]["architecture"]["goal"] == request
    requirements = [row for row in core.PROJECT["requirements"] if row.get("source") == "forgecad-v2-architecture"]
    assert len(requirements) == 1
    assert requirements[0]["statement"].startswith("Opening the door")

    # Applying another plan with the same architecture must not duplicate the architecture
    # record or qualitative requirement.
    second = {"summary": "Record deployment note", "architecture": canonical_architecture, "commands": [{"op": "add_note", "args": {"kind": "deployment", "text": "Configure Discord credentials before deployment."}}], "checks": []}
    PROJECT.apply_agent_plan(second, "Continue door monitor design")
    assert len([note for note in core.PROJECT["notebook"] if note.get("kind") == "design_architecture"]) == 1
    assert len([row for row in core.PROJECT["requirements"] if row.get("source") == "forgecad-v2-architecture"]) == 1

    warning_only = {"risks": [{"severity": "warning", "code": "review", "message": "Review installation."}], "requirements": []}
    hard_failure = {"risks": [{"severity": "error", "code": "collision", "message": "Hard collision."}], "requirements": []}
    assert not agent_loop.should_repair(warning_only, iteration=0)
    assert agent_loop.should_repair(hard_failure, iteration=0)
    assert not agent_loop.should_repair(hard_failure, iteration=agent_loop.MAX_REPAIR_ITERATIONS)

    scene = PROJECT.scene_manifest()
    assert scene["authoritative"] is True and len(scene["parts"]) == 3
    return {
        "version": DESIGN_INTELLIGENCE_VERSION,
        "capabilities": len(capabilities),
        "candidates": len(candidates),
        "objects": len(core.PROJECT["objects"]),
        "connections": len(core.PROJECT["connections"]),
        "requirements": len(core.PROJECT["requirements"]),
        "architecture_notes": len(architecture_notes),
        "symbolic_handles": sorted(handles),
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
