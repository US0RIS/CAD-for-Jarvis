from __future__ import annotations

"""Execution-time enrichment for ForgeCAD 2.0 agent plans.

The 2.0 planner may create a component and then need to position, mate, wire, or program
that newly-created object later in the same plan. Object UUIDs do not exist until Forge
Engine executes the creation command, so plans support symbolic handles:

    {"op":"add_component","as":"door_sensor","args":{"component_id":"..."}}
    {"op":"connect_interfaces","args":{"a_id":"$door_sensor", ...}}

Forge Engine resolves handles transactionally as it executes the typed command stream.
The model never invents UUIDs. This module also persists the architecture and its
requirements into canonical project state so they survive .focad export/import.
"""

from copy import deepcopy
from typing import Any

from ..engineering_state import EngineeringProject
from ..v110 import core

_INSTALLED = False


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _requirement_command(requirement: dict[str, Any]) -> dict[str, Any] | None:
    statement = str(requirement.get("statement") or "").strip()
    if not statement:
        return None
    args: dict[str, Any] = {
        "statement": statement,
        "priority": str(requirement.get("priority") or "must"),
        "verification": str(requirement.get("verification") or "Verify against the completed design."),
        "source": "forgecad-v2-architecture",
    }
    if requirement.get("metric") is not None and requirement.get("target") is not None:
        args["metric"] = str(requirement.get("metric"))
        args["op"] = str(requirement.get("op") or "<=")
        args["target"] = requirement.get("target")
    return {"op": "set_requirement", "args": args}


def _resolve(value: Any, handles: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name not in handles:
            raise ValueError(f"Unresolved ForgeCAD plan handle: {value}")
        return handles[name]
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            name = str(value["$ref"])
            if name not in handles:
                raise ValueError(f"Unresolved ForgeCAD plan handle: ${name}")
            return handles[name]
        return {key: _resolve(item, handles) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, handles) for item in value]
    return value


def _architecture_note_exists(architecture: dict[str, Any]) -> bool:
    goal = _key(architecture.get("goal"))
    if not goal:
        return False
    for note in core.PROJECT.get("notebook", []):
        if not isinstance(note, dict) or note.get("kind") != "design_architecture":
            continue
        existing = note.get("architecture") if isinstance(note.get("architecture"), dict) else {}
        if _key(existing.get("goal")) == goal:
            return True
    return False


def _commands_with_architecture(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    architecture = plan.get("architecture") if isinstance(plan, dict) else None
    if not isinstance(architecture, dict):
        return list(deepcopy(plan.get("commands") or [])), 0

    existing_requirements = {
        _key(item.get("statement") or item.get("description") or item.get("text"))
        for item in core.PROJECT.get("requirements", [])
        if isinstance(item, dict)
    }
    prefix: list[dict[str, Any]] = []
    if not _architecture_note_exists(architecture):
        prefix.append({
            "op": "add_note",
            "args": {
                "kind": "design_architecture",
                "title": str(architecture.get("goal") or "ForgeCAD 2.0 design architecture"),
                "architecture": deepcopy(architecture),
                "source": "forgecad-v2-design-intelligence",
            },
        })
    requirements_added = 0
    for requirement in architecture.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        command = _requirement_command(requirement)
        if command is None:
            continue
        statement_key = _key(command["args"]["statement"])
        if statement_key and statement_key not in existing_requirements:
            existing_requirements.add(statement_key)
            prefix.append(command)
            requirements_added += 1
    return prefix + list(deepcopy(plan.get("commands") or [])), requirements_added


def _apply_v2_plan(self: EngineeringProject, plan: dict[str, Any], text: str) -> dict[str, Any]:
    commands, requirements_added = _commands_with_architecture(plan)
    handles: dict[str, str] = {}
    applied: list[dict[str, Any]] = []

    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            raise ValueError(f"Invalid ForgeCAD plan command at index {index}")
        op = str(command.get("op") or "")
        if not op:
            raise ValueError(f"ForgeCAD plan command {index} has no operation")
        args = _resolve(deepcopy(command.get("args") or {}), handles)
        before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
        result = core.execute(op, args, actor="forge-agent", reason=text)
        after_objects = core.PROJECT.get("objects", [])
        created = [obj for obj in after_objects if str(obj.get("id")) not in before]

        handle = str(command.get("as") or command.get("handle") or "").strip()
        if handle:
            if op not in {"add", "add_component"}:
                raise ValueError(f"Plan handle {handle!r} can only be assigned by add/add_component")
            if len(created) != 1:
                raise ValueError(f"Plan handle {handle!r} expected exactly one created object, got {len(created)}")
            handles[handle] = str(created[0]["id"])

        applied.append({
            "op": op,
            "ok": bool(result.get("ok")),
            **({"handle": handle, "object_id": handles[handle]} if handle else {}),
        })

    architecture = plan.get("architecture") if isinstance(plan, dict) and isinstance(plan.get("architecture"), dict) else None
    return {
        "branch": core.ACTIVE_DESIGN,
        "applied": applied,
        "handles": handles,
        "project": self.snapshot(),
        "requirements_added": requirements_added,
        **({"architecture": deepcopy(architecture)} if architecture is not None else {}),
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    EngineeringProject.apply_agent_plan = _apply_v2_plan
    _INSTALLED = True
