from __future__ import annotations

"""ForgeCAD 3.0 application entrypoint.

3.0 keeps the complete 2.x engineering surface intact and adds the persistent
Physical World Model used by Jarvis to reason about stable physical identity,
hierarchy, pose, capabilities, interfaces, live state and provenance.
"""

from copy import deepcopy
from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import main as legacy
from . import main_v2 as v2
from .v110 import core
from .v300 import WORLD_MODEL_SCHEMA_VERSION
from .v300.capability_runtime import CapabilityBinding, CapabilityRuntime
from .v300.identity_resolution import resolve_entity_reference
from .v300.world_model import (
    PhysicalWorldStore,
    ROOT_WORLD_ID,
    WorldEntity,
    WorldRelation,
    sync_forgecad_project,
)


app = v2.app
WORLD = PhysicalWorldStore()
ACTIONS = CapabilityRuntime(WORLD)
_LAST_SYNC: dict[str, Any] = {"ok": False, "reason": "not_yet_synchronized"}


class ObservationRequest(BaseModel):
    entity_id: str
    key: str
    value: Any
    unit: str | None = None
    observed_at: str | None = None
    source: str = "sensor"
    source_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectSyncRequest(BaseModel):
    parent_id: str | None = None


class ActionPlanRequest(BaseModel):
    entity_id: str
    capability: str
    operation: str
    args: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "jarvis"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionConfirmRequest(BaseModel):
    confirmation_token: str
    confirmed_by: str = "human"


class ActionCancelRequest(BaseModel):
    cancelled_by: str = "human"


def _current_project_objects() -> list[dict[str, Any]]:
    with core.LOCK:
        return deepcopy(core.PROJECT.get("objects", []))


def _sync_current_project(*, parent_id: str | None = None, reason: str = "explicit") -> dict[str, Any]:
    global _LAST_SYNC
    try:
        result = sync_forgecad_project(
            WORLD,
            project_snapshot=legacy.PROJECT.snapshot(),
            raw_objects=_current_project_objects(),
            parent_id=parent_id,
        )
        _LAST_SYNC = {**result, "reason": reason}
        return deepcopy(_LAST_SYNC)
    except Exception as exc:
        _LAST_SYNC = {"ok": False, "reason": reason, "error": str(exc)}
        raise


def _action_runtime_summary() -> dict[str, Any]:
    snapshot = ACTIONS.snapshot()
    return {
        "binding_count": len(snapshot.bindings),
        "action_count": len(snapshot.actions),
        "registered_adapters": ACTIONS.adapters(),
        "awaiting_confirmation": sum(1 for row in snapshot.actions if row.status == "awaiting_confirmation"),
    }


@app.on_event("startup")
async def initialize_physical_world() -> None:
    try:
        _sync_current_project(reason="engine_startup")
    except Exception:
        # Engineering remains available even if world projection needs repair.
        # /v3/health surfaces the stale-sync condition explicitly.
        pass


@app.middleware("http")
async def synchronize_world_after_v2_mutation(request: Request, call_next):
    response = await call_next(request)
    if (
        response.status_code < 400
        and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/v2/")
    ):
        try:
            _sync_current_project(reason=f"{request.method.upper()} {request.url.path}")
        except Exception:
            # Do not turn a committed 2.x mutation into a misleading HTTP failure.
            # v3 health exposes the stale-sync state instead.
            pass
    return response


@app.get("/v3/health")
async def v3_health() -> dict[str, Any]:
    return {
        "ok": bool(_LAST_SYNC.get("ok")),
        "api_version": "3",
        "engine_version": legacy.__version__,
        "world_model_schema_version": WORLD_MODEL_SCHEMA_VERSION,
        "world": WORLD.summary(),
        "capability_runtime": _action_runtime_summary(),
        "project_sync": deepcopy(_LAST_SYNC),
    }


@app.get("/v3/world", dependencies=[Depends(legacy.require_session)])
async def world_snapshot(include_events: bool = True) -> dict[str, Any]:
    snapshot = WORLD.snapshot().model_dump(mode="json")
    if not include_events:
        snapshot["events"] = []
    return snapshot


@app.get("/v3/world/events", dependencies=[Depends(legacy.require_session)])
async def world_events(after_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    snapshot = WORLD.snapshot()
    events = list(snapshot.events)
    if after_id:
        indexes = [index for index, event in enumerate(events) if event.id == after_id]
        if not indexes:
            raise HTTPException(
                status_code=409,
                detail="Requested world event is no longer available; refresh the world snapshot",
            )
        events = events[indexes[-1] + 1 :]
    limit = max(1, min(1000, int(limit)))
    rows = events[:limit]
    return {
        "revision": snapshot.revision,
        "items": [row.model_dump(mode="json") for row in rows],
        "count": len(rows),
        "truncated": len(events) > limit,
        "last_event_id": rows[-1].id if rows else after_id,
    }


@app.get("/v3/world/entities", dependencies=[Depends(legacy.require_session)])
async def world_entities(
    kind: str | None = None,
    capability: str | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    rows = WORLD.entities(kind=kind, capability=capability, parent_id=parent_id)
    return {"items": [row.model_dump(mode="json") for row in rows], "count": len(rows)}


@app.get("/v3/world/entities/{entity_id:path}", dependencies=[Depends(legacy.require_session)])
async def world_entity(entity_id: str) -> dict[str, Any]:
    try:
        return WORLD.entity(entity_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown world entity: {entity_id}") from exc


@app.post("/v3/world/entities", dependencies=[Depends(legacy.require_session)])
async def create_world_entity(entity: WorldEntity) -> dict[str, Any]:
    try:
        return WORLD.upsert_entity(entity, source="api").model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown parent entity: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/v3/world/entities/{entity_id:path}", dependencies=[Depends(legacy.require_session)])
async def update_world_entity(entity_id: str, entity: WorldEntity) -> dict[str, Any]:
    candidate = entity.model_copy(deep=True)
    candidate.id = entity_id
    try:
        return WORLD.upsert_entity(candidate, source="api").model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown parent entity: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v3/world/entities/{entity_id:path}", dependencies=[Depends(legacy.require_session)])
async def delete_world_entity(entity_id: str, cascade: bool = False) -> dict[str, Any]:
    try:
        WORLD.delete_entity(entity_id, cascade=cascade, source="api")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown world entity: {entity_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "entity_id": entity_id, "cascade": cascade}


@app.get("/v3/world/relations", dependencies=[Depends(legacy.require_session)])
async def world_relations(entity_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
    rows = WORLD.relations(entity_id=entity_id, kind=kind)
    return {"items": [row.model_dump(mode="json") for row in rows], "count": len(rows)}


@app.post("/v3/world/relations", dependencies=[Depends(legacy.require_session)])
async def create_world_relation(relation: WorldRelation) -> dict[str, Any]:
    try:
        return WORLD.upsert_relation(relation, source="api").model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown relation endpoint: {exc.args[0]}") from exc


@app.post("/v3/world/observations", dependencies=[Depends(legacy.require_session)])
async def world_observation(request: ObservationRequest) -> dict[str, Any]:
    try:
        sample = WORLD.observe(
            entity_id=request.entity_id,
            key=request.key,
            value=request.value,
            unit=request.unit,
            observed_at=request.observed_at,
            source=request.source,
            source_id=request.source_id,
            confidence=request.confidence,
            metadata=request.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown world entity: {request.entity_id}") from exc
    return {
        "ok": True,
        "entity_id": request.entity_id,
        "key": request.key,
        "sample": sample.model_dump(mode="json"),
    }


@app.post("/v3/world/sync-project", dependencies=[Depends(legacy.require_session)])
async def sync_project_into_world(request: ProjectSyncRequest) -> dict[str, Any]:
    try:
        return _sync_current_project(parent_id=request.parent_id, reason="explicit_api_sync")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown parent entity: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v3/capabilities/bindings", dependencies=[Depends(legacy.require_session)])
async def capability_bindings(
    entity_id: str | None = None,
    capability: str | None = None,
    operation: str | None = None,
) -> dict[str, Any]:
    rows = ACTIONS.bindings(entity_id=entity_id, capability=capability, operation=operation)
    return {
        "items": [row.model_dump(mode="json") for row in rows],
        "count": len(rows),
        "registered_adapters": ACTIONS.adapters(),
    }


@app.post("/v3/capabilities/bindings", dependencies=[Depends(legacy.require_session)])
async def create_capability_binding(binding: CapabilityBinding) -> dict[str, Any]:
    try:
        return ACTIONS.bind(binding).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v3/capabilities/bindings/{binding_id}", dependencies=[Depends(legacy.require_session)])
async def delete_capability_binding(binding_id: str) -> dict[str, Any]:
    try:
        ACTIONS.unbind(binding_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown capability binding: {binding_id}") from exc
    return {"ok": True, "binding_id": binding_id}


@app.get("/v3/actions", dependencies=[Depends(legacy.require_session)])
async def capability_actions(entity_id: str | None = None, status: str | None = None) -> dict[str, Any]:
    rows = ACTIONS.actions(entity_id=entity_id, status=status)
    return {"items": [row.model_dump(mode="json") for row in rows], "count": len(rows)}


@app.post("/v3/actions/plan", dependencies=[Depends(legacy.require_session)])
async def plan_capability_action(request: ActionPlanRequest) -> dict[str, Any]:
    try:
        action, confirmation_token = ACTIONS.plan(
            entity_id=request.entity_id,
            capability=request.capability,
            operation=request.operation,
            args=request.args,
            requested_by=request.requested_by,
            metadata=request.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "action": action.model_dump(mode="json"),
        # Confirmation tokens are returned only at plan time. Only a hash remains
        # in memory and confirmation-dependent actions expire across engine restart.
        "confirmation_token": confirmation_token,
    }


@app.post("/v3/actions/{action_id}/confirm", dependencies=[Depends(legacy.require_session)])
async def confirm_capability_action(action_id: str, request: ActionConfirmRequest) -> dict[str, Any]:
    try:
        action = ACTIONS.confirm(action_id, request.confirmation_token, confirmed_by=request.confirmed_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown capability action: {action_id}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return action.model_dump(mode="json")


@app.post("/v3/actions/{action_id}/execute", dependencies=[Depends(legacy.require_session)])
async def execute_capability_action(action_id: str) -> dict[str, Any]:
    try:
        action = await ACTIONS.execute(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown capability action: {action_id}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return action.model_dump(mode="json")


@app.post("/v3/actions/{action_id}/cancel", dependencies=[Depends(legacy.require_session)])
async def cancel_capability_action(action_id: str, request: ActionCancelRequest) -> dict[str, Any]:
    try:
        action = ACTIONS.cancel(action_id, cancelled_by=request.cancelled_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown capability action: {action_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return action.model_dump(mode="json")


@app.get("/v3/jarvis/resolve", dependencies=[Depends(legacy.require_session)])
async def resolve_jarvis_reference(
    q: str,
    kind: str | None = None,
    capability: str | None = None,
    max_candidates: int = 10,
) -> dict[str, Any]:
    resolution = resolve_entity_reference(
        WORLD,
        q,
        kind=kind,
        capability=capability,
        max_candidates=max(1, min(50, int(max_candidates))),
    )
    return resolution.model_dump(mode="json")


@app.get("/v3/jarvis/context", dependencies=[Depends(legacy.require_session)])
async def jarvis_world_context(
    kind: str | None = None,
    capability: str | None = None,
    max_entities: int = 200,
) -> dict[str, Any]:
    max_entities = max(1, min(1000, int(max_entities)))
    entities = WORLD.entities(kind=kind, capability=capability)[:max_entities]
    entity_ids = {row.id for row in entities}
    relations = [
        row for row in WORLD.relations()
        if row.a_id in entity_ids or row.b_id in entity_ids
    ]
    compact_entities = []
    for entity in entities:
        compact_entities.append(
            {
                "id": entity.id,
                "name": entity.name,
                "kind": entity.kind,
                "parent_id": entity.parent_id,
                "pose": entity.pose.model_dump(mode="json"),
                "capabilities": [row.name for row in entity.capabilities],
                "interfaces": [
                    {"id": row.id, "kind": row.kind, "direction": row.direction, "protocol": row.protocol}
                    for row in entity.interfaces
                ],
                "live_state": {
                    key: {
                        "value": sample.value,
                        "unit": sample.unit,
                        "observed_at": sample.observed_at,
                        "source": sample.source,
                        "source_id": sample.source_id,
                        "confidence": sample.confidence,
                    }
                    for key, sample in entity.live_state.items()
                },
                "source_links": deepcopy(entity.source_links),
                "confidence": entity.confidence,
            }
        )
    relevant_bindings = [
        row
        for row in ACTIONS.bindings()
        if row.entity_id in entity_ids
    ]
    return {
        "world": WORLD.summary(),
        "root_id": ROOT_WORLD_ID,
        "project_sync": deepcopy(_LAST_SYNC),
        "capability_runtime": _action_runtime_summary(),
        "entities": compact_entities,
        "relations": [
            {
                "id": row.id,
                "kind": row.kind,
                "a_id": row.a_id,
                "b_id": row.b_id,
                "a_interface_id": row.a_interface_id,
                "b_interface_id": row.b_interface_id,
            }
            for row in relations
        ],
        "capability_bindings": [
            {
                "id": row.id,
                "entity_id": row.entity_id,
                "capability": row.capability,
                "operation": row.operation,
                "adapter_id": row.adapter_id,
                "risk": row.risk,
                "requires_confirmation": row.requires_confirmation,
                "enabled": row.enabled,
            }
            for row in relevant_bindings
        ],
        "truncated": len(entities) >= max_entities,
    }
