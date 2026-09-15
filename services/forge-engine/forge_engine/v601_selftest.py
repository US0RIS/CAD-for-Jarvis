from __future__ import annotations

"""Focused ForgeCAD 6.0.1 release-hardening checks.

These checks intentionally exercise canonical branch state directly. They are not UI
mocks: a code write must survive the same sibling-branch round trip used by the desktop.
"""

from .engineering_state import PROJECT
from .v110 import core


def _code_for(project: dict, object_id: str, path: str) -> str:
    obj = next(row for row in project.get("objects", []) if str(row.get("id")) == object_id)
    return str(((obj.get("code") or {}).get("files") or {}).get(path) or "")


def code_write_survives_branch_round_trip() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.add_component("compute.raspberry_pi_5_8gb")
    snapshot = PROJECT.snapshot()
    workspace_id = str(snapshot["parts"][0]["id"])
    original = PROJECT.read_file(workspace_id, "main.py")["content"]

    PROJECT.create_branch("guard-sibling", "6.0.1 persistence selftest sibling")
    PROJECT.activate_branch("main")
    assert PROJECT.snapshot()["active_branch"] == "main"

    marker = "# forgecad-v601-branch-persistence"
    PROJECT.write_file(workspace_id, "main.py", original + "\n" + marker + "\n")

    immediate = PROJECT.read_file(workspace_id, "main.py")["content"]
    stored_main = _code_for(core.BRANCHES["main"], workspace_id, "main.py")
    assert marker in immediate, "code_write did not update the live main branch"
    assert marker in stored_main, "persist did not update the stored main branch snapshot"

    PROJECT.activate_branch("guard-sibling")
    sibling_content = PROJECT.read_file(workspace_id, "main.py")["content"]
    assert marker not in sibling_content, "sibling branch was rewritten by a main-branch code edit"

    PROJECT.activate_branch("main")
    restored = PROJECT.read_file(workspace_id, "main.py")["content"]
    assert marker in restored, "main branch lost embedded code after a sibling branch round trip"

    return {
        "ok": True,
        "workspace_id": workspace_id,
        "main_has_marker": marker in restored,
        "sibling_has_marker": marker in sibling_content,
        "active_branch": PROJECT.snapshot()["active_branch"],
    }


def main() -> None:
    result = code_write_survives_branch_round_trip()
    print({"forgecad_v601_selftest": result})


if __name__ == "__main__":
    main()
