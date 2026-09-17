from __future__ import annotations

from copy import deepcopy
from typing import Any

from .world_model import PhysicalWorldStore, ROOT_WORLD_ID, WorldEntity


MAX_PLANNER_WORLD_ENTITIES = 120
MAX_ENTITY_PROVENANCE = 6


def _compact_provenance(entity: WorldEntity) -> list[dict[str, Any]]:
    rows = entity.provenance[-MAX_ENTITY_PROVENANCE:]
    return [
        {
            "source": row.source,
            "source_id": row.source_id,
            "observed_at": row.observed_at,
            "confidence": row.confidence,
            "authoritative": row.authoritative,
            "note": row.note,
        }
        for row in rows
    ]


def _compact_entity(entity: WorldEntity) -> dict[str, Any]:
    forgecad_object_id = entity.source_links.get("forgecad_object_id")
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "kind": entity.kind,
        "parent_id": entity.parent_id,
        "pose": entity.pose.model_dump(mode="json"),
        "capabilities": [
            {
                "name": row.name,
                "mode": row.mode,
                "constraints": deepcopy(row.constraints),
            }
            for row in entity.capabilities
        ],
        "interfaces": [
            {
                "id": row.id,
                "kind": row.kind,
                "direction": row.direction,
                "protocol": row.protocol,
            }
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
        "source_links": dict(entity.source_links),
        "provenance": _compact_provenance(entity),
        "confidence": entity.confidence,
        # This is the only world -> design authority bridge the planner may use.
        # entity_id itself is never a CAD object identifier.
        "design_addressable": bool(forgecad_object_id),
        "forgecad_object_id": forgecad_object_id,
    }


def build_physical_world_planner_context(
    store: PhysicalWorldStore,
    request_text: str,
    *,
    max_entities: int = MAX_PLANNER_WORLD_ENTITIES,
) -> dict[str, Any]:
    """Build deterministic physical-world context for ForgeCAD's engineering agent.

    The context deliberately exposes stable physical identity and current observations
    without granting world IDs authority over CAD state. A world entity becomes
    design-addressable only when the canonical world projection contains an explicit
    ``source_links.forgecad_object_id`` mapping.
    """

    max_entities = max(1, min(500, int(max_entities)))
    snapshot = store.snapshot()
    entities = [row for row in snapshot.entities if row.id != ROOT_WORLD_ID]
    entities.sort(key=lambda row: (row.kind, row.name.lower(), row.id))
    selected = entities[:max_entities]
    selected_ids = {row.id for row in selected}
    relations = [
        row
        for row in snapshot.relations
        if row.a_id in selected_ids or row.b_id in selected_ids
    ]
    relations.sort(key=lambda row: (row.kind, row.id))

    design_links = {
        row.id: row.source_links["forgecad_object_id"]
        for row in selected
        if row.source_links.get("forgecad_object_id")
    }

    return {
        "schema_version": snapshot.schema_version,
        "revision": snapshot.revision,
        "request": request_text,
        "entity_count": len(snapshot.entities),
        "relation_count": len(snapshot.relations),
        "entities": [_compact_entity(row) for row in selected],
        "relations": [
            {
                "id": row.id,
                "kind": row.kind,
                "a_id": row.a_id,
                "b_id": row.b_id,
                "a_interface_id": row.a_interface_id,
                "b_interface_id": row.b_interface_id,
                "metadata": deepcopy(row.metadata),
            }
            for row in relations
        ],
        "design_links": design_links,
        "truncated": len(entities) > len(selected),
        "authority_rules": [
            "World entity_id values identify physical-world entities, not CAD objects.",
            "Only source_links.forgecad_object_id may be used as a CAD object_id.",
            "Observed live_state is time-stamped evidence and must not silently become a design requirement.",
            "Non-authoritative or low-confidence provenance must remain qualified as uncertain.",
            "Ambiguous physical identity must be resolved deterministically before acting.",
        ],
    }


def install_world_aware_planner(store: PhysicalWorldStore) -> None:
    """Extend the existing 2.x planner/reply context with the canonical v3 world.

    main_v2's qwen_plan/qwen_reply functions resolve ``_planner_context`` and
    ``_planner_system`` from their module globals at call time, so replacing those two
    functions upgrades both planning and analysis without forking the mature 2.x agent
    loop. Re-installation only swaps the backing store; wrappers are never stacked.
    """

    from .. import main_v2 as v2

    holder = getattr(v2, "_v300_world_store_holder", None)
    if isinstance(holder, dict):
        holder["store"] = store
        return

    original_context = v2._planner_context
    original_system = v2._planner_system
    store_holder: dict[str, PhysicalWorldStore] = {"store": store}

    def planner_context(text: str, architecture: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
        context = original_context(text, architecture, project)
        context["physical_world"] = build_physical_world_planner_context(store_holder["store"], text)
        return context

    def planner_system() -> str:
        return original_system() + (
            " ForgeCAD 3.0 also supplies physical_world context. Physical-world entity_id values are stable real-world identity, NOT CAD object IDs. "
            "Never place an entity_id into object_id, a_id, b_id, parent_id, child_id, or any other design-operation field. "
            "A physical-world entity may be addressed by a CAD operation only when its physical_world entry has design_addressable=true and an explicit forgecad_object_id; use exactly that forgecad_object_id. "
            "Treat live_state as time-stamped observation evidence rather than an immutable design fact. Preserve source, timestamp, confidence and provenance distinctions. "
            "If the request refers to a physical entity ambiguously, do not guess which entity is meant and do not convert a fuzzy candidate into an operation. "
            "Physical capability execution is separate from CAD planning and must go through ForgeCAD 3.0's typed capability/action runtime and confirmation policy."
        )

    v2._planner_context = planner_context
    v2._planner_system = planner_system
    v2._v300_world_store_holder = store_holder
    v2._v300_original_planner_context = original_context
    v2._v300_original_planner_system = original_system
