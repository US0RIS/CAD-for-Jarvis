from __future__ import annotations

"""ForgeCAD v1.1 real-world component registry.

A purchased component is engineering data: identity, provenance, geometry assets,
interfaces, constraints, electrical behaviour, procurement, and software capability.
The CAD core consumes normalized snapshots instead of depending on supplier APIs.
"""

import hashlib
import json
import math
import os
import re
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from . import components as legacy_components
from . import curated_catalog

SCHEMA_VERSION = 1
DATA_DIR = Path(os.environ.get("FORGECAD_DATA_DIR") or (Path.home() / ".forgecad"))
REGISTRY_DIR = DATA_DIR / "component_registry"
ASSET_DIR = REGISTRY_DIR / "assets"
CUSTOM_PATH = REGISTRY_DIR / "custom-components.json"
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
ASSET_DIR.mkdir(parents=True, exist_ok=True)

TRUST_RANK = {"manufacturer":100,"standards_body":95,"authorized_distributor":85,"community_verified":70,"forgecad_derived":55,"user_supplied":45,"legacy_estimate":25,"unknown":0}
GEOMETRY_RANK = {"official_step":100,"official_cad":95,"verified_step":90,"detailed_parametric":75,"mechanical_envelope":55,"bounding_box":20,"none":0}
CATEGORY_ALIASES = {"motor":"stepper_motor","stepper":"stepper_motor","servo_motor":"servo","sbc":"compute","controller":"microcontroller","mcu":"microcontroller","linear_rail":"linear_motion","screw":"fastener","bolt":"fastener","dc_dc":"power"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-") or "component"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out=deepcopy(base)
    for key,value in override.items():
        out[key]=_deep_merge(out[key],value) if isinstance(value,dict) and isinstance(out.get(key),dict) else deepcopy(value)
    return out


def _source(kind:str,url:str|None=None,title:str|None=None,revision:str|None=None,accessed:str|None=None,notes:str|None=None)->dict[str,Any]:
    d={"kind":kind,"trust":TRUST_RANK.get(kind,0)}
    if url:d["url"]=url
    if title:d["title"]=title
    if revision:d["revision"]=revision
    if accessed:d["accessed"]=accessed
    if notes:d["notes"]=notes
    return d


def _iface(iid:str,kind:str,*,position:Iterable[float]=(0,0,0),axis:Iterable[float]=(0,0,1),gender:str="neutral",standard:str|None=None,mate:list[str]|None=None,required:bool=False,metadata:dict[str,Any]|None=None)->dict[str,Any]:
    out={"id":iid,"kind":kind,"position_mm":[float(x) for x in position],"axis":[float(x) for x in axis],"gender":gender,"required":bool(required),"mate":list(mate or [])}
    if standard:out["standard"]=standard
    if metadata:out["metadata"]=deepcopy(metadata)
    return out


def _default_geometry(c:dict[str,Any])->dict[str,Any]:
    dims=[float(x) for x in c.get("dimensions_mm",[20,20,20])[:3]]
    while len(dims)<3:dims.append(10.0)
    cat=str(c.get("category","custom"));profile=c.get("geometry_profile")
    if profile:fidelity="detailed_parametric";trust="forgecad_derived"
    elif cat in {"bearing","stepper_motor","servo","solenoid","fan","fastener","linear_motion","battery","compute","microcontroller","sensor","power"}:profile=cat;fidelity="mechanical_envelope";trust="forgecad_derived"
    else:profile="box";fidelity="bounding_box";trust="legacy_estimate"
    return {"preferred":"parametric","fidelity":fidelity,"trust":trust,"profile":profile,"dimensions_mm":dims,"assets":[],"source":_source(trust)}


def _default_interfaces(c:dict[str,Any])->list[dict[str,Any]]:
    cat=str(c.get("category","custom"));dims=[float(x) for x in c.get("dimensions_mm",[20,20,20])[:3]]
    while len(dims)<3:dims.append(10.0)
    x,y,z=dims;out=[]
    if cat=="fastener":
        dia=float(c.get("diameter_mm",max(1.0,x/1.7)));out.append(_iface("thread","mechanical_thread",position=(0,0,-z/2),axis=(0,0,-1),gender="male",standard=f"ISO-metric-M{dia:g}",mate=["mechanical_thread:female","mount_hole"],required=True,metadata={"diameter_mm":dia,"length_mm":c.get("length_mm")}))
    elif cat=="bearing":
        bore=float(c.get("bore_mm",max(1.0,x/3)));od=float(c.get("outer_diameter_mm",x));out.extend([_iface("shaft_bore","cylindrical_mate",axis=(0,0,1),gender="female",mate=["shaft"],required=True,metadata={"diameter_mm":bore}),_iface("outer_race","cylindrical_mate",axis=(0,0,1),gender="male",mate=["bearing_pocket"],required=True,metadata={"diameter_mm":od})])
    elif cat=="stepper_motor":
        face=min(x,y);nema=next((t for t in c.get("tags",[]) if str(t).startswith("nema")),None);out.extend([_iface("mount_face","mount_face",position=(0,0,-z/2),axis=(0,0,-1),standard=nema,mate=["motor_mount"],required=True,metadata={"face_mm":face}),_iface("output_shaft","shaft",position=(0,0,z/2+8),axis=(0,0,1),gender="male",mate=["cylindrical_mate","shaft_coupler"],required=True,metadata={"diameter_mm":5 if face<=42 else 6.35}),_iface("motor_power","electrical_power",position=(0,-y/2,0),axis=(0,-1,0),mate=["motor_driver"],required=True,metadata={"phases":2,"nominal_voltage_v":c.get("voltage_v",24)})])
    elif cat=="servo":
        out.extend([_iface("mount","mount_face",position=(0,0,-z/2),axis=(0,0,-1),mate=["servo_mount"],required=True),_iface("horn","rotary_output",position=(0,0,z/2),axis=(0,0,1),gender="male",mate=["servo_horn","linkage"],required=True),_iface("control","servo_signal",position=(0,-y/2,-z/4),axis=(0,-1,0),mate=["pwm_output"],required=True,metadata={"voltage_v":c.get("voltage_v",6)})])
    elif cat=="solenoid":
        stroke=float(c.get("stroke_mm",10));out.extend([_iface("mount","mount_face",position=(0,0,-z/2),axis=(0,0,-1),mate=["solenoid_mount"],required=True),_iface("plunger","linear_output",position=(0,0,z/2),axis=(0,0,1),gender="male",mate=["linkage","push_surface"],required=True,metadata={"stroke_mm":stroke,"force_n":c.get("force_n")}),_iface("coil","electrical_load",position=(x/2,0,0),axis=(1,0,0),mate=["switched_power"],required=True,metadata={"voltage_v":c.get("voltage_v",12),"duty_cycle":c.get("duty_cycle",1.0)})])
    elif cat=="fan":
        out.extend([_iface("mount","mount_face",position=(0,0,-z/2),axis=(0,0,-1),mate=["fan_mount"],required=True),_iface("air_in","airflow",position=(0,0,-z/2),axis=(0,0,1),gender="input",mate=["airflow"],metadata={"cfm":c.get("airflow_cfm")}),_iface("air_out","airflow",position=(0,0,z/2),axis=(0,0,1),gender="output",mate=["airflow"],metadata={"cfm":c.get("airflow_cfm")}),_iface("power","electrical_load",position=(x/2,0,0),axis=(1,0,0),mate=["power_output"],required=True,metadata={"voltage_v":c.get("voltage_v",12)})])
    elif cat=="linear_motion":out.extend([_iface("rail_mount","mount_face",position=(0,0,-z/2),axis=(0,0,-1),mate=["linear_rail_mount"],required=True),_iface("carriage","linear_output",position=(0,0,z/2),axis=(1,0,0),mate=["moving_platform"],required=True,metadata={"travel_mm":c.get("travel_mm")})])
    elif cat in {"compute","microcontroller"}:
        out.append(_iface("board_mount","mount_pattern",position=(0,0,-z/2),axis=(0,0,-1),mate=["board_standoffs","mount_hole"],required=True,metadata={"pattern_mm":c.get("mounting_pattern_mm"),"hole_diameter_mm":c.get("mount_hole_diameter_mm")}));out.append(_iface("power","electrical_power_input",position=(-x/2,-y/3,0),axis=(-1,0,0),gender="input",mate=["power_output"],required=True,metadata={"voltage_v":c.get("voltage_v",5),"power_w":c.get("power_w")}))
        if c.get("programmable"):out.append(_iface("gpio","digital_io",position=(0,y/2,z/4),axis=(0,1,0),gender="bidirectional",mate=["digital_io","pwm_output","i2c","spi","uart"],metadata={"logic_voltage_v":3.3}))
    elif cat=="sensor":out.extend([_iface("mount","mount_face",position=(0,0,-z/2),axis=(0,0,-1),mate=["sensor_mount"]),_iface("bus","digital_io",position=(x/2,0,0),axis=(1,0,0),mate=["i2c","spi","digital_io"],required=True,metadata={"voltage_v":c.get("voltage_v",3.3)})])
    elif cat=="battery":out.append(_iface("power","electrical_power_output",position=(x/2,0,0),axis=(1,0,0),gender="output",mate=["power_input","power_converter"],required=True,metadata={"voltage_v":c.get("voltage_v"),"energy_wh":c.get("energy_wh")}))
    elif cat=="power":out.extend([_iface("input","electrical_power_input",position=(-x/2,0,0),axis=(-1,0,0),gender="input",mate=["power_output"],required=True,metadata={"max_voltage_v":c.get("input_max_v",36)}),_iface("output","electrical_power_output",position=(x/2,0,0),axis=(1,0,0),gender="output",mate=["power_input","electrical_load"],required=True,metadata={"voltage_v":c.get("output_v",5),"max_current_a":c.get("max_current_a")})])
    return out


def _normalize_legacy(c:dict[str,Any])->dict[str,Any]:
    identity={"id":str(c.get("id") or f"legacy.{_slug(c.get('name','component'))}"),"category":str(c.get("category") or "custom"),"manufacturer":str(c.get("manufacturer") or "Unknown"),"model":str(c.get("model") or c.get("name") or "Component"),"name":str(c.get("name") or f"{c.get('manufacturer','Unknown')} {c.get('model','Component')}").strip(),"revision":str(c.get("revision") or "unspecified")}
    dims=[float(x) for x in list(c.get("dimensions_mm") or [20,20,20])[:3]]
    while len(dims)<3:dims.append(10.0)
    specs={k:deepcopy(v) for k,v in c.items() if k not in {"id","category","manufacturer","model","name","tags","dimensions_mm","material","geometry_profile","mechanical_source","official_step_available"}}
    source_kind="manufacturer" if c.get("mechanical_source") else "legacy_estimate";provenance=[_source(source_kind,c.get("mechanical_source"),"mechanical/source data" if c.get("mechanical_source") else "ForgeCAD v1 legacy catalog")];geometry=_default_geometry(c)
    if c.get("mechanical_source"):geometry["source"]=provenance[0]
    if c.get("official_step_available"):geometry["official_asset_expected"]=True
    return {"schema_version":SCHEMA_VERSION,**identity,"tags":sorted({str(x).lower() for x in c.get("tags",[])}),"dimensions_mm":dims,"mass_g":float(c["mass_g"]) if c.get("mass_g") is not None else None,"material":c.get("material"),"specs":specs,"geometry":geometry,"interfaces":_default_interfaces(c),"keepouts":[],"procurement":{"status":"catalog","unit_cost_usd":c.get("unit_cost_usd"),"supplier":c.get("supplier"),"sku":c.get("sku"),"url":c.get("procurement_url")},"software":{"programmable":bool(c.get("programmable")),"platform":c.get("code_platform")},"provenance":provenance,"trust_score":TRUST_RANK[source_kind],"legacy":deepcopy(c)}


ENRICHMENTS={
 "compute.raspberry_pi_5_8gb":{"manufacturer_part_number":"SC1112","geometry":{"preferred":"official_step","fidelity":"detailed_parametric","profile":"raspberry_pi_5","official_asset_expected":True,"source":_source("manufacturer","https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf","Raspberry Pi 5 mechanical drawing")},"interfaces":[_iface("mount","mount_pattern",position=(0,0,-.8),axis=(0,0,-1),mate=["board_standoffs","mount_hole"],required=True,metadata={"pattern_mm":[58,49],"hole_diameter_mm":2.7,"fastener":"M2.5"}),_iface("gpio40","digital_io",position=(-5,24.2,5.3),axis=(0,1,0),gender="bidirectional",mate=["digital_io","pwm_output","i2c","spi","uart"],metadata={"pins":40,"pitch_mm":2.54,"logic_voltage_v":3.3}),_iface("usb_c_power","electrical_power_input",position=(-31,-29.3,2.5),axis=(0,-1,0),gender="input",standard="USB-C",mate=["usb_c_source","power_output"],required=True,metadata={"voltage_v":5,"recommended_current_a":5}),_iface("pcie_fpc","pcie",position=(17.5,-23.5,2.35),axis=(0,-1,0),mate=["pcie"],metadata={"lanes":1}),_iface("fan_header","fan_power",position=(25,23,2.45),axis=(0,1,0),mate=["fan"],metadata={"pins":4})],"provenance":[_source("manufacturer","https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf","Mechanical drawing"),_source("manufacturer","https://www.raspberrypi.com/products/raspberry-pi-5/","Product specification")],"trust_score":100},
 "servo.sg90":{"interfaces":[_iface("mount","servo_mount",position=(0,0,-14.5),axis=(0,0,-1),mate=["mount_face"],required=True),_iface("spline","rotary_output",position=(0,0,14.5),axis=(0,0,1),gender="male",mate=["servo_horn"],required=True),_iface("pwm","servo_signal",position=(0,-6,-5),axis=(0,-1,0),mate=["pwm_output"],required=True,metadata={"nominal_voltage_v":5})]},
 "servo.mg996r":{"interfaces":[_iface("mount","servo_mount",position=(0,0,-22),axis=(0,0,-1),mate=["mount_face"],required=True),_iface("spline","rotary_output",position=(0,0,22),axis=(0,0,1),gender="male",mate=["servo_horn"],required=True),_iface("pwm","servo_signal",position=(0,-10,-7),axis=(0,-1,0),mate=["pwm_output"],required=True,metadata={"nominal_voltage_v":6})]}
}


def validate_component(item:dict[str,Any])->None:
    missing=[k for k in ("id","category","manufacturer","model","name","geometry","interfaces") if k not in item]
    if missing:raise ValueError(f"Component missing required fields: {', '.join(missing)}")
    dims=item.get("dimensions_mm")
    if not isinstance(dims,list) or len(dims)!=3 or any(float(x)<=0 for x in dims):raise ValueError("dimensions_mm must contain three positive numbers")
    ids=set()
    for interface in item.get("interfaces",[]):
        iid=str(interface.get("id") or "")
        if not iid or iid in ids:raise ValueError(f"Component {item['id']} has invalid/duplicate interface id {iid!r}")
        ids.add(iid);p=interface.get("position_mm",[0,0,0]);a=interface.get("axis",[0,0,1])
        if len(p)!=3 or len(a)!=3:raise ValueError(f"Interface {iid} requires 3D position and axis")
        if math.sqrt(sum(float(x)**2 for x in a))<1e-9:raise ValueError(f"Interface {iid} axis cannot be zero")
    fidelity=item.get("geometry",{}).get("fidelity","none")
    if fidelity not in GEOMETRY_RANK:raise ValueError(f"Unknown geometry fidelity: {fidelity}")


def _normalize_custom(raw:dict[str,Any],source_kind:str="user_supplied")->dict[str,Any]:
    if not isinstance(raw,dict):raise ValueError("Component must be a JSON object")
    cid=str(raw.get("id") or "").strip()
    if not cid:cid=f"custom.{_slug(str(raw.get('manufacturer') or 'custom'))}.{_slug(str(raw.get('model') or raw.get('name') or 'component'))}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+",cid):raise ValueError(f"Invalid component id: {cid}")
    if raw.get("schema_version")==SCHEMA_VERSION and raw.get("geometry") is not None:item=deepcopy(raw);item["id"]=cid
    else:legacy=deepcopy(raw);legacy["id"]=cid;item=_normalize_legacy(legacy)
    item.setdefault("schema_version",SCHEMA_VERSION);item.setdefault("category","custom");item.setdefault("manufacturer","Custom");item.setdefault("model",item.get("name",cid));item.setdefault("name",f"{item['manufacturer']} {item['model']}");item.setdefault("tags",[]);item.setdefault("dimensions_mm",[20.0,20.0,20.0]);item.setdefault("specs",{});item.setdefault("geometry",_default_geometry(item));item.setdefault("interfaces",_default_interfaces(item));item.setdefault("keepouts",[]);item.setdefault("procurement",{});item.setdefault("software",{"programmable":False,"platform":None});item.setdefault("provenance",[_source(source_kind,notes="Imported into local ForgeCAD registry")]);item.setdefault("trust_score",TRUST_RANK.get(source_kind,0));validate_component(item);return item

_BUILTIN={};_CUSTOM={}
def _load_builtin():
    _BUILTIN.clear()
    for legacy in legacy_components.REGISTRY:
        item=_deep_merge(_normalize_legacy(legacy),ENRICHMENTS.get(legacy["id"],{}));validate_component(item);_BUILTIN[item["id"]]=item
    # Specific manufacturer-sourced parts override generic envelope choices only by ID, never silently.
    for raw in curated_catalog.CATALOG:
        item=_normalize_custom(raw,"manufacturer");validate_component(item);_BUILTIN[item["id"]]=item

def _load_custom():
    _CUSTOM.clear()
    if not CUSTOM_PATH.exists():return
    try:
        payload=json.loads(CUSTOM_PATH.read_text(encoding="utf-8"));items=payload if isinstance(payload,list) else payload.get("components",[])
        for raw in items:
            item=_normalize_custom(raw,"user_supplied");_CUSTOM[item["id"]]=item
    except Exception:return

def _persist_custom():
    tmp=CUSTOM_PATH.with_suffix(".tmp");tmp.write_text(json.dumps({"schema_version":SCHEMA_VERSION,"components":list(_CUSTOM.values())},indent=2),encoding="utf-8");tmp.replace(CUSTOM_PATH)
def reload_registry():_load_builtin();_load_custom()
def _all_map():return {**_BUILTIN,**_CUSTOM}
def all_components(category:str|None=None):
    category=CATEGORY_ALIASES.get(str(category),str(category)) if category else None;vals=list(_all_map().values());return [deepcopy(x) for x in vals if not category or x["category"]==category]
def component_by_id(cid:str):
    try:return deepcopy(_all_map()[cid])
    except KeyError:raise KeyError(cid) from None
def categories():return sorted({x["category"] for x in _all_map().values()})

def registry_stats():
    vals=list(_all_map().values());by_fidelity={};by_trust={}
    for c in vals:
        f=str(c.get("geometry",{}).get("fidelity","none"));by_fidelity[f]=by_fidelity.get(f,0)+1;trust=str((c.get("provenance") or [{}])[0].get("kind","unknown"));by_trust[trust]=by_trust.get(trust,0)+1
    return {"schema_version":SCHEMA_VERSION,"total":len(vals),"builtin":len(_BUILTIN),"custom":len(_CUSTOM),"categories":categories(),"geometry_fidelity":by_fidelity,"provenance":by_trust}

def component_schema():return {"$schema":"https://json-schema.org/draft/2020-12/schema","title":"ForgeCAD real-world component","type":"object","required":["id","category","manufacturer","model","name","dimensions_mm","geometry","interfaces"],"properties":{"schema_version":{"const":SCHEMA_VERSION},"id":{"type":"string","pattern":"^[A-Za-z0-9_.-]+$"},"category":{"type":"string"},"manufacturer":{"type":"string"},"model":{"type":"string"},"manufacturer_part_number":{"type":["string","null"]},"dimensions_mm":{"type":"array","minItems":3,"maxItems":3},"geometry":{"type":"object"},"interfaces":{"type":"array"},"specs":{"type":"object"},"procurement":{"type":"object"},"provenance":{"type":"array"}}}

def _field(c,name):
    if name in c:return c[name]
    if name in c.get("specs",{}):return c["specs"][name]
    return c.get("procurement",{}).get(name)
def _constraint(c,key,target):
    if target is None:return True,0.0,"ignored"
    op="eq";field=key
    if key.startswith("max_"):op,field="max",key[4:]
    elif key.startswith("min_"):op,field="min",key[4:]
    value=_field(c,field)
    if value is None:return False,1e4,f"missing {field}"
    try:fv,ft=float(value),float(target)
    except (TypeError,ValueError):ok=value==target;return ok,0.0 if ok else 1.0,f"{field}={value!r}"
    if op=="max":ok=fv<=ft;p=max(0.0,(fv-ft)/(abs(ft)+1e-9))
    elif op=="min":ok=fv>=ft;p=max(0.0,(ft-fv)/(abs(ft)+1e-9))
    else:ok=math.isclose(fv,ft,rel_tol=1e-9,abs_tol=1e-9);p=abs(fv-ft)/(abs(ft)+1e-9)
    return ok,p,f"{field}={value}"
def _search_blob(c):return " ".join([c.get("id",""),c.get("category",""),c.get("manufacturer",""),c.get("model",""),c.get("name","")," ".join(c.get("tags",[])),json.dumps(c.get("specs",{}),sort_keys=True)," ".join(str(i.get("kind","")) for i in c.get("interfaces",[]))]).lower()

def search_components(query:str="",category:str|None=None,constraints:dict[str,Any]|None=None,weights:dict[str,float]|None=None,limit:int=20,include_infeasible:bool=True,min_trust:int=0,min_geometry_fidelity:str|None=None):
    tokens=[x for x in re.split(r"\s+",query.lower().strip()) if x];category=CATEGORY_ALIASES.get(str(category),str(category)) if category else None;constraints=constraints or {};weights=weights or {};min_geom_rank=GEOMETRY_RANK.get(min_geometry_fidelity or "none",0);rows=[]
    for c in _all_map().values():
        if category and c["category"]!=category:continue
        if int(c.get("trust_score",0))<int(min_trust):continue
        geom_rank=GEOMETRY_RANK.get(str(c.get("geometry",{}).get("fidelity","none")),0)
        if geom_rank<min_geom_rank:continue
        blob=_search_blob(c)
        if tokens and not all(tok in blob for tok in tokens):continue
        feasible=True;penalty=0.0;reasons=[]
        for key,target in constraints.items():ok,p,reason=_constraint(c,key,target);feasible=feasible and ok;penalty+=p*float(weights.get(key,1.0));reasons.extend([reason] if not ok else [])
        if not feasible and not include_infeasible:continue
        text_score=sum(blob.count(tok) for tok in tokens) if tokens else 0;rank=(1000 if feasible else 0)-penalty*100+text_score*4+int(c.get("trust_score",0))/100*3+geom_rank/100*2;rows.append((-rank,c["name"],c,feasible,penalty,reasons))
    rows.sort(key=lambda x:(x[0],x[1]));results=[]
    for _,_,c,feasible,penalty,reasons in rows[:max(1,min(int(limit),200))]:results.append(deepcopy(c)|{"feasible":feasible,"constraint_penalty":penalty,"constraint_failures":reasons})
    return {"query":query,"category":category,"count":len(results),"total_registry":len(_all_map()),"results":results}

def select_component(requirements:dict[str,Any],*,category:str|None=None,query:str="",limit:int=8):
    result=search_components(query,category,requirements,{},limit,True);ranked=[]
    for c in result["results"]:ranked.append({"component":c,"recommended":bool(c.get("feasible")),"why":"meets all stated constraints" if c.get("feasible") else "violates or lacks one or more stated constraints","geometry_fidelity":c.get("geometry",{}).get("fidelity"),"trust_score":c.get("trust_score",0),"failures":c.get("constraint_failures",[])})
    return {"requirements":deepcopy(requirements),"category":category,"query":query,"ranked":ranked,"best":ranked[0] if ranked else None}

def interface_by_id(component,interface_id):
    for interface in component.get("interfaces",[]):
        if interface.get("id")==interface_id:return deepcopy(interface)
    raise KeyError(interface_id)
def _kind_compatible(a,b):
    ak,bk=str(a.get("kind","")),str(b.get("kind",""));am=set(a.get("mate",[]));bm=set(b.get("mate",[]));return ak==bk or bk in am or ak in bm

def interface_compatibility(a,b):
    reasons=[];compatible=_kind_compatible(a,b)
    if not compatible:reasons.append(f"interface kinds do not mate: {a.get('kind')} ↔ {b.get('kind')}")
    ag,bg=a.get("gender","neutral"),b.get("gender","neutral")
    if ag==bg and ag in {"male","female","input","output"}:compatible=False;reasons.append(f"interface genders are both {ag}")
    am,bm=a.get("metadata",{}),b.get("metadata",{});av=am.get("voltage_v") or am.get("nominal_voltage_v");bv=bm.get("voltage_v") or bm.get("nominal_voltage_v")
    if av is not None and bv is not None and abs(float(av)-float(bv))>max(.25,.05*max(abs(float(av)),abs(float(bv)))):compatible=False;reasons.append(f"voltage mismatch {av} V ↔ {bv} V")
    ad,bd=am.get("diameter_mm"),bm.get("diameter_mm")
    if ad is not None and bd is not None and abs(float(ad)-float(bd))>.25:compatible=False;reasons.append(f"diameter mismatch {ad} mm ↔ {bd} mm")
    return {"compatible":compatible,"reasons":reasons or ["compatible interface types and constraints"]}
def compatible_interfaces(component_a,component_b):
    a,b=component_by_id(component_a),component_by_id(component_b);out=[]
    for ia in a.get("interfaces",[]):
        for ib in b.get("interfaces",[]):
            r=interface_compatibility(ia,ib)
            if r["compatible"]:out.append({"a":ia,"b":ib,**r})
    return out

def component_snapshot(cid):
    snap={k:deepcopy(v) for k,v in component_by_id(cid).items() if k!="legacy"}
    for asset in snap.get("geometry",{}).get("assets",[]):asset.pop("path",None)
    return snap

def resolve_asset_path(asset):
    rel=asset.get("relative_path")
    if rel:
        p=(ASSET_DIR/str(rel)).resolve()
        try:p.relative_to(ASSET_DIR.resolve())
        except ValueError:return None
        return p
    old=asset.get("path")
    if old:
        p=Path(str(old));return p if p.is_file() else None
    return None
def make_project_object(cid:str,*,name:str|None=None,transform:dict[str,Any]|None=None):
    c=component_by_id(cid);dims=c.get("dimensions_mm",[20,20,20]);obj={"name":name or c["name"],"kind":"component","params":{"x":float(dims[0]),"y":float(dims[1]),"z":float(dims[2])},"material":c.get("material") or "abs","component_ref":c["id"],"component_snapshot":component_snapshot(cid),"interfaces":deepcopy(c.get("interfaces",[])),"semantic":{"role":c.get("category"),"tags":deepcopy(c.get("tags",[])),"geometry_fidelity":c.get("geometry",{}).get("fidelity"),"trust_score":c.get("trust_score",0),"manufacturer":c.get("manufacturer"),"model":c.get("model")}}
    if transform:obj["transform"]=deepcopy(transform)
    if c.get("software",{}).get("programmable"):
        platform=c.get("software",{}).get("platform") or "generic";ext="ino" if "arduino" in platform else "py";entry=f"main.{ext}";obj["code"]={"platform":platform,"entrypoint":entry,"files":{entry:"# ForgeCAD embedded component workspace\n\ndef main():\n    pass\n" if ext=="py" else "// ForgeCAD embedded component workspace\nvoid setup() {}\nvoid loop() {}\n","README.md":f"# {c['name']}\n\nCode is versioned with the physical design branch.\n"}}
    return obj
def bom_item(cid,qty=1):
    c=component_by_id(cid);p=c.get("procurement",{});return {"component_ref":cid,"manufacturer":c.get("manufacturer"),"model":c.get("model"),"mpn":c.get("manufacturer_part_number"),"description":c.get("name"),"qty":int(qty),"unit_cost_usd":p.get("unit_cost_usd") or 0,"supplier":p.get("supplier"),"supplier_sku":p.get("sku"),"procurement_url":p.get("url"),"source_trust":c.get("trust_score",0)}

def _refresh_compat_registry():
    global REGISTRY
    if "REGISTRY" in globals():REGISTRY[:]=list(_all_map().values())

def import_components(payload,*,replace=True,source_kind="user_supplied"):
    items=payload.get("components",[]) if isinstance(payload,dict) and "components" in payload else (payload if isinstance(payload,list) else [payload]);added=[]
    for raw in items:
        item=_normalize_custom(raw,source_kind)
        if item["id"] in _BUILTIN and not replace:raise ValueError(f"Cannot replace built-in component {item['id']}")
        _CUSTOM[item["id"]]=item;added.append(deepcopy(item))
    _persist_custom();_refresh_compat_registry();return {"ok":True,"added":added,"total_registry":len(_all_map())}
def _safe_asset_name(name):
    base=Path(name).name
    if not base or base in {".",".."}:raise ValueError("Invalid asset name")
    return re.sub(r"[^A-Za-z0-9_.-]+","_",base)
def register_asset_bytes(cid,filename,data,*,role="geometry",source_kind="user_supplied",source_url=None):
    if len(data)>250*1024*1024:raise ValueError("Component asset exceeds 250 MB")
    component=component_by_id(cid);digest=hashlib.sha256(data).hexdigest();ext=Path(filename).suffix.lower()
    if role=="geometry" and ext not in {".step",".stp",".iges",".igs",".stl",".obj",".3mf"}:raise ValueError(f"Unsupported geometry asset type: {ext}")
    folder=ASSET_DIR/_slug(cid);folder.mkdir(parents=True,exist_ok=True);out=folder/f"{digest[:16]}_{_safe_asset_name(filename)}";out.write_bytes(data);rel=str(out.relative_to(ASSET_DIR)).replace("\\","/");asset={"id":digest[:16],"role":role,"filename":filename,"relative_path":rel,"sha256":digest,"bytes":len(data),"format":ext.lstrip("."),"source":_source(source_kind,source_url)};component.setdefault("geometry",{}).setdefault("assets",[]).append(asset)
    if role=="geometry" and ext in {".step",".stp"}:component["geometry"].update({"preferred":"step_asset","fidelity":"official_step" if source_kind=="manufacturer" else "verified_step","trust":source_kind})
    _CUSTOM[cid]=component;_persist_custom();_refresh_compat_registry();return {"ok":True,"component":component,"asset":asset}
def import_catalog_pack_bytes(filename,data):
    if len(data)>300*1024*1024:raise ValueError("Catalog pack exceeds 300 MB")
    if filename.lower().endswith(".json"):return import_components(json.loads(data.decode("utf-8")))
    if not filename.lower().endswith(".zip"):raise ValueError("Catalog pack must be JSON or ZIP")
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);pack=root/"pack.zip";pack.write_bytes(data)
        with zipfile.ZipFile(pack) as z:
            for info in z.infolist():
                p=Path(info.filename)
                if p.is_absolute() or ".." in p.parts:raise ValueError("Catalog pack contains unsafe path")
            z.extractall(root/"unpacked")
        unpacked=root/"unpacked";manifests=[p for p in (unpacked/"manifest.json",unpacked/"components.json") if p.exists()]
        if not manifests:raise ValueError("Catalog ZIP requires manifest.json or components.json")
        manifest=json.loads(manifests[0].read_text(encoding="utf-8"));result=import_components(manifest);assets=[];asset_map=manifest.get("assets",{}) if isinstance(manifest,dict) else {}
        for cid,entries in asset_map.items():
            for entry in entries if isinstance(entries,list) else [entries]:
                rel=Path(str(entry.get("path") if isinstance(entry,dict) else entry));asset_path=(unpacked/rel).resolve()
                if unpacked.resolve() not in asset_path.parents or not asset_path.is_file():raise ValueError(f"Invalid component asset path: {rel}")
                role=entry.get("role","geometry") if isinstance(entry,dict) else "geometry";source_kind=entry.get("source_kind","user_supplied") if isinstance(entry,dict) else "user_supplied";assets.append(register_asset_bytes(cid,asset_path.name,asset_path.read_bytes(),role=role,source_kind=source_kind))
        return {**result,"assets_imported":len(assets)}
def delete_custom_component(cid):
    if cid not in _CUSTOM:raise KeyError(cid)
    del _CUSTOM[cid];_persist_custom();_refresh_compat_registry();return {"ok":True,"id":cid,"total_registry":len(_all_map())}
def provider_status():return {"providers":[],"offline_registry":registry_stats(),"note":"v1.1 uses deterministic local component data and accepts manufacturer/distributor catalog packs. Live supplier adapters remain an optional boundary."}
def search_provider(provider,query,limit=25,import_results=False):raise RuntimeError(f"Live supplier provider {provider!r} is not configured")

reload_registry()
REGISTRY=list(_all_map().values())
