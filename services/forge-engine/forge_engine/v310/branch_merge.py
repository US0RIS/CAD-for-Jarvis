from __future__ import annotations

"""Branch-scale semantic merge for ForgeCAD 3.1.

Merge is deliberately conservative: stable-ID engineering records are merged
three-way against a common ancestor, and conflicting edits fail closed. A merge
never writes directly onto a protected/working baseline; it creates a new branch.
"""

from copy import deepcopy
import json
from typing import Any

from ..v110 import core


_COLLECTIONS = (
    "objects",
    "joints",
    "loads",
    "constraints",
    "requirements",
    "bom",
    "connections",
    "simulations",
    "notebook",
    "fabrication_packages",
    "deployments",
    "inspections",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _branch_state(name: str) -> dict[str, Any]:
    if name == core.ACTIVE_DESIGN:
        return deepcopy(core.PROJECT)
    if name not in core.BRANCHES:
        raise KeyError(name)
    return deepcopy(core.BRANCHES[name])


def _ancestors(branch: str) -> list[str]:
    if branch not in core.DESIGNS:
        raise KeyError(branch)
    out = []
    seen: set[str] = set()
    current: str | None = branch
    while current and current not in seen:
        seen.add(current)
        out.append(current)
        meta = core.DESIGNS.get(current) or {}
        parent = meta.get("parent")
        current = str(parent) if parent else None
    return out


def common_ancestor(source: str, target: str) -> str | None:
    source_ancestors = set(_ancestors(source))
    for name in _ancestors(target):
        if name in source_ancestors:
            return name
    return None


def _stable_key(collection: str, item: dict[str, Any], index: int) -> str:
    if item.get("id"):
        return str(item["id"])
    if collection == "bom" and item.get("component_ref"):
        return f"component:{item['component_ref']}"
    if collection == "notebook":
        return f"note:{index}:{item.get('at') or item.get('title') or ''}"
    return f"index:{index}"


def _index(collection: str, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_stable_key(collection, row, index): deepcopy(row) for index, row in enumerate(rows)}


def _merge_value(base: Any, source: Any, target: Any, path: str, conflicts: list[dict[str, Any]]) -> Any:
    if _canonical(source) == _canonical(target):
        return deepcopy(source)
    if _canonical(source) == _canonical(base):
        return deepcopy(target)
    if _canonical(target) == _canonical(base):
        return deepcopy(source)
    if isinstance(base, dict) and isinstance(source, dict) and isinstance(target, dict):
        result: dict[str, Any] = {}
        for key in sorted(set(base) | set(source) | set(target)):
            result[key] = _merge_value(base.get(key), source.get(key), target.get(key), f"{path}.{key}", conflicts)
        return result
    conflicts.append({"path": path, "base": deepcopy(base), "source": deepcopy(source), "target": deepcopy(target)})
    return deepcopy(target)


def _merge_collection(
    collection: str,
    base_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base = _index(collection, base_rows)
    source = _index(collection, source_rows)
    target = _index(collection, target_rows)
    result: list[dict[str, Any]] = []
    for key in sorted(set(base) | set(source) | set(target)):
        b, s, t = base.get(key), source.get(key), target.get(key)
        if s is None and t is None:
            continue
        if b is None:
            if s is not None and t is not None and _canonical(s) != _canonical(t):
                conflicts.append({"path": f"{collection}[{key}]", "type": "concurrent_add", "base": None, "source": s, "target": t})
                result.append(deepcopy(t))
            else:
                result.append(deepcopy(s if s is not None else t))
            continue
        if s is None:
            if _canonical(t) == _canonical(b):
                continue
            conflicts.append({"path": f"{collection}[{key}]", "type": "delete_vs_modify", "base": b, "source": None, "target": t})
            result.append(deepcopy(t))
            continue
        if t is None:
            if _canonical(s) == _canonical(b):
                continue
            conflicts.append({"path": f"{collection}[{key}]", "type": "modify_vs_delete", "base": b, "source": s, "target": None})
            # Preserve target deletion until a human resolves the conflict.
            continue
        merged = _merge_value(b, s, t, f"{collection}[{key}]", conflicts)
        if isinstance(merged, dict):
            result.append(merged)
    return result


def merge_preflight(source: str, target: str) -> dict[str, Any]:
    ancestor = common_ancestor(source, target)
    if ancestor is None:
        return {"ok": False, "source": source, "target": target, "ancestor": None, "conflicts": [{"path": "branch", "type": "no_common_ancestor"}], "merged_project": None}
    base_project = _branch_state(ancestor)
    source_project = _branch_state(source)
    target_project = _branch_state(target)
    conflicts: list[dict[str, Any]] = []
    merged = deepcopy(target_project)
    # Merge scalar/project metadata excluding runtime timestamps/version/ledger.
    ignored = {"updated_at", "created_at", "version", "schema", "ledger", *_COLLECTIONS}
    for key in sorted((set(base_project) | set(source_project) | set(target_project)) - ignored):
        merged[key] = _merge_value(base_project.get(key), source_project.get(key), target_project.get(key), key, conflicts)
    for collection in _COLLECTIONS:
        merged[collection] = _merge_collection(
            collection,
            list(base_project.get(collection) or []),
            list(source_project.get(collection) or []),
            list(target_project.get(collection) or []),
            conflicts,
        )
    # Ledger is audit history, not mergeable semantic state. Retain target history and
    # record source lineage at apply time.
    merged["ledger"] = deepcopy(target_project.get("ledger") or [])
    merged["version"] = core.APP_VERSION
    merged["schema"] = max(4, int(merged.get("schema", 4) or 4))
    return {
        "ok": not conflicts,
        "source": source,
        "target": target,
        "ancestor": ancestor,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "merged_project": merged if not conflicts else None,
    }


def apply_merge(source: str, target: str, *, branch_name: str | None = None, actor: str = "human") -> dict[str, Any]:
    preflight = merge_preflight(source, target)
    if not preflight["ok"]:
        raise ValueError(f"Merge has {preflight['conflict_count']} unresolved conflict(s)")
    merged = deepcopy(preflight["merged_project"])
    with core.LOCK:
        core.switch_branch(target)
        merge_branch = core.create_branch(
            branch_name or f"merge-{source}-into-{target}",
            reason=f"Three-way semantic merge of {source} into {target} via {preflight['ancestor']}",
        )
        core.PROJECT.clear()
        core.PROJECT.update(merged)
        core.PROJECT.setdefault("ledger", []).append(
            {
                "at": core.now(),
                "actor": actor,
                "action": "semantic_merge",
                "reason": f"Merged {source} into {target}",
                "source_branch": source,
                "target_branch": target,
                "ancestor_branch": preflight["ancestor"],
                "design": core.ACTIVE_DESIGN,
            }
        )
        core.HISTORY.clear()
        core.HISTORY.append(deepcopy(core.PROJECT))
        core.REDO.clear()
        core.persist()
        return {
            "ok": True,
            "source": source,
            "target": target,
            "ancestor": preflight["ancestor"],
            "merge_branch": core.ACTIVE_DESIGN,
            "project": deepcopy(core.PROJECT),
        }
