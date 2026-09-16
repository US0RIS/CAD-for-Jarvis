from __future__ import annotations

"""Import real vendor CAD into reusable ForgeCAD component definitions."""
import json, tempfile
from pathlib import Path
from typing import Any
import cadquery as cq
from . import component_registry as registry


def _derive_step_geometry(data:bytes,filename:str)->dict[str,Any]:
    if len(data)>250*1024*1024:raise ValueError("STEP component exceeds 250 MB")
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/(Path(filename).name or "component.step");path.write_bytes(data)
        shape=cq.importers.importStep(str(path)).val();bb=shape.BoundingBox();vol=float(shape.Volume());area=float(shape.Area())
        if min(bb.xlen,bb.ylen,bb.zlen)<=0:raise ValueError("STEP component has a degenerate bounding box")
        return {"dimensions_mm":[float(bb.xlen),float(bb.ylen),float(bb.zlen)],"volume_mm3":vol,"surface_area_mm2":area,"centroid_mm":[float(shape.Center().x),float(shape.Center().y),float(shape.Center().z)]}

def import_step_component(filename:str,data:bytes,*,manufacturer:str,model:str,category:str="custom",component_id:str|None=None,manufacturer_part_number:str|None=None,mass_g:float|None=None,source_kind:str="user_supplied",source_url:str|None=None,tags:list[str]|None=None,interfaces:list[dict[str,Any]]|None=None,specs:dict[str,Any]|None=None,procurement:dict[str,Any]|None=None)->dict[str,Any]:
    geom=_derive_step_geometry(data,filename);cid=component_id or f"custom.{registry._slug(manufacturer)}.{registry._slug(model)}";raw={"schema_version":registry.SCHEMA_VERSION,"id":cid,"category":category,"manufacturer":manufacturer,"model":model,"name":f"{manufacturer} {model}".strip(),"manufacturer_part_number":manufacturer_part_number,"dimensions_mm":geom["dimensions_mm"],"mass_g":mass_g,"material":None,"tags":list(tags or []),"specs":dict(specs or {})|{"cad_volume_mm3":geom["volume_mm3"],"cad_surface_area_mm2":geom["surface_area_mm2"],"cad_centroid_mm":geom["centroid_mm"]},"geometry":{"preferred":"step_asset","fidelity":"official_step" if source_kind=="manufacturer" else "verified_step","trust":source_kind,"profile":"step_asset","dimensions_mm":geom["dimensions_mm"],"assets":[]},"interfaces":list(interfaces or []),"keepouts":[],"procurement":dict(procurement or {}),"software":{"programmable":False,"platform":None},"provenance":[registry._source(source_kind,source_url,"Imported vendor STEP")],"trust_score":registry.TRUST_RANK.get(source_kind,0)};registry.import_components(raw,source_kind=source_kind);asset=registry.register_asset_bytes(cid,filename,data,role="geometry",source_kind=source_kind,source_url=source_url);return {"ok":True,"component":asset["component"],"derived_geometry":geom,"asset":asset["asset"]}

def import_metadata_json(text:str)->dict[str,Any]:
    data=json.loads(text)
    if not isinstance(data,dict):raise ValueError("Component metadata must be a JSON object")
    return data

def update_component_interfaces(component_id:str,interfaces:list[dict[str,Any]])->dict[str,Any]:
    c=registry.component_by_id(component_id);c["interfaces"]=interfaces;registry.validate_component(c);registry._CUSTOM[component_id]=c;registry._persist_custom();return c
