from __future__ import annotations

"""Deterministic regression coverage for ForgeCAD 2.0 P2S manufacturing integration."""

from io import BytesIO
import zipfile

from ..v110 import core
from . import design_intelligence
from . import manufacturing


def run() -> dict[str, object]:
    project = core.upgrade_project(core.default_project())
    project["name"] = "P2S manufacturing self-test"
    project["objects"] = [
        {
            "id": "printed-bracket",
            "name": "Printed bracket",
            "kind": "box",
            "params": {"x": 80.0, "y": 45.0, "z": 12.0},
            "material": "abs",
            "transform": {"position": [0.0, 0.0, 6.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "features": [
                {"type": "hole", "diameter": 4.2, "axis": "z", "x": -28.0, "y": 0.0, "z": 0.0},
                {"type": "hole", "diameter": 4.2, "axis": "z", "x": 28.0, "y": 0.0, "z": 0.0},
            ],
            "semantic": {"role": "mount", "tags": ["fabricated", "3d-print"], "wall_thickness_mm": 2.4},
            "visible": True,
        },
        {
            "id": "oversize-panel",
            "name": "Oversize panel",
            "kind": "box",
            "params": {"x": 300.0, "y": 300.0, "z": 5.0},
            "material": "abs",
            "transform": {"position": [0.0, 0.0, 2.5], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "features": [],
            "semantic": {"role": "panel", "tags": ["fabricated", "3d-print"]},
            "visible": True,
        },
        {
            "id": "purchased-placeholder",
            "name": "Purchased component placeholder",
            "kind": "component",
            "component_ref": "compute.raspberry_pi_5_8gb",
            "params": {"x": 85.0, "y": 56.0, "z": 17.0},
            "material": "fr4",
            "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "features": [],
            "semantic": {"role": "compute"},
            "visible": True,
        },
    ]

    fabricated = manufacturing.fabricated_objects(project)
    assert {row["id"] for row in fabricated} == {"printed-bracket", "oversize-panel"}

    bracket = manufacturing.analyze_object(next(row for row in fabricated if row["id"] == "printed-bracket"), core.build_shape)
    assert bracket["fits_build_volume"] is True
    assert bracket["wall_thickness_status"] == "declared"

    panel = manufacturing.analyze_object(next(row for row in fabricated if row["id"] == "oversize-panel"), core.build_shape)
    assert panel["fits_build_volume"] is False
    assert any(warning["code"] == "exceeds_build_volume" for warning in panel["warnings"])

    payload = manufacturing.geometry_3mf(project, core.tessellate, object_ids=["printed-bracket"], tolerance_mm=0.25)
    assert payload.startswith(b"PK")
    with zipfile.ZipFile(BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names
        model = archive.read("3D/3dmodel.model")
        assert b"Printed bracket" in model
        assert b"triangle" in model

    command = manufacturing.build_bambu_cli_command(
        "/opt/BambuStudio",
        "/tmp/input.3mf",
        "/tmp/output",
        machine_profile="/profiles/p2s-machine.json",
        process_profile="/profiles/process.json",
        filament_profiles=["/profiles/petg.json"],
    )
    assert "--orient" in command
    assert command[command.index("--arrange") + 1] == "1"
    assert command[command.index("--slice") + 1] == "0"
    assert command[command.index("--export-3mf") + 1].endswith(".3mf")
    assert "/profiles/p2s-machine.json;/profiles/process.json" in command
    assert "/profiles/petg.json" in command

    status = manufacturing.p2s_status(project, core.build_shape)
    assert status["resource"]["build_volume_mm"] == [256.0, 256.0, 256.0]
    assert status["fabricated_part_count"] == 2
    assert status["all_parts_fit_individually"] is False
    assert status["lan_control"]["implemented"] is False

    # Manufacturing must be part of design reasoning, not a disconnected export tool.
    request = "Design a printable enclosure for my Bambu P2S."
    architecture = design_intelligence.bootstrap_architecture(request, {"parts": []})
    context = design_intelligence.build_planner_context(request, architecture, {"parts": []})
    manufacturing_rows = [row for row in context["functions"] if row.get("capability") == "additive_manufacturing"]
    assert len(manufacturing_rows) == 1
    assert manufacturing_rows[0]["status"] == "manufacturing_resource"
    assert manufacturing_rows[0]["candidate_components"] == []
    assert manufacturing_rows[0]["constraints"]["build_volume_mm"] == [256.0, 256.0, 256.0]
    resources = context["available_manufacturing_resources"]
    assert len(resources) == 1 and resources[0]["id"] == "bambu-lab-p2s"
    assert context["manufacturing_policy"]["primary_exchange_format"] == "3mf"
    assert context["manufacturing_policy"]["direct_printer_control_available"] is False

    return {
        "printer": status["resource"]["model"],
        "fabricated_parts": status["fabricated_part_count"],
        "3mf_bytes": len(payload),
        "build_volume_mm": status["resource"]["build_volume_mm"],
        "headless_slice_ready": status["slicer"]["ready_for_headless_slice"],
        "planner_manufacturing_status": manufacturing_rows[0]["status"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 manufacturing self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
