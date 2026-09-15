from __future__ import annotations

"""Focused ForgeCAD 6.0.1 release-hardening checks.

These checks intentionally exercise canonical branch state directly. They are not UI
mocks: code must survive a branch round trip, job provenance must fail stale, and a
human branch label must not rewrite evidence-owned physical verification.
"""

from . import main as legacy
from .engineering_state import PROJECT
from .models import EngineeringJob
from .v110 import core
from .v601_runtime import assert_job_source, set_design_label_preserving_evidence


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


def stale_job_is_rejected() -> dict[str, object]:
    source = PROJECT.snapshot()
    job = EngineeringJob(
        kind="agent",
        branch=source["active_branch"],
        revision=source["revision"],
        selected_object_id=source["parts"][0]["id"],
    )
    assert_job_source(legacy, job)

    core.execute(
        "add_note",
        {"text": "Change the source revision after the job was queued."},
        actor="human",
        reason="6.0.1 stale-job selftest",
    )
    rejected = False
    try:
        assert_job_source(legacy, job)
    except RuntimeError as exc:
        rejected = "stale" in str(exc).lower()
    assert rejected, "a job queued against an older project revision was not rejected"
    return {"ok": True, "source_revision": job.revision, "current_revision": PROJECT.snapshot()["revision"]}


def branch_label_preserves_physical_evidence() -> dict[str, object]:
    branch = PROJECT.snapshot()["active_branch"]
    with core.LOCK:
        core.DESIGNS[branch]["physical_verified"] = True
        core.persist()

    updated = set_design_label_preserving_evidence(branch, "not_working", "Label-only 6.0.1 selftest")
    assert updated["status"] == "not_working"
    assert updated["physical_verified"] is True, "branch label erased evidence-owned physical verification"
    assert core.DESIGNS[branch]["physical_verified"] is True
    return {"ok": True, "branch": branch, "status": updated["status"], "physical_verified": True}


def main() -> None:
    result = {
        "branch_persistence": code_write_survives_branch_round_trip(),
        "stale_job": stale_job_is_rejected(),
        "evidence_preservation": branch_label_preserves_physical_evidence(),
    }
    print({"forgecad_v601_selftest": result})


if __name__ == "__main__":
    main()
