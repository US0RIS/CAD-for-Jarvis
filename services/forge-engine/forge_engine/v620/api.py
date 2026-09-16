from __future__ import annotations

"""Read-only inspection API for ForgeCAD 6.2 component geometry fidelity."""

from copy import deepcopy
from typing import Any

from fastapi import Depends, HTTPException

from ..v110 import component_registry as registry
from ..v110 import core
from . import MILESTONE_VERSION, RELEASE_COMPLETE, COMPONENT_GEOMETRY_SCHEMA_VERSION
from . import component_fidelity


_INSTALLED = False


def _project_component_statuses() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obj in core.PROJECT.get("objects") or []:
        if not isinstance(obj, dict) or obj.get("kind") != "component":
            continue
        status = component_fidelity.geometry_status(obj)
        rows.append({
            "object_id": str(obj.get("id") or ""),
            "name": str(obj.get("name") or obj.get("component_ref") or "Component"),
            "component_ref": str(obj.get("component_ref") or ""),
            **status,
        })
    return rows


def install(app: Any, require_session: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.get("/v6/component-fidelity/health", dependencies=[Depends(require_session)])
    async def component_fidelity_health() -> dict[str, Any]:
        rows = _project_component_statuses()
        return {
            "ok": True,
            "version": MILESTONE_VERSION,
            "release_complete": RELEASE_COMPLETE,
            "schema_version": COMPONENT_GEOMETRY_SCHEMA_VERSION,
            "project_components": len(rows),
            "authoritative_cad_components": sum(bool(row.get("authoritative_cad")) for row in rows),
            "fallback_components": sum(not bool(row.get("authoritative_cad")) for row in rows),
            "components": rows,
            "truth": "authoritative_cad=true only means the rendered/engineering B-rep came from a manufacturer or authorized-distributor CAD asset; it is not physical verification of the assembled design.",
        }

    @app.get("/v6/component-fidelity/audit", dependencies=[Depends(require_session)])
    async def component_fidelity_audit() -> dict[str, Any]:
        # Read-only and offline: background/lazy resolution happens through the normal
        # scene path. This endpoint never turns an HTTP inspection into a network crawl.
        return component_fidelity.catalog_audit(attempt_download=False)

    @app.get("/v6/component-fidelity/components/{component_id}", dependencies=[Depends(require_session)])
    async def component_fidelity_component(component_id: str) -> dict[str, Any]:
        try:
            component = registry.component_by_id(component_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown component {component_id}") from exc
        obj = {
            "id": f"inspect:{component_id}",
            "kind": "component",
            "component_ref": component_id,
            "component_snapshot": deepcopy(component),
            "features": [],
            "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        }
        return {
            "component": {
                "id": component_id,
                "manufacturer": component.get("manufacturer"),
                "model": component.get("model"),
                "manufacturer_part_number": component.get("manufacturer_part_number"),
            },
            "geometry": component_fidelity.geometry_status(obj),
            "source_candidates": [
                {"url": source.url, "kind": source.kind, "direct": source.direct}
                for source in component_fidelity._source_candidates(component)
            ],
        }

    _INSTALLED = True
