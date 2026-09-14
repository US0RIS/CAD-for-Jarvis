from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from .cad_features import normalize_feature


class FeatureCreate(BaseModel):
    type: str
    name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class FeaturePatch(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)


class FeatureReorder(BaseModel):
    to_index: int


class FeatureSuppress(BaseModel):
    suppressed: bool = True


class PartCreate(BaseModel):
    name: str = "Part"
    kind: str = "box"
    params: dict[str, Any] = Field(default_factory=dict)
    material: str = "aluminum_6061_t6"
    semantic: dict[str, Any] = Field(default_factory=dict)


_INSTALLED = False


def install(app: Any, require_session: Callable[..., None]) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @app.get("/v3.1/cad/objects/{object_id}/features", dependencies=[Depends(require_session)])
    async def list_features(object_id: str) -> dict[str, Any]:
        try:
            obj = core.object_by_id(object_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown CAD object: {object_id}") from exc
        return {"object_id": object_id, "items": deepcopy(obj.get("features", [])), "count": len(obj.get("features", []))}

    @app.post("/v3.1/cad/parts", dependencies=[Depends(require_session)])
    async def create_part(request: PartCreate) -> dict[str, Any]:
        try:
            result = core.execute(
                "add",
                {
                    "name": request.name,
                    "kind": request.kind,
                    "params": request.params,
                    "material": request.material,
                    "semantic": request.semantic,
                },
                actor="human",
                reason="3.1 direct CAD part creation",
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "project": result["project"], "active_design": result["active_design"]}

    @app.post("/v3.1/cad/objects/{object_id}/features", dependencies=[Depends(require_session)])
    async def add_feature(object_id: str, request: FeatureCreate) -> dict[str, Any]:
        feature = normalize_feature({"type": request.type, **request.parameters, **({"name": request.name} if request.name else {})})
        try:
            result = core.execute("add_feature", {"id": object_id, "feature": feature}, actor="human", reason=f"add {request.type} feature")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        obj = core.object_by_id(object_id)
        return {"ok": True, "feature": deepcopy(obj.get("features", [])[-1]), "active_design": result["active_design"]}

    @app.patch("/v3.1/cad/objects/{object_id}/features/{feature_id}", dependencies=[Depends(require_session)])
    async def update_feature(object_id: str, feature_id: str, request: FeaturePatch) -> dict[str, Any]:
        try:
            return core.execute("update_feature", {"id": object_id, "feature_id": feature_id, "patch": request.patch}, actor="human", reason="edit CAD feature")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown CAD object/feature: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/v3.1/cad/objects/{object_id}/features/{feature_id}", dependencies=[Depends(require_session)])
    async def delete_feature(object_id: str, feature_id: str) -> dict[str, Any]:
        try:
            return core.execute("delete_feature", {"id": object_id, "feature_id": feature_id}, actor="human", reason="delete CAD feature")
        except (KeyError, IndexError) as exc:
            raise HTTPException(status_code=404, detail=f"Unknown CAD object/feature: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v3.1/cad/objects/{object_id}/features/{feature_id}/reorder", dependencies=[Depends(require_session)])
    async def reorder_feature(object_id: str, feature_id: str, request: FeatureReorder) -> dict[str, Any]:
        try:
            return core.execute("reorder_feature", {"id": object_id, "feature_id": feature_id, "to_index": request.to_index}, actor="human", reason="reorder CAD feature history")
        except (KeyError, IndexError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v3.1/cad/objects/{object_id}/features/{feature_id}/suppress", dependencies=[Depends(require_session)])
    async def suppress_feature(object_id: str, feature_id: str, request: FeatureSuppress) -> dict[str, Any]:
        try:
            return core.execute("suppress_feature", {"id": object_id, "feature_id": feature_id, "suppressed": request.suppressed}, actor="human", reason="suppress CAD feature")
        except (KeyError, IndexError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v3.1/cad/objects/{object_id}/features/{feature_id}/duplicate", dependencies=[Depends(require_session)])
    async def duplicate_feature(object_id: str, feature_id: str, name: str | None = None) -> dict[str, Any]:
        try:
            return core.execute("duplicate_feature", {"id": object_id, "feature_id": feature_id, "name": name}, actor="human", reason="duplicate CAD feature")
        except (KeyError, IndexError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    _INSTALLED = True
