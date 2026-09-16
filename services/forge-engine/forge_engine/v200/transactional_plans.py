from __future__ import annotations

"""Atomic application of ForgeCAD 2.0 agent command streams.

A design agent often emits a dependent sequence: create a body, dimension it, place it,
attach hardware, then add loads and requirements. Persisting the first half of that
sequence when a later command is invalid leaves a project in a state the user never
approved. This layer makes the whole typed plan one transaction.

The transaction covers canonical in-memory/on-disk project, branches, branch metadata,
undo/redo history and the active branch. It intentionally does not attempt to roll back
external side effects outside ForgeCAD's project store; current agent operations do not
perform direct printer/network actions.
"""

from copy import deepcopy
import json
from typing import Any, Callable

from ..engineering_state import EngineeringProject
from ..v110 import core


_INSTALLED = False
_ORIGINAL_APPLY_AGENT_PLAN: Callable[..., dict[str, Any]] | None = None


def _capture() -> dict[str, Any]:
    return {
        "active": core.ACTIVE_DESIGN,
        "project": deepcopy(core.PROJECT),
        "branches": deepcopy(core.BRANCHES),
        "designs": deepcopy(core.DESIGNS),
        "history": deepcopy(core.HISTORY),
        "redo": deepcopy(core.REDO),
    }


def _persist_exact(state: dict[str, Any]) -> None:
    # `core.persist()` intentionally updates the project timestamp. A rollback should be
    # observationally identical to the pre-transaction state, including revision/time,
    # so write the already-captured serialized state without touching timestamps.
    core.PROJECTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": state["active"],
        "project": state["project"],
        "branches": state["branches"],
        "designs": state["designs"],
    }
    tmp = core.STATE_PATH.with_suffix(".transaction-rollback.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(core.STATE_PATH)


def _restore(state: dict[str, Any], project: EngineeringProject) -> None:
    core.ACTIVE_DESIGN = str(state["active"])
    core.PROJECT.clear()
    core.PROJECT.update(deepcopy(state["project"]))
    core.BRANCHES.clear()
    core.BRANCHES.update(deepcopy(state["branches"]))
    core.DESIGNS.clear()
    core.DESIGNS.update(deepcopy(state["designs"]))
    core.HISTORY.clear()
    core.HISTORY.extend(deepcopy(state["history"]))
    core.REDO.clear()
    core.REDO.extend(deepcopy(state["redo"]))
    project._mesh_cache.clear()
    _persist_exact(state)


def _apply_agent_plan(self: EngineeringProject, plan: dict[str, Any], text: str) -> dict[str, Any]:
    assert _ORIGINAL_APPLY_AGENT_PLAN is not None
    with core.LOCK:
        before = _capture()
        try:
            result = _ORIGINAL_APPLY_AGENT_PLAN(self, plan, text)
        except Exception:
            _restore(before, self)
            raise
        result["transaction"] = {
            "atomic": True,
            "rolled_back": False,
            "command_count": len(plan.get("commands") or []) if isinstance(plan, dict) else 0,
            "source_branch": before["active"],
            "result_branch": core.ACTIVE_DESIGN,
        }
        return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_APPLY_AGENT_PLAN
    if _INSTALLED:
        return
    _ORIGINAL_APPLY_AGENT_PLAN = EngineeringProject.apply_agent_plan
    EngineeringProject.apply_agent_plan = _apply_agent_plan  # type: ignore[method-assign]
    _INSTALLED = True
