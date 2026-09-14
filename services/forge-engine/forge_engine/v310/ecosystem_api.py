from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException

from .component_ecosystem import compatible_components, component_families, ecosystem_status


_INSTALLED = False


def install(app: Any, require_session: Callable[..., None]) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.get("/v3.1/components/ecosystem", dependencies=[Depends(require_session)])
    async def get_ecosystem_status() -> dict[str, Any]:
        return ecosystem_status()

    @app.get("/v3.1/components/families", dependencies=[Depends(require_session)])
    async def get_component_families() -> dict[str, Any]:
        return component_families()

    @app.get("/v3.1/components/{component_id:path}/compatible", dependencies=[Depends(require_session)])
    async def get_compatible_components(component_id: str, limit: int = 100) -> dict[str, Any]:
        try:
            return compatible_components(component_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown component: {component_id}") from exc

    _INSTALLED = True
