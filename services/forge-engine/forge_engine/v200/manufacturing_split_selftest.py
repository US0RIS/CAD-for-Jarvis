from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 oversized-part P2S splitting."""

from io import BytesIO
import zipfile

from ..engineering_state import PROJECT
from ..v110 import core
from . import manufacturing, manufacturing_split


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Oversize P2S panel",
            "kind": "box",
            "params": {"x": 520.0, "y": 100.0, "z": 40.0},
            "material": "abs",
            "semantic": {"role": "panel", "tags": ["fabricated", "3d-print"]},
        },
        actor="human",
        reason="Create deterministic P2S split fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    source_branch = core.ACTIVE_DESIGN
    source_volume = float(core.build_shape(core.object_by_id(object_id)).Volume())

    plan = manufacturing_split.split_plan(
        core.object_by_id(object_id),
        margin_mm=8.0,
        max_pieces=6,
        alignment_diameter_mm=3.2,
        alignment_depth_mm=8.0,
    )
    assert plan["split_required"] is True
    assert plan["grid_counts"] == [3, 1, 1], plan
    assert plan["piece_count"] == 3
    assert plan["seam_count"] == 2
    assert plan["alignment_pair_count"] >= 2
    assert all(max(row["bounds_mm"]) <= 240.0 + 1e-6 for row in plan["pieces"])

    operation = PROJECT.execute(
        "split_for_manufacturing",
        {
            "id": object_id,
            "resource_id": "bambu-lab-p2s",
            "margin_mm": 8.0,
            "max_pieces": 6,
            "alignment_diameter_mm": 3.2,
            "alignment_depth_mm": 8.0,
        },
        actor="forge-agent",
        reason="Adapt oversized panel to the available P2S",
    )
    split = operation["operation"]["split"]
    split_branch = str(split["split_branch"])
    assert split_branch != source_branch
    assert core.ACTIVE_DESIGN == split_branch
    assert split["physical_verification"] is False
    assert len(split["piece_ids"]) == 3

    hidden_source = core.object_by_id(object_id)
    assert hidden_source["visible"] is False
    assert hidden_source["semantic"]["manufacturing"] == "source_unsplit_reference"

    pieces = [core.object_by_id(piece_id) for piece_id in split["piece_ids"]]
    assert all(row["kind"] == "manufacturing_piece" for row in pieces)
    assert all(row["visible"] is True for row in pieces)
    assert all(row["semantic"]["joint_validation_required"] is True for row in pieces)
    assert all(row["params"]["source_snapshot"]["id"] == object_id for row in pieces)

    piece_volumes = []
    for piece in pieces:
        shape = core.build_shape(piece)
        volume = float(shape.Volume())
        assert volume > 0.0
        assert volume < source_volume
        piece_volumes.append(volume)
        check = manufacturing.analyze_object(piece, core.build_shape)
        assert check["eligible"] is True, check
        assert check["fits_build_volume"] is True, check

    # Alignment sockets remove a small amount of material, so the piece sum should be
    # close to but no greater than the exact unsplit source volume.
    assert sum(piece_volumes) <= source_volume + 1e-3
    assert sum(piece_volumes) >= source_volume * 0.98

    fabricated = manufacturing.fabricated_objects(core.PROJECT)
    fabricated_ids = {str(row["id"]) for row in fabricated}
    assert object_id not in fabricated_ids
    assert set(split["piece_ids"]) <= fabricated_ids

    status = manufacturing.p2s_status(core.PROJECT, core.build_shape)
    assert status["fabricated_part_count"] == 3
    assert status["all_parts_fit_individually"] is True
    assert status["plate_packing"]["unplaced_object_ids"] == []
    assert status["estimated_plate_count"] is not None

    package = manufacturing.geometry_3mf(core.PROJECT, core.tessellate, tolerance_mm=0.5)
    assert package.startswith(b"PK")
    with zipfile.ZipFile(BytesIO(package), "r") as archive:
        model = archive.read("3D/3dmodel.model")
        for index in range(1, 4):
            assert f"Oversize P2S panel — P2S {index}/3".encode("utf-8") in model

    split_notes = [row for row in core.PROJECT.get("notebook", []) if row.get("kind") == "manufacturing_split"]
    assert len(split_notes) == 1
    assert split_notes[0]["source_branch"] == source_branch
    assert split_notes[0]["split_branch"] == split_branch

    # The manufacturing adaptation must never rewrite the source design in place.
    PROJECT.activate_branch(source_branch)
    source = core.object_by_id(object_id)
    assert source["visible"] is True
    assert float(core.build_shape(source).Volume()) == source_volume
    assert not any(row.get("kind") == "manufacturing_piece" for row in core.PROJECT["objects"])

    PROJECT.execute(
        "add",
        {
            "name": "Already fitting part",
            "kind": "box",
            "params": {"x": 100.0, "y": 80.0, "z": 20.0},
            "material": "abs",
            "semantic": {"role": "small_part", "tags": ["fabricated", "3d-print"]},
        },
        actor="human",
        reason="Create no-split control",
    )
    fitting_id = str(core.PROJECT["objects"][-1]["id"])
    fitting_plan = manufacturing_split.split_plan(core.object_by_id(fitting_id), margin_mm=8.0)
    assert fitting_plan["split_required"] is False
    try:
        manufacturing_split.apply_split(fitting_id)
    except ValueError as exc:
        assert "no split is required" in str(exc)
    else:
        raise AssertionError("Already-fitting P2S part should not be split")

    return {
        "source_branch": source_branch,
        "split_branch": split_branch,
        "grid_counts": plan["grid_counts"],
        "pieces": len(pieces),
        "alignment_pairs": plan["alignment_pair_count"],
        "all_pieces_fit": True,
        "source_preserved": True,
        "3mf_bytes": len(package),
        "joint_validation_required": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 manufacturing split self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
