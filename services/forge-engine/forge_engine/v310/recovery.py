from __future__ import annotations

"""Transactional recovery checkpoints for ForgeCAD 3.1.

Canonical state already persists atomically. Checkpoints add user-visible recovery
points that can survive bad edits/imports and restore the complete multi-branch
workspace without depending on derived graph/evidence caches.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from ..v110 import core


CHECKPOINT_SCHEMA = 1
DEFAULT_RETENTION = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    path = core.DATA_DIR / "recovery" / "v31"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:80] or "checkpoint"


def _workspace_payload() -> dict[str, Any]:
    with core.LOCK:
        core.BRANCHES[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
        return {
            "schema": CHECKPOINT_SCHEMA,
            "version": core.APP_VERSION,
            "active": core.ACTIVE_DESIGN,
            "project": deepcopy(core.PROJECT),
            "branches": deepcopy(core.BRANCHES),
            "designs": deepcopy(core.DESIGNS),
            "created_at": _now(),
        }


def _digest(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def create_checkpoint(label: str = "autosave", *, reason: str = "", actor: str = "forgecad", retention: int = DEFAULT_RETENTION) -> dict[str, Any]:
    payload = _workspace_payload()
    checkpoint_id = f"cp-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    payload.update({"id": checkpoint_id, "label": label, "reason": reason, "actor": actor})
    payload["sha256"] = _digest({k: v for k, v in payload.items() if k != "sha256"})
    path = _root() / f"{checkpoint_id}-{_safe(label)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    prune_checkpoints(retention=max(2, int(retention)))
    return checkpoint_metadata(payload, path)


def checkpoint_metadata(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    project = payload.get("project") or {}
    return {
        "id": payload.get("id"),
        "label": payload.get("label"),
        "reason": payload.get("reason"),
        "actor": payload.get("actor"),
        "created_at": payload.get("created_at"),
        "version": payload.get("version"),
        "active_branch": payload.get("active"),
        "project_name": project.get("name"),
        "object_count": len(project.get("objects", [])),
        "branch_count": len(payload.get("branches") or {}),
        "sha256": payload.get("sha256"),
        "bytes": path.stat().st_size if path and path.exists() else None,
    }


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema", 0)) != CHECKPOINT_SCHEMA:
        raise ValueError("Unsupported recovery checkpoint schema")
    expected = str(payload.get("sha256") or "")
    actual = _digest({k: v for k, v in payload.items() if k != "sha256"})
    if not expected or expected != actual:
        raise ValueError("Recovery checkpoint integrity check failed")
    if not isinstance(payload.get("project"), dict) or not isinstance(payload.get("branches"), dict) or not isinstance(payload.get("designs"), dict):
        raise ValueError("Recovery checkpoint is malformed")
    return payload


def _path_for_id(checkpoint_id: str) -> Path:
    matches = sorted(_root().glob(f"{_safe(checkpoint_id)}-*.json"))
    if not matches:
        # IDs themselves contain no unsafe chars, but support exact filename lookup
        # for future schema revisions that may omit the label suffix.
        exact = _root() / f"{_safe(checkpoint_id)}.json"
        if exact.exists():
            return exact
        raise KeyError(checkpoint_id)
    return matches[-1]


def list_checkpoints(limit: int = 50) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(_root().glob("cp-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = _read(path)
            rows.append(checkpoint_metadata(payload, path))
        except Exception as exc:
            rows.append({"id": path.stem, "label": "corrupt", "error": str(exc), "bytes": path.stat().st_size})
        if len(rows) >= max(1, min(500, int(limit))):
            break
    return rows


def prune_checkpoints(retention: int = DEFAULT_RETENTION) -> int:
    retention = max(2, int(retention))
    paths = sorted(_root().glob("cp-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in paths[retention:]:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def restore_checkpoint(checkpoint_id: str, *, actor: str = "human", create_safety_checkpoint: bool = True) -> dict[str, Any]:
    path = _path_for_id(checkpoint_id)
    payload = _read(path)
    safety = None
    if create_safety_checkpoint:
        safety = create_checkpoint("pre-restore", reason=f"Before restoring {checkpoint_id}", actor="forgecad")
    active = str(payload.get("active") or "main")
    project = core.upgrade_project(deepcopy(payload["project"]))
    branches = {
        str(name): core.upgrade_project(deepcopy(branch))
        for name, branch in payload["branches"].items()
        if isinstance(branch, dict)
    }
    designs = {str(name): deepcopy(meta) for name, meta in payload["designs"].items() if isinstance(meta, dict)}
    if active not in branches:
        branches[active] = deepcopy(project)
    if active not in designs:
        designs[active] = {"name": active, "parent": None, "status": "unverified", "note": "Recovered checkpoint", "physical_verified": False, "created_at": _now(), "updated_at": _now()}
    with core.LOCK:
        core.PROJECT.clear(); core.PROJECT.update(project)
        core.BRANCHES.clear(); core.BRANCHES.update(branches)
        core.DESIGNS.clear(); core.DESIGNS.update(designs)
        core.ACTIVE_DESIGN = active
        core.HISTORY.clear(); core.HISTORY.append(deepcopy(project))
        core.REDO.clear()
        core.PROJECT.setdefault("ledger", []).append({
            "at": core.now(),
            "actor": actor,
            "action": "restore_checkpoint",
            "reason": f"Restored recovery checkpoint {checkpoint_id}",
            "checkpoint_id": checkpoint_id,
            "design": active,
        })
        core.persist()
    return {
        "ok": True,
        "checkpoint": checkpoint_metadata(payload, path),
        "safety_checkpoint": safety,
        "active_branch": core.ACTIVE_DESIGN,
        "project": deepcopy(core.PROJECT),
    }
