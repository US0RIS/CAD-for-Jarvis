from __future__ import annotations

"""Canonical cross-domain engineering graph for ForgeCAD 3.1.

The graph is deliberately derived from canonical project/world state. It gives
Jarvis and the desktop one stable identity plane across CAD objects, component
catalog identities, interfaces, BOM records, requirements, analyses, software,
manufacturing, deployments and physical-world entities without making the graph
a second source of truth.
"""

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable

from pydantic import BaseModel, Field

from . import ENGINEERING_GRAPH_SCHEMA_VERSION


DEPENDENCY_EDGE_KINDS = {
    "contains",
    "depends_on",
    "instance_of",
    "implements",
    "verifies",
    "analysis_of",
    "software_for",
    "bom_for",
    "interface_of",
    "connected_to",
    "joint_between",
    "represents",
    "deployed_to",
    "manufactures",
    "observes",
    "scoped_to",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_id(value: Any) -> str:
    return str(value or "").strip()


class EngineeringNode(BaseModel):
    id: str
    kind: str
    name: str
    domain: str
    source: str
    source_id: str | None = None
    fingerprint: str
    properties: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    dirty: bool = False
    dirty_reasons: list[str] = Field(default_factory=list)


class EngineeringEdge(BaseModel):
    id: str
    kind: str
    from_id: str
    to_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str


class EngineeringEvidence(BaseModel):
    id: str
    kind: str
    subject_node_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    value: Any = None
    unit: str | None = None
    status: str = "informational"
    method: str = "forgecad"
    source_ids: list[str] = Field(default_factory=list)
    input_fingerprints: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=_now)
    stale: bool = False
    invalidation_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineeringGraphSnapshot(BaseModel):
    schema_version: int = ENGINEERING_GRAPH_SCHEMA_VERSION
    project_revision: str
    active_branch: str
    graph_revision: str
    generated_at: str = Field(default_factory=_now)
    profile: dict[str, Any] = Field(default_factory=dict)
    nodes: list[EngineeringNode] = Field(default_factory=list)
    edges: list[EngineeringEdge] = Field(default_factory=list)
    evidence: list[EngineeringEvidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineeringGraphStore:
    """Persistent derived engineering graph with deterministic invalidation.

    Persistence is atomic. The graph can always be reconstructed from canonical
    project/world state, so load failures never mutate canonical engineering data.
    """

    def __init__(self, path: Path | None = None) -> None:
        data_dir = Path(os.environ.get("FORGECAD_DATA_DIR") or (Path.home() / ".forgecad"))
        self.path = path or (data_dir / "engineering_graph_v31.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._snapshot: EngineeringGraphSnapshot | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._snapshot = EngineeringGraphSnapshot.model_validate(payload)
        except Exception:
            self._snapshot = None

    def _persist(self) -> None:
        if self._snapshot is None:
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._snapshot.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    @staticmethod
    def _node(
        *,
        node_id: str,
        kind: str,
        name: str,
        domain: str,
        source: str,
        source_id: str | None,
        properties: dict[str, Any],
        tags: Iterable[str] = (),
        confidence: float = 1.0,
        provenance: list[dict[str, Any]] | None = None,
    ) -> EngineeringNode:
        body = {
            "kind": kind,
            "name": name,
            "domain": domain,
            "source": source,
            "source_id": source_id,
            "properties": properties,
            "tags": sorted({str(x) for x in tags if str(x)}),
            "confidence": float(confidence),
            "provenance": provenance or [],
        }
        return EngineeringNode(
            id=node_id,
            fingerprint=_fingerprint(body),
            **body,
        )

    @staticmethod
    def _edge(
        *,
        kind: str,
        from_id: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
    ) -> EngineeringEdge:
        props = deepcopy(properties or {})
        body = {"kind": kind, "from_id": from_id, "to_id": to_id, "properties": props}
        digest = _fingerprint(body)
        return EngineeringEdge(
            id=f"edge:{kind}:{digest[:20]}",
            kind=kind,
            from_id=from_id,
            to_id=to_id,
            properties=props,
            fingerprint=digest,
        )

    def snapshot(self) -> EngineeringGraphSnapshot:
        with self._lock:
            if self._snapshot is None:
                raise RuntimeError("Engineering graph has not been synchronized")
            return self._snapshot.model_copy(deep=True)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            if self._snapshot is None:
                return {"ready": False, "schema_version": ENGINEERING_GRAPH_SCHEMA_VERSION}
            by_domain: dict[str, int] = {}
            dirty = 0
            for node in self._snapshot.nodes:
                by_domain[node.domain] = by_domain.get(node.domain, 0) + 1
                dirty += int(node.dirty)
            stale_evidence = sum(int(item.stale) for item in self._snapshot.evidence)
            return {
                "ready": True,
                "schema_version": self._snapshot.schema_version,
                "graph_revision": self._snapshot.graph_revision,
                "project_revision": self._snapshot.project_revision,
                "active_branch": self._snapshot.active_branch,
                "node_count": len(self._snapshot.nodes),
                "edge_count": len(self._snapshot.edges),
                "evidence_count": len(self._snapshot.evidence),
                "dirty_node_count": dirty,
                "stale_evidence_count": stale_evidence,
                "domains": by_domain,
                "profile": deepcopy(self._snapshot.profile),
            }

    def node(self, node_id: str) -> EngineeringNode:
        snapshot = self.snapshot()
        for node in snapshot.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def nodes(self, *, kind: str | None = None, domain: str | None = None, dirty: bool | None = None) -> list[EngineeringNode]:
        rows = self.snapshot().nodes
        if kind is not None:
            rows = [row for row in rows if row.kind == kind]
        if domain is not None:
            rows = [row for row in rows if row.domain == domain]
        if dirty is not None:
            rows = [row for row in rows if row.dirty is dirty]
        return rows

    def edges(self, *, node_id: str | None = None, kind: str | None = None) -> list[EngineeringEdge]:
        rows = self.snapshot().edges
        if kind is not None:
            rows = [row for row in rows if row.kind == kind]
        if node_id is not None:
            rows = [row for row in rows if row.from_id == node_id or row.to_id == node_id]
        return rows

    def add_evidence(self, evidence: EngineeringEvidence) -> EngineeringEvidence:
        with self._lock:
            if self._snapshot is None:
                raise RuntimeError("Engineering graph has not been synchronized")
            node_map = {node.id: node for node in self._snapshot.nodes}
            for node_id in evidence.subject_node_ids:
                if node_id not in node_map:
                    raise KeyError(node_id)
            candidate = evidence.model_copy(deep=True)
            if not candidate.input_fingerprints:
                candidate.input_fingerprints = {
                    node_id: node_map[node_id].fingerprint
                    for node_id in candidate.subject_node_ids
                    if node_id in node_map
                }
            existing = [row for row in self._snapshot.evidence if row.id != candidate.id]
            existing.append(candidate)
            self._snapshot.evidence = existing
            self._recompute_revision_locked()
            self._persist()
            return candidate.model_copy(deep=True)

    def evidence(self, *, requirement_id: str | None = None, subject_node_id: str | None = None, include_stale: bool = True) -> list[EngineeringEvidence]:
        rows = self.snapshot().evidence
        if requirement_id is not None:
            rows = [row for row in rows if requirement_id in row.requirement_ids]
        if subject_node_id is not None:
            rows = [row for row in rows if subject_node_id in row.subject_node_ids]
        if not include_stale:
            rows = [row for row in rows if not row.stale]
        return rows

    def _recompute_revision_locked(self) -> None:
        assert self._snapshot is not None
        payload = {
            "schema_version": self._snapshot.schema_version,
            "project_revision": self._snapshot.project_revision,
            "active_branch": self._snapshot.active_branch,
            "profile": self._snapshot.profile,
            "nodes": [row.model_dump(mode="json") for row in self._snapshot.nodes],
            "edges": [row.model_dump(mode="json") for row in self._snapshot.edges],
            "evidence": [row.model_dump(mode="json") for row in self._snapshot.evidence],
        }
        self._snapshot.graph_revision = _fingerprint(payload)
        self._snapshot.generated_at = _now()

    def synchronize(
        self,
        *,
        project_snapshot: dict[str, Any],
        raw_project: dict[str, Any],
        world_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebuild graph projection and preserve valid evidence.

        Evidence is invalidated when any captured input fingerprint changed or a
        referenced node disappeared. Dirty nodes are propagated through typed
        dependency edges from changed canonical nodes.
        """
        with self._lock:
            old = self._snapshot.model_copy(deep=True) if self._snapshot is not None else None
            new_snapshot = build_engineering_graph(
                project_snapshot=project_snapshot,
                raw_project=raw_project,
                world_snapshot=world_snapshot,
            )
            old_nodes = {row.id: row for row in (old.nodes if old else [])}
            new_nodes = {row.id: row for row in new_snapshot.nodes}
            changed_ids = {
                node_id
                for node_id in set(old_nodes) | set(new_nodes)
                if node_id not in old_nodes
                or node_id not in new_nodes
                or old_nodes[node_id].fingerprint != new_nodes[node_id].fingerprint
            }

            preserved: list[EngineeringEvidence] = []
            for item in (old.evidence if old else []):
                candidate = item.model_copy(deep=True)
                reasons = list(candidate.invalidation_reasons)
                for node_id, fingerprint in candidate.input_fingerprints.items():
                    current = new_nodes.get(node_id)
                    if current is None:
                        reasons.append(f"input node removed: {node_id}")
                    elif current.fingerprint != fingerprint:
                        reasons.append(f"input fingerprint changed: {node_id}")
                if reasons:
                    candidate.stale = True
                    candidate.invalidation_reasons = sorted(set(reasons))
                preserved.append(candidate)
            new_snapshot.evidence = preserved
            self._snapshot = new_snapshot
            if changed_ids:
                self._mark_dirty_locked(changed_ids, reason="canonical state changed")
            self._recompute_revision_locked()
            self._persist()
            return {
                "ok": True,
                "graph_revision": self._snapshot.graph_revision,
                "project_revision": self._snapshot.project_revision,
                "changed_node_ids": sorted(changed_ids),
                "changed_node_count": len(changed_ids),
                "summary": self.summary(),
            }

    def _mark_dirty_locked(self, node_ids: Iterable[str], *, reason: str) -> set[str]:
        assert self._snapshot is not None
        node_map = {row.id: row for row in self._snapshot.nodes}
        adjacency: dict[str, set[str]] = {}
        for edge in self._snapshot.edges:
            if edge.kind not in DEPENDENCY_EDGE_KINDS:
                continue
            adjacency.setdefault(edge.from_id, set()).add(edge.to_id)
            # Most engineering dependency relations can invalidate either side:
            # e.g. a changed interface invalidates its connection and vice versa.
            adjacency.setdefault(edge.to_id, set()).add(edge.from_id)
        queue = deque(str(node_id) for node_id in node_ids if str(node_id))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            row = node_map.get(current)
            if row is not None:
                row.dirty = True
                row.dirty_reasons = sorted(set([*row.dirty_reasons, reason]))
            for neighbor in adjacency.get(current, set()):
                if neighbor not in seen:
                    queue.append(neighbor)
        return seen

    def mark_dirty(self, node_ids: Iterable[str], *, reason: str) -> list[str]:
        with self._lock:
            if self._snapshot is None:
                raise RuntimeError("Engineering graph has not been synchronized")
            impacted = self._mark_dirty_locked(node_ids, reason=reason)
            self._recompute_revision_locked()
            self._persist()
            return sorted(impacted)

    def clear_dirty(self, node_ids: Iterable[str] | None = None) -> None:
        with self._lock:
            if self._snapshot is None:
                return
            wanted = set(node_ids or [])
            for row in self._snapshot.nodes:
                if not wanted or row.id in wanted:
                    row.dirty = False
                    row.dirty_reasons = []
            self._recompute_revision_locked()
            self._persist()

    def impact(self, node_id: str, *, max_depth: int = 6) -> dict[str, Any]:
        snapshot = self.snapshot()
        node_map = {row.id: row for row in snapshot.nodes}
        if node_id not in node_map:
            raise KeyError(node_id)
        adjacency: dict[str, list[tuple[str, EngineeringEdge]]] = {}
        for edge in snapshot.edges:
            if edge.kind not in DEPENDENCY_EDGE_KINDS:
                continue
            adjacency.setdefault(edge.from_id, []).append((edge.to_id, edge))
            adjacency.setdefault(edge.to_id, []).append((edge.from_id, edge))
        queue = deque([(node_id, 0)])
        seen = {node_id}
        impacted: list[dict[str, Any]] = []
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor, edge in adjacency.get(current, []):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                row = node_map.get(neighbor)
                if row is not None:
                    impacted.append(
                        {
                            "node_id": neighbor,
                            "kind": row.kind,
                            "domain": row.domain,
                            "name": row.name,
                            "depth": depth + 1,
                            "via_edge": edge.kind,
                        }
                    )
                queue.append((neighbor, depth + 1))
        impacted.sort(key=lambda row: (row["depth"], row["domain"], row["name"], row["node_id"]))
        return {
            "source": node_map[node_id].model_dump(mode="json"),
            "impacted": impacted,
            "count": len(impacted),
            "max_depth": max_depth,
        }

    def trace_to(self, start_id: str, predicate_kinds: set[str], *, max_depth: int = 8) -> list[dict[str, Any]]:
        snapshot = self.snapshot()
        node_map = {row.id: row for row in snapshot.nodes}
        if start_id not in node_map:
            raise KeyError(start_id)
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for edge in snapshot.edges:
            if edge.kind not in DEPENDENCY_EDGE_KINDS:
                continue
            adjacency.setdefault(edge.from_id, []).append((edge.to_id, edge.kind))
            adjacency.setdefault(edge.to_id, []).append((edge.from_id, edge.kind))
        queue = deque([(start_id, [])])
        seen = {start_id}
        hits: list[dict[str, Any]] = []
        while queue:
            current, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            for neighbor, edge_kind in adjacency.get(current, []):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                next_path = [*path, {"from": current, "edge": edge_kind, "to": neighbor}]
                node = node_map.get(neighbor)
                if node is not None and node.kind in predicate_kinds:
                    hits.append({"node": node.model_dump(mode="json"), "path": next_path})
                queue.append((neighbor, next_path))
        hits.sort(key=lambda row: (len(row["path"]), row["node"]["id"]))
        return hits

    def semantic_diff(self, other: EngineeringGraphSnapshot) -> dict[str, Any]:
        current = self.snapshot()
        a_nodes = {row.id: row for row in other.nodes}
        b_nodes = {row.id: row for row in current.nodes}
        node_changes: list[dict[str, Any]] = []
        for node_id in sorted(set(a_nodes) | set(b_nodes)):
            if node_id not in a_nodes:
                node_changes.append({"id": node_id, "change": "added", "after": b_nodes[node_id].model_dump(mode="json")})
            elif node_id not in b_nodes:
                node_changes.append({"id": node_id, "change": "removed", "before": a_nodes[node_id].model_dump(mode="json")})
            elif a_nodes[node_id].fingerprint != b_nodes[node_id].fingerprint:
                node_changes.append(
                    {
                        "id": node_id,
                        "change": "modified",
                        "before": a_nodes[node_id].model_dump(mode="json"),
                        "after": b_nodes[node_id].model_dump(mode="json"),
                    }
                )
        a_edges = {row.id: row for row in other.edges}
        b_edges = {row.id: row for row in current.edges}
        return {
            "from_revision": other.graph_revision,
            "to_revision": current.graph_revision,
            "node_changes": node_changes,
            "edge_added": [b_edges[key].model_dump(mode="json") for key in sorted(set(b_edges) - set(a_edges))],
            "edge_removed": [a_edges[key].model_dump(mode="json") for key in sorted(set(a_edges) - set(b_edges))],
            "changed_node_count": len(node_changes),
        }


def _project_profile(raw_project: dict[str, Any]) -> dict[str, Any]:
    settings = raw_project.get("settings") or {}
    profile = deepcopy(settings.get("product_profile") or {})
    profile.setdefault("mode", "general_engineering")
    profile.setdefault("schema_version", 1)
    return profile


def build_engineering_graph(
    *,
    project_snapshot: dict[str, Any],
    raw_project: dict[str, Any],
    world_snapshot: dict[str, Any] | None = None,
) -> EngineeringGraphSnapshot:
    nodes: dict[str, EngineeringNode] = {}
    edges: dict[str, EngineeringEdge] = {}

    def add_node(node: EngineeringNode) -> None:
        nodes[node.id] = node

    def add_edge(edge: EngineeringEdge) -> None:
        if edge.from_id in nodes and edge.to_id in nodes:
            edges[edge.id] = edge

    active_branch = str(project_snapshot.get("active_branch") or "main")
    project_revision = str(project_snapshot.get("revision") or raw_project.get("updated_at") or _now())
    project_id = f"project:{active_branch}"
    project_props = {
        "name": project_snapshot.get("name") or raw_project.get("name"),
        "revision": project_revision,
        "metrics": deepcopy(project_snapshot.get("metrics") or {}),
    }
    add_node(
        EngineeringGraphStore._node(
            node_id=project_id,
            kind="project",
            name=str(project_props["name"] or "ForgeCAD Project"),
            domain="project",
            source="forgecad_project",
            source_id=active_branch,
            properties=project_props,
            tags=["canonical", "branch"],
        )
    )

    raw_objects = {str(row.get("id")): row for row in raw_project.get("objects", []) if row.get("id")}
    for object_id, obj in raw_objects.items():
        cad_id = f"cad:{object_id}"
        component_ref = obj.get("component_ref")
        props = {
            "object_id": object_id,
            "kind": obj.get("kind"),
            "params": deepcopy(obj.get("params") or {}),
            "material": obj.get("material"),
            "transform": deepcopy(obj.get("transform") or {}),
            "semantic": deepcopy(obj.get("semantic") or {}),
            "component_ref": component_ref,
            "visible": bool(obj.get("visible", True)),
        }
        add_node(
            EngineeringGraphStore._node(
                node_id=cad_id,
                kind="cad_object",
                name=str(obj.get("name") or object_id),
                domain="mechanical",
                source="forgecad_object",
                source_id=object_id,
                properties=props,
                tags=[str(obj.get("kind") or "part"), *(obj.get("semantic") or {}).get("tags", [])],
                confidence=1.0,
            )
        )
        add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=cad_id))

        for index, feature in enumerate(obj.get("features", [])):
            feature_id = _safe_id(feature.get("id")) or f"index-{index}"
            node_id = f"feature:{object_id}:{feature_id}"
            add_node(
                EngineeringGraphStore._node(
                    node_id=node_id,
                    kind="cad_feature",
                    name=str(feature.get("name") or feature.get("type") or feature_id),
                    domain="mechanical",
                    source="forgecad_feature",
                    source_id=feature_id,
                    properties=deepcopy(feature),
                    tags=[str(feature.get("type") or "feature")],
                )
            )
            add_edge(EngineeringGraphStore._edge(kind="contains", from_id=cad_id, to_id=node_id, properties={"order": index}))
            add_edge(EngineeringGraphStore._edge(kind="depends_on", from_id=cad_id, to_id=node_id))

        if component_ref:
            snapshot = deepcopy(obj.get("component_snapshot") or {})
            comp_id = f"component:{component_ref}"
            add_node(
                EngineeringGraphStore._node(
                    node_id=comp_id,
                    kind="catalog_component",
                    name=str(snapshot.get("name") or component_ref),
                    domain="component",
                    source="component_registry",
                    source_id=str(component_ref),
                    properties=snapshot,
                    tags=[str(snapshot.get("category") or "component"), *snapshot.get("tags", [])],
                    confidence=max(0.0, min(1.0, float(snapshot.get("trust_score", 0)) / 100.0)),
                    provenance=deepcopy(snapshot.get("provenance") or []),
                )
            )
            add_edge(EngineeringGraphStore._edge(kind="instance_of", from_id=cad_id, to_id=comp_id))

        for interface in obj.get("interfaces", []):
            interface_id = _safe_id(interface.get("id"))
            if not interface_id:
                continue
            node_id = f"interface:{object_id}:{interface_id}"
            add_node(
                EngineeringGraphStore._node(
                    node_id=node_id,
                    kind="interface",
                    name=f"{obj.get('name') or object_id} · {interface_id}",
                    domain="interface",
                    source="forgecad_interface",
                    source_id=interface_id,
                    properties=deepcopy(interface),
                    tags=[str(interface.get("kind") or "interface")],
                )
            )
            add_edge(EngineeringGraphStore._edge(kind="interface_of", from_id=node_id, to_id=cad_id))

        if isinstance(obj.get("code"), dict):
            code = deepcopy(obj["code"])
            files = code.get("files") or {}
            code["software_sha256"] = _fingerprint(files)
            software_id = f"software:{object_id}"
            add_node(
                EngineeringGraphStore._node(
                    node_id=software_id,
                    kind="software_workspace",
                    name=f"{obj.get('name') or object_id} software",
                    domain="software",
                    source="forgecad_code_workspace",
                    source_id=object_id,
                    properties=code,
                    tags=[str(code.get("platform") or "software")],
                )
            )
            add_edge(EngineeringGraphStore._edge(kind="software_for", from_id=software_id, to_id=cad_id))

    for index, item in enumerate(raw_project.get("bom", [])):
        source_id = _safe_id(item.get("id")) or _safe_id(item.get("component_ref")) or str(index)
        node_id = f"bom:{source_id}"
        add_node(
            EngineeringGraphStore._node(
                node_id=node_id,
                kind="bom_item",
                name=str(item.get("description") or item.get("model") or source_id),
                domain="procurement",
                source="project_bom",
                source_id=source_id,
                properties=deepcopy(item),
                tags=["bom", str(item.get("manufacturer") or "unknown")],
            )
        )
        add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=node_id))
        component_ref = item.get("component_ref")
        if component_ref and f"component:{component_ref}" in nodes:
            add_edge(EngineeringGraphStore._edge(kind="bom_for", from_id=node_id, to_id=f"component:{component_ref}"))

    for collection_name, kind, domain in (
        ("joints", "joint", "assembly"),
        ("loads", "load", "analysis"),
        ("constraints", "constraint", "requirements"),
        ("requirements", "requirement", "requirements"),
    ):
        for index, item in enumerate(raw_project.get(collection_name, [])):
            source_id = _safe_id(item.get("id")) or str(index)
            node_id = f"{kind}:{source_id}"
            add_node(
                EngineeringGraphStore._node(
                    node_id=node_id,
                    kind=kind,
                    name=str(item.get("name") or item.get("metric") or item.get("type") or source_id),
                    domain=domain,
                    source=f"project_{collection_name}",
                    source_id=source_id,
                    properties=deepcopy(item),
                    tags=[kind, str(item.get("criticality") or item.get("type") or "")],
                )
            )
            add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=node_id))
            scope_ids = []
            for key in ("object_id", "part_id", "subject_id", "a_id", "b_id"):
                value = item.get(key)
                if value:
                    scope_ids.append(str(value))
            for value in item.get("scope_object_ids", []) or []:
                scope_ids.append(str(value))
            for object_id in sorted(set(scope_ids)):
                cad_id = f"cad:{object_id}"
                if cad_id in nodes:
                    edge_kind = "joint_between" if kind == "joint" else "scoped_to"
                    add_edge(EngineeringGraphStore._edge(kind=edge_kind, from_id=node_id, to_id=cad_id))

    for connection_index, connection in enumerate(raw_project.get("connections", [])):
        a = connection.get("a") or {}
        b = connection.get("b") or {}
        a_obj, b_obj = _safe_id(a.get("object_id")), _safe_id(b.get("object_id"))
        a_if, b_if = _safe_id(a.get("interface_id")), _safe_id(b.get("interface_id"))
        a_node = f"interface:{a_obj}:{a_if}" if a_obj and a_if else f"cad:{a_obj}"
        b_node = f"interface:{b_obj}:{b_if}" if b_obj and b_if else f"cad:{b_obj}"
        if a_node in nodes and b_node in nodes:
            add_edge(
                EngineeringGraphStore._edge(
                    kind="connected_to",
                    from_id=a_node,
                    to_id=b_node,
                    properties={"connection": deepcopy(connection), "order": connection_index},
                )
            )

    for index, simulation in enumerate(raw_project.get("simulations", [])):
        source_id = _safe_id(simulation.get("id")) or str(index)
        node_id = f"analysis:{source_id}"
        add_node(
            EngineeringGraphStore._node(
                node_id=node_id,
                kind="analysis",
                name=str(simulation.get("kind") or source_id),
                domain="analysis",
                source="project_simulation",
                source_id=source_id,
                properties=deepcopy(simulation),
                tags=[str(simulation.get("kind") or "analysis"), "stale" if simulation.get("stale") else "current"],
            )
        )
        add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=node_id))
        object_id = simulation.get("object_id")
        if object_id and f"cad:{object_id}" in nodes:
            add_edge(EngineeringGraphStore._edge(kind="analysis_of", from_id=node_id, to_id=f"cad:{object_id}"))

    for index, package in enumerate(raw_project.get("fabrication_packages", [])):
        source_id = _safe_id(package.get("id")) or str(index)
        node_id = f"fabrication:{source_id}"
        add_node(
            EngineeringGraphStore._node(
                node_id=node_id,
                kind="fabrication_package",
                name=str(package.get("name") or source_id),
                domain="manufacturing",
                source="fabrication_package",
                source_id=source_id,
                properties=deepcopy(package),
                tags=["fabrication", str(package.get("status") or "generated")],
            )
        )
        add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=node_id))
        for object_id in package.get("object_ids", []) or []:
            cad_id = f"cad:{object_id}"
            if cad_id in nodes:
                add_edge(EngineeringGraphStore._edge(kind="manufactures", from_id=node_id, to_id=cad_id))

    for index, deployment in enumerate(raw_project.get("deployments", [])):
        source_id = _safe_id(deployment.get("id")) or str(index)
        node_id = f"deployment:{source_id}"
        add_node(
            EngineeringGraphStore._node(
                node_id=node_id,
                kind="deployment",
                name=str(deployment.get("name") or source_id),
                domain="hardware",
                source="deployment_record",
                source_id=source_id,
                properties=deepcopy(deployment),
                tags=["deployment", str(deployment.get("status") or "observed")],
                confidence=float(deployment.get("confidence", 1.0) or 1.0),
            )
        )
        add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=node_id))
        object_id = deployment.get("object_id")
        if object_id and f"cad:{object_id}" in nodes:
            add_edge(EngineeringGraphStore._edge(kind="deployed_to", from_id=node_id, to_id=f"cad:{object_id}"))

    for index, inspection in enumerate(raw_project.get("inspections", [])):
        source_id = _safe_id(inspection.get("id")) or str(index)
        node_id = f"inspection:{source_id}"
        add_node(
            EngineeringGraphStore._node(
                node_id=node_id,
                kind="inspection",
                name=str(inspection.get("name") or inspection.get("metric") or source_id),
                domain="physical_evidence",
                source="inspection_record",
                source_id=source_id,
                properties=deepcopy(inspection),
                tags=["inspection", str(inspection.get("status") or "observed")],
                confidence=float(inspection.get("confidence", 1.0) or 1.0),
            )
        )
        add_edge(EngineeringGraphStore._edge(kind="contains", from_id=project_id, to_id=node_id))
        object_id = inspection.get("object_id")
        if object_id and f"cad:{object_id}" in nodes:
            add_edge(EngineeringGraphStore._edge(kind="observes", from_id=node_id, to_id=f"cad:{object_id}"))

    if world_snapshot:
        for entity in world_snapshot.get("entities", []):
            world_id = _safe_id(entity.get("id"))
            if not world_id:
                continue
            node_id = f"world:{world_id}"
            add_node(
                EngineeringGraphStore._node(
                    node_id=node_id,
                    kind="world_entity",
                    name=str(entity.get("name") or world_id),
                    domain="world",
                    source="physical_world_model",
                    source_id=world_id,
                    properties=deepcopy(entity),
                    tags=[str(entity.get("kind") or "world_entity"), *entity.get("capabilities", [])],
                    confidence=float(entity.get("confidence", 1.0) or 1.0),
                    provenance=deepcopy(entity.get("provenance") or []),
                )
            )
            links = entity.get("source_links") or {}
            object_id = links.get("forgecad_object_id")
            if object_id and f"cad:{object_id}" in nodes:
                add_edge(EngineeringGraphStore._edge(kind="represents", from_id=node_id, to_id=f"cad:{object_id}"))
        for relation in world_snapshot.get("relations", []):
            a_id = f"world:{relation.get('a_id')}"
            b_id = f"world:{relation.get('b_id')}"
            if a_id in nodes and b_id in nodes:
                add_edge(
                    EngineeringGraphStore._edge(
                        kind="world_relation",
                        from_id=a_id,
                        to_id=b_id,
                        properties=deepcopy(relation),
                    )
                )

    ordered_nodes = sorted(nodes.values(), key=lambda row: row.id)
    ordered_edges = sorted(edges.values(), key=lambda row: row.id)
    payload = {
        "schema_version": ENGINEERING_GRAPH_SCHEMA_VERSION,
        "project_revision": project_revision,
        "active_branch": active_branch,
        "profile": _project_profile(raw_project),
        "nodes": [row.model_dump(mode="json") for row in ordered_nodes],
        "edges": [row.model_dump(mode="json") for row in ordered_edges],
    }
    return EngineeringGraphSnapshot(
        project_revision=project_revision,
        active_branch=active_branch,
        graph_revision=_fingerprint(payload),
        profile=_project_profile(raw_project),
        nodes=ordered_nodes,
        edges=ordered_edges,
        evidence=[],
        metadata={"reconstructable": True, "canonical_source": "forgecad_project+physical_world"},
    )
