from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .world_model import PhysicalWorldStore, ROOT_WORLD_ID, WorldEntity


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize(value: Any) -> str:
    return " ".join(_TOKEN_RE.findall(str(value or "").lower()))


def _tokens(value: Any) -> set[str]:
    return set(_TOKEN_RE.findall(str(value or "").lower()))


class EntityReferenceCandidate(BaseModel):
    entity_id: str
    name: str
    kind: str
    score: int
    match_type: str
    path: str
    source_links: dict[str, str] = Field(default_factory=dict)


class EntityResolution(BaseModel):
    query: str
    status: str
    entity_id: str | None = None
    exact: bool = False
    reason: str
    candidates: list[EntityReferenceCandidate] = Field(default_factory=list)


def _entity_path(store: PhysicalWorldStore, entity: WorldEntity) -> str:
    names: list[str] = [entity.name]
    cursor = entity.parent_id
    visited: set[str] = {entity.id}
    while cursor and cursor not in visited:
        visited.add(cursor)
        try:
            parent = store.entity(cursor)
        except KeyError:
            break
        if parent.id != ROOT_WORLD_ID:
            names.append(parent.name)
        cursor = parent.parent_id
    names.reverse()
    return " / ".join(names)


def _aliases(entity: WorldEntity) -> list[str]:
    raw = entity.metadata.get("aliases")
    if isinstance(raw, list):
        return [str(value) for value in raw if str(value).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw]
    return []


def _filtered_entities(
    store: PhysicalWorldStore,
    *,
    kind: str | None,
    capability: str | None,
) -> list[WorldEntity]:
    rows = store.entities(kind=kind, capability=capability)
    return [row for row in rows if row.id != ROOT_WORLD_ID]


def resolve_entity_reference(
    store: PhysicalWorldStore,
    query: str,
    *,
    kind: str | None = None,
    capability: str | None = None,
    max_candidates: int = 10,
) -> EntityResolution:
    """Resolve a human/Jarvis reference without allowing the model to invent identity.

    Only exact deterministic matches may auto-resolve. Fuzzy similarity is returned as
    candidate context and always requires an explicit follow-up selection. This makes
    ambiguous names such as two identical Raspberry Pis fail closed rather than silently
    choosing whichever object happened to rank first.
    """

    raw_query = str(query or "").strip()
    normalized = _normalize(raw_query)
    if not normalized:
        return EntityResolution(query=raw_query, status="not_found", reason="empty_reference")

    rows = _filtered_entities(store, kind=kind, capability=capability)
    if not rows:
        return EntityResolution(query=raw_query, status="not_found", reason="no_entities_in_scope")

    exact_candidates: list[EntityReferenceCandidate] = []
    fuzzy_candidates: list[EntityReferenceCandidate] = []
    q_tokens = _tokens(raw_query)

    for entity in rows:
        path = _entity_path(store, entity)
        match_type: str | None = None
        score = 0

        if raw_query == entity.id:
            match_type, score = "entity_id", 100
        else:
            source_matches = [
                key
                for key, value in entity.source_links.items()
                if _normalize(value) == normalized
            ]
            if source_matches:
                match_type, score = f"source_link:{source_matches[0]}", 96
            elif _normalize(path) == normalized:
                match_type, score = "hierarchy_path", 94
            elif _normalize(entity.name) == normalized:
                match_type, score = "name", 92
            elif any(_normalize(alias) == normalized for alias in _aliases(entity)):
                match_type, score = "alias", 90

        if match_type is not None:
            exact_candidates.append(
                EntityReferenceCandidate(
                    entity_id=entity.id,
                    name=entity.name,
                    kind=entity.kind,
                    score=score,
                    match_type=match_type,
                    path=path,
                    source_links=dict(entity.source_links),
                )
            )
            continue

        # Fuzzy candidates are useful context but are deliberately non-authoritative.
        searchable = " ".join(
            [entity.name, path, *_aliases(entity), *entity.source_links.values()]
        )
        candidate_tokens = _tokens(searchable)
        if not q_tokens or not candidate_tokens:
            continue
        overlap = len(q_tokens & candidate_tokens)
        if overlap == 0:
            continue
        coverage = overlap / len(q_tokens)
        precision = overlap / len(candidate_tokens)
        fuzzy_score = int(round(40 + 35 * coverage + 15 * precision))
        if normalized in _normalize(searchable):
            fuzzy_score = max(fuzzy_score, 78)
        fuzzy_candidates.append(
            EntityReferenceCandidate(
                entity_id=entity.id,
                name=entity.name,
                kind=entity.kind,
                score=min(fuzzy_score, 89),
                match_type="fuzzy",
                path=path,
                source_links=dict(entity.source_links),
            )
        )

    if exact_candidates:
        exact_candidates.sort(key=lambda row: (-row.score, row.path, row.entity_id))
        best_score = exact_candidates[0].score
        best = [row for row in exact_candidates if row.score == best_score]
        if len(best) == 1:
            return EntityResolution(
                query=raw_query,
                status="resolved",
                entity_id=best[0].entity_id,
                exact=True,
                reason=best[0].match_type,
                candidates=exact_candidates[: max(1, max_candidates)],
            )
        return EntityResolution(
            query=raw_query,
            status="ambiguous",
            exact=True,
            reason="multiple_exact_matches",
            candidates=best[: max(1, max_candidates)],
        )

    if fuzzy_candidates:
        fuzzy_candidates.sort(key=lambda row: (-row.score, row.path, row.entity_id))
        return EntityResolution(
            query=raw_query,
            status="ambiguous",
            exact=False,
            reason="non_exact_match_requires_explicit_identity",
            candidates=fuzzy_candidates[: max(1, max_candidates)],
        )

    return EntityResolution(
        query=raw_query,
        status="not_found",
        exact=False,
        reason="no_matching_entity",
    )
