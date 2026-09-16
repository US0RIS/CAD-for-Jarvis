from __future__ import annotations

"""Regression gate for complete multi-branch `.focad` round trips."""

from io import BytesIO
import json
import zipfile

from ..engineering_state import PROJECT
from ..v110 import core


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Branch fixture",
            "kind": "box",
            "params": {"x": 20.0, "y": 10.0, "z": 4.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "branch_fixture", "tags": ["fabricated"]},
        },
        actor="human",
        reason="Create branch workspace fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    source_branch = core.ACTIVE_DESIGN
    assert source_branch == "main"

    PROJECT.create_branch("failed-thicker", "Workspace portability candidate")
    experiment_branch = core.ACTIVE_DESIGN
    PROJECT.execute(
        "update",
        {"id": object_id, "params": {"x": 20.0, "y": 10.0, "z": 8.0}},
        actor="human",
        reason="Make branch geometrically distinct",
    )
    PROJECT.set_branch_status(experiment_branch, "not_working", "Physical prototype interfered with enclosure", False)
    assert core.object_by_id(object_id)["params"]["z"] == 8.0

    PROJECT.activate_branch(source_branch)
    assert core.object_by_id(object_id)["params"]["z"] == 4.0
    PROJECT.set_branch_status(source_branch, "working", "Known-good physical baseline", True)

    payload = PROJECT.export_bundle()
    with zipfile.ZipFile(BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        assert "workspace.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        workspace = json.loads(archive.read("workspace.json"))
        assert manifest["workspace_file"] == "workspace.json"
        assert manifest["branch_count"] == 2
        assert workspace["active"] == source_branch
        assert set(workspace["branches"]) == {source_branch, experiment_branch}
        assert workspace["designs"][source_branch]["physical_verified"] is True
        assert workspace["designs"][experiment_branch]["status"] == "not_working"

    # Destroy local state before import so passing the test proves the branch graph was
    # actually carried by the portable file rather than inherited from the process.
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {"name": "Disposable state", "kind": "box", "params": {"x": 1.0, "y": 1.0, "z": 1.0}},
        actor="human",
        reason="Prove import replaces current workspace",
    )
    restored = PROJECT.import_bundle(payload)
    assert restored["workspace_restored"] is True
    assert restored["branch_count"] == 2
    snapshot = PROJECT.snapshot()
    assert snapshot["active_branch"] == source_branch
    branches = {row["name"]: row for row in snapshot["branches"]}
    assert set(branches) == {source_branch, experiment_branch}
    assert branches[source_branch]["status"] == "working"
    assert branches[source_branch]["physical_verified"] is True
    assert branches[source_branch]["protected"] is True
    assert branches[experiment_branch]["status"] == "not_working"
    assert core.object_by_id(object_id)["params"]["z"] == 4.0

    PROJECT.activate_branch(experiment_branch)
    assert core.object_by_id(object_id)["params"]["z"] == 8.0
    PROJECT.activate_branch(source_branch)
    assert core.object_by_id(object_id)["params"]["z"] == 4.0

    return {
        "bundle_bytes": len(payload),
        "branches_restored": len(branches),
        "active_branch": source_branch,
        "failed_branch": experiment_branch,
        "working_baseline_protection_restored": branches[source_branch]["protected"],
        "branch_geometry_distinction_restored": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 workspace bundle self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
