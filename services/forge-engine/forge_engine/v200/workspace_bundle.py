from __future__ import annotations

"""ForgeCAD 2.0 multi-branch `.focad` workspace persistence.

The v1 interchange container preserved only the active project JSON. ForgeCAD 2.0 treats
branches as first-class engineering state: known-good baselines, failed experiments,
autonomous campaign candidates, and embedded code variants must survive a round trip.

`project.json` remains the canonical active design for compatibility with external agents.
`workspace.json` adds all branch snapshots plus branch metadata. On import, project.json
replaces the workspace's active branch so an external tool can edit the active design
without understanding ForgeCAD's branch graph, while every untouched sibling survives.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..engineering_state import EngineeringProject
from ..v110 import core, project_bundle


_INSTALLED = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_snapshot() -> dict[str, Any]:
    with core.LOCK:
        branches = deepcopy(core.BRANCHES)
        branches[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
        return {
            "active": core.ACTIVE_DESIGN,
            "branches": branches,
            "designs": deepcopy(core.DESIGNS),
        }


def _export_bundle(self: EngineeringProject) -> bytes:
    workspace = _workspace_snapshot()
    active_project = deepcopy(workspace["branches"][workspace["active"]])
    return project_bundle.export_bundle_bytes(active_project, workspace=workspace)


def _normalized_designs(branches: dict[str, dict[str, Any]], raw_designs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    designs: dict[str, dict[str, Any]] = {}
    for name in branches:
        raw = raw_designs.get(name)
        if isinstance(raw, dict):
            meta = deepcopy(raw)
        else:
            meta = {}
        meta.update({
            "name": name,
            "parent": meta.get("parent") if meta.get("parent") in branches else None,
            "status": str(meta.get("status") or "unverified"),
            "note": str(meta.get("note") or "Imported .focad branch"),
            "physical_verified": bool(meta.get("physical_verified", False)),
            "created_at": str(meta.get("created_at") or _now()),
            "updated_at": str(meta.get("updated_at") or _now()),
        })
        designs[name] = meta
    return designs


def _import_bundle(self: EngineeringProject, data: bytes) -> dict[str, Any]:
    restored = project_bundle.import_bundle_bytes(data)
    active_project = core.upgrade_project(restored["project"])
    workspace = restored.get("workspace")

    with core.LOCK:
        if isinstance(workspace, dict):
            active = str(workspace["active"])
            branches = {
                str(name): core.upgrade_project(branch)
                for name, branch in (workspace.get("branches") or {}).items()
                if isinstance(branch, dict)
            }
            if active not in branches:
                raise ValueError(".focad workspace active branch is missing")
            # project.json is deliberately authoritative for the active branch. This is
            # what lets ChatGPT or another engineering tool edit a portable design while
            # treating workspace.json as opaque branch-history state.
            branches[active] = active_project
            designs = _normalized_designs(branches, workspace.get("designs") or {})
            core.ACTIVE_DESIGN = active
            core.PROJECT.clear()
            core.PROJECT.update(deepcopy(branches[active]))
            core.BRANCHES.clear()
            core.BRANCHES.update(deepcopy(branches))
            core.DESIGNS.clear()
            core.DESIGNS.update(designs)
        else:
            # Legacy v1 .focad files have no branch workspace. Import them as the current
            # active branch rather than inventing historical branches that never existed.
            core.PROJECT.clear()
            core.PROJECT.update(active_project)
            core.BRANCHES.clear()
            core.BRANCHES[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
            current_meta = deepcopy(core.DESIGNS.get(core.ACTIVE_DESIGN) or {})
            core.DESIGNS.clear()
            core.DESIGNS[core.ACTIVE_DESIGN] = {
                "name": core.ACTIVE_DESIGN,
                "parent": None,
                "status": str(current_meta.get("status") or "unverified"),
                "note": "Imported legacy .focad design",
                "physical_verified": False,
                "created_at": str(current_meta.get("created_at") or _now()),
                "updated_at": _now(),
            }

        core.HISTORY.clear()
        core.HISTORY.append(deepcopy(core.PROJECT))
        core.REDO.clear()
        core.persist()

    self._mesh_cache.clear()
    restored["project"] = self.snapshot()
    restored["workspace_restored"] = isinstance(workspace, dict)
    restored["branch_count"] = len(core.BRANCHES)
    return restored


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    EngineeringProject.export_bundle = _export_bundle  # type: ignore[method-assign]
    EngineeringProject.import_bundle = _import_bundle  # type: ignore[method-assign]
    _INSTALLED = True
