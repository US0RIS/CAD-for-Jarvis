from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from threading import RLock
from typing import Any
import uuid

from pydantic import BaseModel, Field

from . import WORLD_MODEL_SCHEMA_VERSION


ROOT_WORLD_ID = "world:local"
_MAX_EVENTS = 1000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _world_path() -> Path:
    configured = os.environ.get("FORGECAD_DATA_DIR", "").strip()
    if configured:
        root = Path(configured)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ForgeCAD"
    elif __import__("sys").platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "ForgeCAD"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "forgecad"
    root.mkdir(parents=True, exist_ok=True)
    return root / "physical-world-v1.json"


class WorldPose(BaseModel):
    frame_id: str = ROOT_WORLD_ID
    position_m: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    orientation_xyzw: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0], min_length=4, max_length=4)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ProvenanceRecord(BaseModel):
    source: str
    source_id: str | None = None
    observed_at: str = Field(default_factory=now_iso)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    authoritative: bool = False
    note: str | None = None


class WorldCapability(BaseModel):
    name: str
    mode: str = "unknown"
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldInterface(BaseModel):
    id: str
    kind: str = "unknown"
    direction: str | None = None
    protocol: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldStateValue(BaseModel):
    value: Any
    unit: str | None = None
    observed_at: str = Field(default_factory=now_iso)
    source: str = "unknown"
    source_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldEntity(BaseModel):
    id: str
    name: str
    kind: str
    parent_id: str | None = ROOT_WORLD_ID
    pose: WorldPose = Field(default_factory=WorldPose)
    capabilities: list[WorldCapability] = Field(default_factory=list)
    interfaces: list[WorldInterface] = Field(default_factory=list)
    live_state: dict[str, WorldStateValue] = Field(default_factory=dict)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    source_links: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class WorldRelation(BaseModel):
    id: str
    kind: str
    a_id: str
    b_id: str
    a_interface_id: str | None = None
    b_interface_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class WorldEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    at: str = Field(default_factory=now_iso)
    type: str
    entity_id: str | None = None
    relation_id: str | None = None
    source: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)


class WorldSnapshot(BaseModel):
    schema_version: int = WORLD_MODEL_SCHEMA_VERSION
    revision: int = 0
    root_id: str = ROOT_WORLD_ID
    entities: list[WorldEntity] = Field(default_factory=list)
    relations: list[WorldRelation] = Field(default_factory=list)
    events: list[WorldEvent] = Field(default_factory=list)


class PhysicalWorldStore:
    """Persistent, deterministic physical-world graph.

    ForgeCAD design entities, sensor observations, human declarations and Jarvis
    inferences coexist here without collapsing into a single ambiguous truth source.
    """

    def __init__(self, path: str | Path | None = None, *, autosave: bool = True) -> None:
        self.path = Path(path) if path is not None else _world_path()
        self.autosave = autosave
        self._lock = RLock()
        self._revision = 0
        self._entities: dict[str, WorldEntity] = {}
        self._relations: dict[str, WorldRelation] = {}
        self._events: list[WorldEvent] = []
        self._load()
        self._ensure_root()

    def _ensure_root(self) -> None:
        if ROOT_WORLD_ID in self._entities:
            return
        root = WorldEntity(
            id=ROOT_WORLD_ID,
            name="Local physical world",
            kind="world",
            parent_id=None,
            pose=WorldPose(frame_id=ROOT_WORLD_ID),
            capabilities=[WorldCapability(name="engineering.inspect", mode="engineer")],
            provenance=[ProvenanceRecord(source="system", source_id="forgecad", authoritative=True)],
            source_links={"forgecad": "world-root"},
        )
        self._entities[root.id] = root
        self._touch("entity.created", entity_id=root.id, source="system")

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            snapshot = WorldSnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        self._revision = int(snapshot.revision)
        self._entities = {entity.id: entity for entity in snapshot.entities}
        self._relations = {relation.id: relation for relation in snapshot.relations}
        self._events = list(snapshot.events)[-_MAX_EVENTS:]

    def _persist(self) -> None:
        if not self.autosave:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot().model_dump_json(indent=2)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(self.path)

    def _touch(
        self,
        event_type: str,
        *,
        entity_id: str | None = None,
        relation_id: str | None = None,
        source: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._revision += 1
        self._events.append(
            WorldEvent(
                type=event_type,
                entity_id=entity_id,
                relation_id=relation_id,
                source=source,
                payload=payload or {},
            )
        )
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return WorldSnapshot(
                revision=self._revision,
                entities=[entity.model_copy(deep=True) for entity in self._entities.values()],
                relations=[relation.model_copy(deep=True) for relation in self._relations.values()],
                events=[event.model_copy(deep=True) for event in self._events],
            )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            by_kind: dict[str, int] = {}
            by_source: dict[str, int] = {}
            for entity in self._entities.values():
                by_kind[entity.kind] = by_kind.get(entity.kind, 0) + 1
                for record in entity.provenance:
                    by_source[record.source] = by_source.get(record.source, 0) + 1
            return {
                "schema_version": WORLD_MODEL_SCHEMA_VERSION,
                "revision": self._revision,
                "entity_count": len(self._entities),
                "relation_count": len(self._relations),
                "event_count": len(self._events),
                "by_kind": dict(sorted(by_kind.items())),
                "by_source": dict(sorted(by_source.items())),
            }

    def entity(self, entity_id: str) -> WorldEntity:
        with self._lock:
            if entity_id not in self._entities:
                raise KeyError(entity_id)
            return self._entities[entity_id].model_copy(deep=True)

    def entities(
        self,
        *,
        kind: str | None = None,
        capability: str | None = None,
        parent_id: str | None = None,
    ) -> list[WorldEntity]:
        with self._lock:
            rows = list(self._entities.values())
            if kind is not None:
                rows = [row for row in rows if row.kind == kind]
            if parent_id is not None:
                rows = [row for row in rows if row.parent_id == parent_id]
            if capability is not None:
                rows = [row for row in rows if any(item.name == capability for item in row.capabilities)]
            return [row.model_copy(deep=True) for row in rows]

    def relations(self, *, entity_id: str | None = None, kind: str | None = None) -> list[WorldRelation]:
        with self._lock:
            rows = list(self._relations.values())
            if entity_id is not None:
                rows = [row for row in rows if row.a_id == entity_id or row.b_id == entity_id]
            if kind is not None:
                rows = [row for row in rows if row.kind == kind]
            return [row.model_copy(deep=True) for row in rows]

    def _assert_valid_parent(self, entity_id: str, parent_id: str | None) -> None:
        if parent_id is None:
            if entity_id != ROOT_WORLD_ID:
                raise ValueError("Only the root world entity may have no parent")
            return
        if parent_id not in self._entities:
            raise KeyError(parent_id)
        if parent_id == entity_id:
            raise ValueError("Entity cannot parent itself")
        cursor = parent_id
        visited: set[str] = set()
        while cursor is not None:
            if cursor == entity_id:
                raise ValueError("World hierarchy cycle detected")
            if cursor in visited:
                raise ValueError("Existing world hierarchy contains a cycle")
            visited.add(cursor)
            parent = self._entities.get(cursor)
            cursor = parent.parent_id if parent is not None else None

    def upsert_entity(self, entity: WorldEntity, *, source: str = "system", preserve_live_state: bool = True) -> WorldEntity:
        with self._lock:
            self._assert_valid_parent(entity.id, entity.parent_id)
            existing = self._entities.get(entity.id)
            candidate = entity.model_copy(deep=True)
            if existing is not None:
                candidate.created_at = existing.created_at
                if preserve_live_state and not candidate.live_state:
                    candidate.live_state = deepcopy(existing.live_state)
                candidate.updated_at = now_iso()
                event_type = "entity.updated"
            else:
                candidate.created_at = candidate.created_at or now_iso()
                candidate.updated_at = now_iso()
                event_type = "entity.created"
            candidate.confidence = _clamp_confidence(candidate.confidence)
            self._entities[candidate.id] = candidate
            self._touch(event_type, entity_id=candidate.id, source=source)
            self._persist()
            return candidate.model_copy(deep=True)

    def delete_entity(self, entity_id: str, *, cascade: bool = False, source: str = "system") -> None:
        with self._lock:
            if entity_id == ROOT_WORLD_ID:
                raise ValueError("Root world entity cannot be deleted")
            if entity_id not in self._entities:
                raise KeyError(entity_id)
            children = [row.id for row in self._entities.values() if row.parent_id == entity_id]
            if children and not cascade:
                raise ValueError("Entity has children; cascade is required")
            targets: set[str] = {entity_id}
            if cascade:
                frontier = list(children)
                while frontier:
                    child_id = frontier.pop()
                    if child_id in targets:
                        continue
                    targets.add(child_id)
                    frontier.extend(row.id for row in self._entities.values() if row.parent_id == child_id)
            for target in targets:
                self._entities.pop(target, None)
            stale_relations = [rid for rid, row in self._relations.items() if row.a_id in targets or row.b_id in targets]
            for rid in stale_relations:
                self._relations.pop(rid, None)
            self._touch("entity.deleted", entity_id=entity_id, source=source, payload={"cascade_count": len(targets)})
            self._persist()

    def upsert_relation(self, relation: WorldRelation, *, source: str = "system") -> WorldRelation:
        with self._lock:
            if relation.a_id not in self._entities:
                raise KeyError(relation.a_id)
            if relation.b_id not in self._entities:
                raise KeyError(relation.b_id)
            existing = self._relations.get(relation.id)
            candidate = relation.model_copy(deep=True)
            if existing is not None:
                candidate.created_at = existing.created_at
                candidate.updated_at = now_iso()
                event_type = "relation.updated"
            else:
                candidate.updated_at = now_iso()
                event_type = "relation.created"
            self._relations[candidate.id] = candidate
            self._touch(event_type, relation_id=candidate.id, source=source)
            self._persist()
            return candidate.model_copy(deep=True)

    def delete_relation(self, relation_id: str, *, source: str = "system") -> None:
        with self._lock:
            if relation_id not in self._relations:
                raise KeyError(relation_id)
            self._relations.pop(relation_id)
            self._touch("relation.deleted", relation_id=relation_id, source=source)
            self._persist()

    def observe(
        self,
        *,
        entity_id: str,
        key: str,
        value: Any,
        unit: str | None = None,
        observed_at: str | None = None,
        source: str = "sensor",
        source_id: str | None = None,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> WorldStateValue:
        with self._lock:
            if entity_id not in self._entities:
                raise KeyError(entity_id)
            sample = WorldStateValue(
                value=value,
                unit=unit,
                observed_at=observed_at or now_iso(),
                source=source,
                source_id=source_id,
                confidence=_clamp_confidence(confidence),
                metadata=metadata or {},
            )
            entity = self._entities[entity_id]
            entity.live_state[key] = sample
            entity.updated_at = now_iso()
            self._touch(
                "observation.recorded",
                entity_id=entity_id,
                source=source,
                payload={"key": key, "source_id": source_id, "confidence": sample.confidence},
            )
            self._persist()
            return sample.model_copy(deep=True)


def euler_xyz_deg_to_quaternion(rotation_deg: list[float] | tuple[float, float, float]) -> list[float]:
    rx, ry, rz = [math.radians(float(value)) * 0.5 for value in rotation_deg]
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    x = sx * cy * cz - cx * sy * sz
    y = cx * sy * cz + sx * cy * sz
    z = cx * cy * sz - sx * sy * cz
    w = cx * cy * cz + sx * sy * sz
    norm = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return [x / norm, y / norm, z / norm, w / norm]


def _project_entity_id(branch: str) -> str:
    return f"forgecad:project:{branch}"


def _object_entity_id(object_id: str) -> str:
    return f"forgecad:object:{object_id}"


def _project_capabilities(obj: dict[str, Any]) -> list[WorldCapability]:
    capabilities = [WorldCapability(name="engineering.inspect", mode="engineer")]
    if isinstance(obj.get("code"), dict):
        capabilities.extend(
            [
                WorldCapability(name="compute.execute", mode="compute"),
                WorldCapability(name="software.deploy", mode="compute"),
            ]
        )
    semantic = obj.get("semantic") or {}
    snapshot = obj.get("component_snapshot") or {}
    text = " ".join(
        str(value or "").lower()
        for value in (
            semantic.get("role"),
            snapshot.get("category"),
            snapshot.get("name"),
            obj.get("name"),
        )
    )
    if "sensor" in text:
        capabilities.append(WorldCapability(name="sensor.observe", mode="sense"))
    if any(token in text for token in ("motor", "servo", "solenoid", "actuator", "relay")):
        capabilities.append(WorldCapability(name="actuator.control", mode="actuate"))
    if obj.get("component_ref"):
        capabilities.append(WorldCapability(name="component.real_world", mode="engineer"))
    unique: dict[str, WorldCapability] = {row.name: row for row in capabilities}
    return list(unique.values())


def _project_interfaces(obj: dict[str, Any]) -> list[WorldInterface]:
    rows = obj.get("interfaces")
    if not isinstance(rows, list) or not rows:
        snapshot = obj.get("component_snapshot") or {}
        rows = snapshot.get("interfaces") or []
    interfaces: list[WorldInterface] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        interface_id = str(row.get("id") or row.get("name") or "").strip()
        if not interface_id:
            continue
        metadata = {
            key: deepcopy(value)
            for key, value in row.items()
            if key not in {"id", "name", "kind", "direction", "protocol"}
        }
        interfaces.append(
            WorldInterface(
                id=interface_id,
                kind=str(row.get("kind") or "unknown"),
                direction=str(row.get("direction")) if row.get("direction") is not None else None,
                protocol=str(row.get("protocol")) if row.get("protocol") is not None else None,
                metadata=metadata,
            )
        )
    return interfaces


def sync_forgecad_project(
    store: PhysicalWorldStore,
    *,
    project_snapshot: dict[str, Any],
    raw_objects: list[dict[str, Any]],
    parent_id: str | None = None,
) -> dict[str, Any]:
    """Project the active ForgeCAD design into the persistent physical world graph."""

    parent = parent_id or ROOT_WORLD_ID
    store.entity(parent)
    branch = str(project_snapshot.get("active_branch") or "main")
    project_id = _project_entity_id(branch)
    revision = str(project_snapshot.get("revision") or "")
    project_source_id = f"{branch}:{revision}"
    project_entity = WorldEntity(
        id=project_id,
        name=str(project_snapshot.get("name") or "ForgeCAD design"),
        kind="assembly",
        parent_id=parent,
        pose=WorldPose(frame_id=parent),
        capabilities=[
            WorldCapability(name="engineering.inspect", mode="engineer"),
            WorldCapability(name="engineering.modify", mode="engineer"),
            WorldCapability(name="engineering.simulate", mode="engineer"),
        ],
        provenance=[
            ProvenanceRecord(
                source="forgecad_project",
                source_id=project_source_id,
                authoritative=True,
                confidence=1.0,
                note="Canonical active ForgeCAD design projection",
            )
        ],
        source_links={"forgecad_branch": branch, "forgecad_revision": revision},
        metadata={"project_name": project_snapshot.get("name"), "active_branch": branch},
    )
    store.upsert_entity(project_entity, source="forgecad_project")

    desired_entity_ids = {project_id}
    object_lookup: dict[str, dict[str, Any]] = {}
    for obj in raw_objects:
        object_id = str(obj.get("id") or "").strip()
        if not object_id:
            continue
        object_lookup[object_id] = obj
        entity_id = _object_entity_id(object_id)
        desired_entity_ids.add(entity_id)
        transform = obj.get("transform") or {}
        position_mm = transform.get("position") or [0.0, 0.0, 0.0]
        rotation_deg = transform.get("rotation_deg") or [0.0, 0.0, 0.0]
        snapshot = obj.get("component_snapshot") or {}
        semantic = obj.get("semantic") or {}
        role = str(semantic.get("role") or snapshot.get("category") or obj.get("kind") or "component")
        kind = "device" if isinstance(obj.get("code"), dict) else ("component" if obj.get("component_ref") else "object")
        entity = WorldEntity(
            id=entity_id,
            name=str(obj.get("name") or snapshot.get("name") or object_id),
            kind=kind,
            parent_id=project_id,
            pose=WorldPose(
                frame_id=project_id,
                position_m=[float(position_mm[index]) / 1000.0 for index in range(3)],
                orientation_xyzw=euler_xyz_deg_to_quaternion([float(rotation_deg[index]) for index in range(3)]),
                confidence=1.0,
            ),
            capabilities=_project_capabilities(obj),
            interfaces=_project_interfaces(obj),
            provenance=[
                ProvenanceRecord(
                    source="forgecad_project",
                    source_id=project_source_id,
                    authoritative=True,
                    confidence=1.0,
                )
            ],
            source_links={
                "forgecad_object_id": object_id,
                "forgecad_branch": branch,
                **({"component_ref": str(obj.get("component_ref"))} if obj.get("component_ref") else {}),
            },
            metadata={
                "engineering_role": role,
                "component_ref": obj.get("component_ref"),
                "material": obj.get("material"),
                "visible": bool(obj.get("visible", True)),
                "designed_transform_mm": deepcopy(transform),
            },
        )
        store.upsert_entity(entity, source="forgecad_project", preserve_live_state=True)

    # Remove only stale entities previously owned by this exact ForgeCAD branch.
    for entity in store.entities():
        if entity.id in desired_entity_ids or entity.id == ROOT_WORLD_ID:
            continue
        if entity.source_links.get("forgecad_branch") != branch:
            continue
        if "forgecad_object_id" not in entity.source_links:
            continue
        store.delete_entity(entity.id, cascade=True, source="forgecad_project")

    desired_relations: set[str] = set()
    for connection in project_snapshot.get("connections") or []:
        if not isinstance(connection, dict):
            continue
        a = connection.get("a") or {}
        b = connection.get("b") or {}
        a_object = str(a.get("object_id") or "")
        b_object = str(b.get("object_id") or "")
        if a_object not in object_lookup or b_object not in object_lookup:
            continue
        connection_id = str(connection.get("id") or uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(connection, sort_keys=True, default=str)))
        relation_id = f"forgecad:connection:{connection_id}"
        desired_relations.add(relation_id)
        relation = WorldRelation(
            id=relation_id,
            kind=str(connection.get("kind") or "connection"),
            a_id=_object_entity_id(a_object),
            b_id=_object_entity_id(b_object),
            a_interface_id=str(a.get("interface_id")) if a.get("interface_id") is not None else None,
            b_interface_id=str(b.get("interface_id")) if b.get("interface_id") is not None else None,
            metadata={
                "forgecad_connection_id": connection_id,
                "compatibility": deepcopy(connection.get("compatibility")),
                "branch": branch,
            },
            provenance=[
                ProvenanceRecord(
                    source="forgecad_project",
                    source_id=project_source_id,
                    authoritative=True,
                    confidence=1.0,
                )
            ],
        )
        store.upsert_relation(relation, source="forgecad_project")

    for relation in store.relations():
        if relation.id in desired_relations:
            continue
        if not relation.id.startswith("forgecad:connection:"):
            continue
        if relation.metadata.get("branch") == branch:
            store.delete_relation(relation.id, source="forgecad_project")

    return {
        "ok": True,
        "project_entity_id": project_id,
        "branch": branch,
        "revision": revision,
        "project_object_count": len(object_lookup),
        "world_entity_count": len(store.snapshot().entities),
        "world_relation_count": len(store.snapshot().relations),
    }
