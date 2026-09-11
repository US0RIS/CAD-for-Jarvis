from __future__ import annotations

import json, math, os, re, threading, uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cadquery as cq
from . import component_registry
from . import physical_components
from . import system_validation

APP_VERSION = "2.1.0"
DATA_DIR = Path(os.environ.get("FORGECAD_DATA_DIR") or (Path.home()/".forgecad"))
PROJECTS = DATA_DIR / "projects"
EXPORTS = DATA_DIR / "exports"
PROJECTS.mkdir(parents=True, exist_ok=True); EXPORTS.mkdir(parents=True, exist_ok=True)
STATE_PATH = PROJECTS / "active.forgecad.json"
LOCK = threading.RLock()

MATERIALS: dict[str, dict[str, Any]] = {
    "aluminum_6061_t6": {"name":"Aluminum 6061-T6","density_kg_m3":2700,"youngs_modulus_gpa":68.9,"yield_mpa":276,"poisson":0.33,"thermal_w_mk":167,"specific_heat_j_kgk":896,"color":"#aeb7c2"},
    "aluminum_7075_t6": {"name":"Aluminum 7075-T6","density_kg_m3":2810,"youngs_modulus_gpa":71.7,"yield_mpa":503,"poisson":0.33,"thermal_w_mk":130,"specific_heat_j_kgk":960,"color":"#9ea9b8"},
    "steel_1018": {"name":"Steel 1018","density_kg_m3":7870,"youngs_modulus_gpa":205,"yield_mpa":370,"poisson":0.29,"thermal_w_mk":51.9,"specific_heat_j_kgk":486,"color":"#838b93"},
    "steel_304": {"name":"Stainless Steel 304","density_kg_m3":8000,"youngs_modulus_gpa":193,"yield_mpa":215,"poisson":0.29,"thermal_w_mk":16.2,"specific_heat_j_kgk":500,"color":"#b7bdc5"},
    "ti_6al_4v": {"name":"Ti-6Al-4V","density_kg_m3":4430,"youngs_modulus_gpa":114,"yield_mpa":880,"poisson":0.34,"thermal_w_mk":6.7,"specific_heat_j_kgk":526,"color":"#8f949b"},
    "abs": {"name":"ABS","density_kg_m3":1040,"youngs_modulus_gpa":2.1,"yield_mpa":40,"poisson":0.35,"thermal_w_mk":0.18,"specific_heat_j_kgk":1300,"color":"#313840"},
    "petg": {"name":"PETG","density_kg_m3":1270,"youngs_modulus_gpa":2.0,"yield_mpa":50,"poisson":0.38,"thermal_w_mk":0.20,"specific_heat_j_kgk":1200,"color":"#697783"},
    "pa12": {"name":"PA12 Nylon","density_kg_m3":1010,"youngs_modulus_gpa":1.7,"yield_mpa":45,"poisson":0.39,"thermal_w_mk":0.23,"specific_heat_j_kgk":1700,"color":"#9d9486"},
    "pcb_fr4": {"name":"FR-4 PCB","density_kg_m3":1850,"youngs_modulus_gpa":22.0,"yield_mpa":120,"poisson":0.14,"thermal_w_mk":0.30,"specific_heat_j_kgk":1100,"color":"#187a3b"},
}


def now() -> str: return datetime.now(timezone.utc).isoformat()
def uid() -> str: return str(uuid.uuid4())
def _safe(v: str) -> str: return re.sub(r"[^A-Za-z0-9_.-]+","-",v).strip("-") or "design"


def _transform() -> dict[str, list[float]]:
    return {"position":[0.0,0.0,0.0],"rotation_deg":[0.0,0.0,0.0],"scale":[1.0,1.0,1.0]}


def default_project() -> dict[str, Any]:
    base_id=uid(); pi_id=uid()
    return {
        "schema": 4, "version": APP_VERSION, "name":"ForgeCAD Project", "created_at":now(), "updated_at":now(),
        "objects":[
            {"id":base_id,"name":"Raspberry Pi 5 Mounting Plate","kind":"mounting_plate","params":{"x":105.0,"y":76.0,"thickness":3.0,"corner_radius":4.0,"mount_x":58.0,"mount_y":49.0,"mount_hole_diameter":2.7,"standoff_od":6.0,"standoff_height":6.0,"chassis_hole_diameter":4.0},"material":"aluminum_6061_t6","transform":_transform(),"features":[],"semantic":{"role":"structural_base","tags":["machined","reference","raspberry-pi-5","m2.5"],"description":"Machined Raspberry Pi 5 mounting plate with 58 x 49 mm M2.5 standoff pattern and corner chassis holes."},"visible":True},
            {"id":pi_id,"name":"Raspberry Pi 5 8GB","kind":"component","params":{"x":85.0,"y":56.0,"z":17.0},"material":"pcb_fr4","transform":{"position":[0.0,0.0,6.8],"rotation_deg":[0.0,0.0,0.0],"scale":[1.0,1.0,1.0]},"features":[],"semantic":{"role":"embedded_compute","tags":["electronics","programmable","raspberry-pi-5","physical-geometry"],"description":"Raspberry Pi 5 8GB physical-layout model with PCB, mounting holes, I/O connectors, GPIO and major packages.","mechanical_source":"https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf","geometry_fidelity":"mechanical-envelope-detailed"},"component_ref":"compute.raspberry_pi_5_8gb","component_snapshot":component_registry.component_snapshot("compute.raspberry_pi_5_8gb"),"interfaces":component_registry.component_by_id("compute.raspberry_pi_5_8gb").get("interfaces",[]),"code":{"platform":"python/linux","entrypoint":"main.py","files":{"main.py":"from time import sleep\n\n\ndef main():\n    print('ForgeCAD device online')\n    while True:\n        sleep(1)\n\nif __name__ == '__main__':\n    main()\n","README.md":"# Raspberry Pi workspace\n\nEdit and version device code together with the mechanical design.\n"}},"visible":True},
        ],
        "joints":[], "loads":[], "constraints":[], "requirements":[], "bom":[component_registry.bom_item("compute.raspberry_pi_5_8gb")], "connections":[], "simulations":[], "notebook":[],
        "settings":{"ollama_model":os.environ.get("FORGECAD_OLLAMA_MODEL","qwen3:8b"),"units":"mm","coordinate_system":"Z-up"},
        "ledger":[],
    }


def _snap(project: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(project)

PROJECT: dict[str, Any] = default_project()
BRANCHES: dict[str, dict[str, Any]] = {"main":_snap(PROJECT)}
DESIGNS: dict[str, dict[str, Any]] = {"main":{"name":"main","parent":None,"status":"working","note":"Initial baseline","physical_verified":False,"created_at":now(),"updated_at":now()}}
ACTIVE_DESIGN = "main"
HISTORY: list[dict[str, Any]]=[]
REDO: list[dict[str, Any]]=[]


def _serialize() -> dict[str, Any]:
    BRANCHES[ACTIVE_DESIGN]=_snap(PROJECT)
    return {"active":ACTIVE_DESIGN,"project":PROJECT,"branches":BRANCHES,"designs":DESIGNS}

def persist() -> None:
    with LOCK:
        PROJECT["updated_at"]=now()
        tmp=STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_serialize(),indent=2),encoding="utf-8")
        tmp.replace(STATE_PATH)

def load() -> None:
    global ACTIVE_DESIGN
    if not STATE_PATH.exists(): return
    try:
        data=json.loads(STATE_PATH.read_text(encoding="utf-8")); p=data.get("project")
        if not isinstance(p,dict) or "objects" not in p: return
        PROJECT.clear(); PROJECT.update(upgrade_project(p))
        BRANCHES.clear(); BRANCHES.update({k:upgrade_project(v) for k,v in (data.get("branches") or {}).items() if isinstance(v,dict)})
        DESIGNS.clear(); DESIGNS.update(data.get("designs") or {})
        ACTIVE_DESIGN=str(data.get("active") or "main")
        if ACTIVE_DESIGN not in DESIGNS: DESIGNS[ACTIVE_DESIGN]={"name":ACTIVE_DESIGN,"parent":None,"status":"unknown","note":"","physical_verified":False,"created_at":now(),"updated_at":now()}
        BRANCHES[ACTIVE_DESIGN]=_snap(PROJECT)
    except Exception:
        return

def upgrade_project(p: dict[str, Any]) -> dict[str, Any]:
    q=deepcopy(p); q["schema"]=max(4,int(q.get("schema",0) or 0)); q["version"]=APP_VERSION; q.setdefault("name","ForgeCAD Project")
    for k,default in (("objects",[]),("joints",[]),("loads",[]),("constraints",[]),("requirements",[]),("bom",[]),("connections",[]),("simulations",[]),("notebook",[]),("ledger",[])): q.setdefault(k,deepcopy(default))
    q.setdefault("settings",{"ollama_model":"qwen3:8b","units":"mm"})
    for o in q["objects"]:
        o.setdefault("id",uid());o.setdefault("features",[]);o.setdefault("transform",_transform());o.setdefault("material","aluminum_6061_t6");o.setdefault("semantic",{});o.setdefault("visible",True)
        if o.get("component_ref"):
            try:
                snap=component_registry.component_snapshot(str(o["component_ref"]));o.setdefault("component_snapshot",snap);o.setdefault("interfaces",deepcopy(snap.get("interfaces",[])))
            except KeyError: pass
    # Legacy projects did not automatically put purchased component instances in the BOM.
    bom_refs={x.get("component_ref") for x in q.get("bom",[])}
    for o in q["objects"]:
        if o.get("component_ref") and o.get("component_ref") not in bom_refs:
            try:q["bom"].append(component_registry.bom_item(str(o["component_ref"])))
            except KeyError:pass
    return q

def reset_project() -> dict[str, Any]:
    global ACTIVE_DESIGN
    with LOCK:
        PROJECT.clear(); PROJECT.update(default_project()); BRANCHES.clear(); DESIGNS.clear(); ACTIVE_DESIGN="main"
        BRANCHES["main"]=_snap(PROJECT); DESIGNS["main"]={"name":"main","parent":None,"status":"working","note":"Reset baseline","physical_verified":False,"created_at":now(),"updated_at":now()}
        HISTORY.clear(); REDO.clear(); push_history("reset project","human","reset canonical project"); return PROJECT


def object_by_id(object_id: str) -> dict[str, Any]:
    for o in PROJECT["objects"]:
        if o.get("id")==object_id: return o
    raise KeyError(f"Object not found: {object_id}")


def _rounded_box_xy(x: float, y: float, z: float, radius: float=0.0, center_z: float=0.0):
    wp=cq.Workplane("XY").workplane(offset=center_z-z/2).box(x,y,z,centered=(True,True,False))
    if radius>0:
        try: wp=wp.edges("|Z").fillet(min(radius,x/2-0.01,y/2-0.01))
        except Exception: pass
    return wp.val()


def _mounting_plate_shape(obj: dict[str, Any]):
    p=obj.get("params") or {}
    x=float(p.get("x",105)); y=float(p.get("y",76)); t=float(p.get("thickness",3)); r=float(p.get("corner_radius",4))
    mx=float(p.get("mount_x",58)); my=float(p.get("mount_y",49)); hd=float(p.get("mount_hole_diameter",2.7)); sod=float(p.get("standoff_od",6)); sh=float(p.get("standoff_height",6)); chd=float(p.get("chassis_hole_diameter",4))
    plate=_rounded_box_xy(x,y,t,r,center_z=-t/2)
    mount_pts=[(-mx/2,-my/2),(mx/2,-my/2),(mx/2,my/2),(-mx/2,my/2)]
    standoffs=[]
    for px,py in mount_pts:
        st=cq.Workplane("XY").center(px,py).circle(sod/2).circle(hd/2).extrude(sh).val(); standoffs.append(st)
    shape=cq.Compound.makeCompound([plate,*standoffs])
    for px,py in mount_pts:
        tool=cq.Workplane("XY").workplane(offset=-t-0.5).center(px,py).circle(hd/2).extrude(t+sh+1).val(); shape=shape.cut(tool)
    for px,py in [(-x/2+8,-y/2+8),(x/2-8,-y/2+8),(x/2-8,y/2-8),(-x/2+8,y/2-8)]:
        tool=cq.Workplane("XY").workplane(offset=-t-0.5).center(px,py).circle(chd/2).extrude(t+1).val(); shape=shape.cut(tool)
    return shape


def _pi5_local_parts() -> list[tuple[Any,str]]:
    # Board and mounting data follow Raspberry Pi's published Pi 5 mechanical drawing.
    parts=[]
    board=_rounded_box_xy(85,56,1.6,3,0)
    for px,py in [(-29,-24.5),(29,-24.5),(29,24.5),(-29,24.5)]:
        tool=cq.Workplane("XY").workplane(offset=-1).center(px,py).circle(1.35).extrude(2).val(); board=board.cut(tool)
    parts.append((board,"#16813e"))
    parts += [
        (_rounded_box_xy(17.2,17.2,1.7,0.6,1.65).translate((-8,-1,0)),"#202327"),
        (_rounded_box_xy(12.5,12.5,1.4,0.4,1.5).translate((11,2,0)),"#24272b"),
        (_rounded_box_xy(7,7,1.2,0.3,1.4).translate((-20,11,0)),"#2a2d31"),
        (_rounded_box_xy(8,6,1.1,0.2,1.35).translate((19,-12,0)),"#303338"),
        (_rounded_box_xy(19,17,13.5,0.8,7.55).translate((42.5,-16.5,0)),"#aeb5bc"),
        (_rounded_box_xy(17,14,15.2,0.8,8.4).translate((43.5,3.0,0)),"#aab2ba"),
        (_rounded_box_xy(17,14,15.2,0.8,8.4).translate((43.5,19.0,0)),"#aab2ba"),
        (_rounded_box_xy(9.2,8.0,3.4,1.2,2.5).translate((-31,-29.3,0)),"#b9bec4"),
        (_rounded_box_xy(7.6,7.2,3.2,0.8,2.4).translate((-14,-29.0,0)),"#b8bdc3"),
        (_rounded_box_xy(7.6,7.2,3.2,0.8,2.4).translate((-2,-29.0,0)),"#b8bdc3"),
        (_rounded_box_xy(15,13,1.7,0.4,-1.65).translate((-35,1,0)),"#9da5ac"),
    ]
    parts.append((_rounded_box_xy(51.0,5.2,2.5,0.3,2.05).translate((-5.0,24.2,0)),"#17191b"))
    pins=[]; x0=-29.13
    for col in range(20):
        for row in range(2):
            px=x0+col*2.54; py=22.93+row*2.54
            pins.append(_rounded_box_xy(0.65,0.65,8.0,0,5.3).translate((px,py,0)))
    parts.append((cq.Compound.makeCompound(pins),"#d7a928"))
    parts += [
        (_rounded_box_xy(17,3.8,3.1,0.3,2.35).translate((17.5,-23.5,0)),"#e2ded4"),
        (_rounded_box_xy(17,3.8,3.1,0.3,2.35).translate((17.5,15.5,0)),"#e2ded4"),
        (_rounded_box_xy(11,3.5,2.8,0.3,2.2).translate((-30,22,0)),"#e2ded4"),
        (_rounded_box_xy(6,4,3.3,0.5,2.45).translate((25,23,0)),"#eee9df"),
        (_rounded_box_xy(4.5,4.5,2.8,0.4,2.2).translate((-39,18,0)),"#d9dde0"),
    ]
    return parts


def _component_parts(obj: dict[str, Any]) -> list[tuple[Any,str]]|None:
    # v1.1 resolves every known purchased component through the physical component layer.
    parts=physical_components.component_parts(obj)
    return parts if parts else None


def _base_shape(obj: dict[str, Any]):
    p=obj.get("params") or {}; kind=obj.get("kind","box")
    if kind=="mounting_plate": return _mounting_plate_shape(obj)
    if kind=="component":
        parts=_component_parts(obj)
        if parts: return cq.Compound.makeCompound([sh for sh,_ in parts])
        return cq.Workplane("XY").box(float(p.get("x",20)),float(p.get("y",20)),float(p.get("z",20))).val()
    if kind=="box": return cq.Workplane("XY").box(float(p.get("x",20)),float(p.get("y",20)),float(p.get("z",20))).val()
    if kind=="cylinder": return cq.Workplane("XY").circle(float(p.get("radius",10))).extrude(float(p.get("height",20)),both=True).val()
    if kind=="sphere": return cq.Workplane("XY").sphere(float(p.get("radius",10))).val()
    if kind=="sketch_extrude":
        h=float(p.get("height",10)); sk=p.get("sketch") or {}; typ=sk.get("type","rectangle"); wp=cq.Workplane("XY")
        if typ=="circle": wp=wp.circle(float(sk.get("radius",10)))
        elif typ=="polygon": wp=wp.polyline([(float(a),float(b)) for a,b in sk.get("points",[[-10,-10],[10,-10],[10,10],[-10,10]])]).close()
        else: wp=wp.rect(float(sk.get("width",20)),float(sk.get("height",20)))
        return wp.extrude(h,both=True).val()
    if kind=="revolve":
        pts=[(float(a),float(b)) for a,b in p.get("points",[[0,0],[10,0],[10,20],[0,20]])]
        return cq.Workplane("XZ").polyline(pts).close().revolve(float(p.get("angle_deg",360)),(0,0),(0,1)).val()
    if kind=="step":
        path=Path(str(p.get("path","")))
        if not path.exists(): raise FileNotFoundError(path)
        return cq.importers.importStep(str(path)).val()
    raise ValueError(f"Unsupported kind: {kind}")

def _apply_feature(shape, f: dict[str, Any]):
    typ=str(f.get("type","")); bb=shape.BoundingBox()
    if typ=="hole":
        d=float(f.get("diameter",5)); axis=str(f.get("axis","z")); x=float(f.get("x",0)); y=float(f.get("y",0)); z=float(f.get("z",0)); margin=max(bb.xlen,bb.ylen,bb.zlen)+20
        if axis=="x": tool=cq.Workplane("YZ").center(y,z).circle(d/2).extrude(margin,both=True).val()
        elif axis=="y": tool=cq.Workplane("XZ").center(x,z).circle(d/2).extrude(margin,both=True).val()
        else: tool=cq.Workplane("XY").center(x,y).circle(d/2).extrude(margin,both=True).val()
        return shape.cut(tool)
    if typ in {"circular_pocket","pocket_circle"}:
        d=float(f.get("diameter",10)); depth=float(f.get("depth",2)); x=float(f.get("x",0));y=float(f.get("y",0)); top=bb.zmax+0.01
        tool=cq.Workplane("XY").workplane(offset=top).center(x,y).circle(d/2).extrude(-depth-0.02).val(); return shape.cut(tool)
    if typ in {"rectangular_pocket","pocket_rect"}:
        w=float(f.get("width",10));h=float(f.get("height",10));depth=float(f.get("depth",2));x=float(f.get("x",0));y=float(f.get("y",0)); top=bb.zmax+0.01
        tool=cq.Workplane("XY").workplane(offset=top).center(x,y).rect(w,h).extrude(-depth-0.02).val(); return shape.cut(tool)
    if typ=="fillet":
        r=float(f.get("radius",1)); return cq.Workplane(obj=shape).edges().fillet(r).val()
    if typ=="chamfer":
        d=float(f.get("distance",1)); return cq.Workplane(obj=shape).edges().chamfer(d).val()
    return shape


def build_shape(obj: dict[str, Any]):
    shape=_base_shape(obj)
    for f in obj.get("features",[]): shape=_apply_feature(shape,f)
    t=obj.get("transform") or {}; s=t.get("scale",[1,1,1]);
    if any(abs(float(s[i])-1)>1e-9 for i in range(3)):
        # OpenCascade non-uniform scaling is intentionally not performed here; scale is a viewport-level hint.
        if len({round(float(x),9) for x in s})==1: shape=shape.scale(float(s[0]))
    r=t.get("rotation_deg",[0,0,0]);
    if float(r[0]): shape=shape.rotate((0,0,0),(1,0,0),float(r[0]))
    if float(r[1]): shape=shape.rotate((0,0,0),(0,1,0),float(r[1]))
    if float(r[2]): shape=shape.rotate((0,0,0),(0,0,1),float(r[2]))
    pos=t.get("position",[0,0,0]); shape=shape.translate(tuple(float(v) for v in pos))
    return shape


def object_metrics(obj: dict[str, Any]) -> dict[str, Any]:
    sh=build_shape(obj); bb=sh.BoundingBox(); vol=float(sh.Volume()); mat=MATERIALS.get(obj.get("material"),MATERIALS["aluminum_6061_t6"]); mass=vol*1e-9*float(mat["density_kg_m3"]); c=sh.Center()
    if obj.get("kind")=="component":
        definition=physical_components.component_definition(obj)
        if definition and definition.get("mass_g") is not None:mass=float(definition["mass_g"])/1000.0
    return {"volume_mm3":vol,"area_mm2":float(sh.Area()),"mass_kg":mass,"bounds_mm":{"x":bb.xlen,"y":bb.ylen,"z":bb.zlen},"centroid_mm":[c.x,c.y,c.z],"material":mat["name"],"geometry_fidelity":obj.get("component_snapshot",{}).get("geometry",{}).get("fidelity") if obj.get("kind")=="component" else "exact_brep"}

def project_metrics() -> dict[str, Any]:
    vals=[object_metrics(o) for o in PROJECT["objects"] if o.get("visible",True)]; purchased=sum(o.get("kind")=="component" for o in PROJECT["objects"]); custom=len(PROJECT["objects"])-purchased
    return {"object_count":len(PROJECT["objects"]),"purchased_component_count":purchased,"custom_part_count":custom,"connection_count":len(PROJECT.get("connections",[])),"mass_kg":sum(x["mass_kg"] for x in vals),"bom_cost_usd":sum(float(x.get("unit_cost_usd",0) or 0)*float(x.get("qty",1) or 1) for x in PROJECT.get("bom",[])),"active_design":ACTIVE_DESIGN}

def tessellate(obj: dict[str, Any], tolerance: float=.35) -> dict[str, Any]:
    parts=_component_parts(obj) if obj.get("kind")=="component" else None
    if parts and not obj.get("features"):
        t=obj.get("transform") or {}; pos=t.get("position",[0,0,0]); rot=t.get("rotation_deg",[0,0,0]); scl=t.get("scale",[1,1,1]); positions=[]; indices=[]; tri_colors=[]; offset=0
        for sh,color in parts:
            if len({round(float(x),9) for x in scl})==1 and abs(float(scl[0])-1)>1e-9: sh=sh.scale(float(scl[0]))
            if float(rot[0]): sh=sh.rotate((0,0,0),(1,0,0),float(rot[0]))
            if float(rot[1]): sh=sh.rotate((0,0,0),(0,1,0),float(rot[1]))
            if float(rot[2]): sh=sh.rotate((0,0,0),(0,0,1),float(rot[2]))
            sh=sh.translate(tuple(float(v) for v in pos)); verts,tris=sh.tessellate(float(tolerance)); positions.extend([[v.x,v.y,v.z] for v in verts]); indices.extend([[int(a)+offset,int(b)+offset,int(c)+offset] for a,b,c in tris]); tri_colors.extend([color]*len(tris)); offset+=len(verts)
        return {"id":obj["id"],"positions":positions,"triangles":indices,"triangle_colors":tri_colors,"material":obj.get("material"),"color":"#ffffff","geometry_fidelity":"component-specific"}
    sh=build_shape(obj); verts,tris=sh.tessellate(float(tolerance)); positions=[[v.x,v.y,v.z] for v in verts]; indices=[list(map(int,t)) for t in tris]
    return {"id":obj["id"],"positions":positions,"triangles":indices,"material":obj.get("material"),"color":MATERIALS.get(obj.get("material"),{}).get("color","#8aa0b6")}

def import_step_bytes(filename: str, data: bytes) -> dict[str, Any]:
    imports=DATA_DIR/"imports"; imports.mkdir(parents=True,exist_ok=True); path=imports/f"{uid()}_{_safe(filename)}"; path.write_bytes(data)
    obj={"id":uid(),"name":Path(filename).stem,"kind":"step","params":{"path":str(path)},"material":"aluminum_6061_t6","transform":_transform(),"features":[],"semantic":{"role":"imported_part","tags":["step"]},"visible":True}; PROJECT["objects"].append(obj); push_history("import STEP","human",filename); persist(); return obj


def push_history(action: str, actor: str="human", reason: str="") -> None:
    HISTORY.append(_snap(PROJECT));
    if len(HISTORY)>80: del HISTORY[:-80]
    REDO.clear(); PROJECT.setdefault("ledger",[]).append({"at":now(),"actor":actor,"action":action,"reason":reason,"design":ACTIVE_DESIGN}); PROJECT["ledger"]=PROJECT["ledger"][-500:]

def undo() -> bool:
    if len(HISTORY)<2: return False
    REDO.append(_snap(PROJECT)); HISTORY.pop(); prev=_snap(HISTORY[-1]); PROJECT.clear();PROJECT.update(prev);persist();return True

def redo() -> bool:
    if not REDO:return False
    nxt=REDO.pop();PROJECT.clear();PROJECT.update(nxt);HISTORY.append(_snap(nxt));persist();return True


def _unique_branch(name: str) -> str:
    base=_safe(name); out=base; n=2
    while out in DESIGNS: out=f"{base}-{n}"; n+=1
    return out

def create_branch(name: str, *, reason: str="", prefix: str|None=None) -> dict[str, Any]:
    global ACTIVE_DESIGN
    with LOCK:
        old=ACTIVE_DESIGN; BRANCHES[old]=_snap(PROJECT); nm=_unique_branch(prefix or name)
        BRANCHES[nm]=_snap(PROJECT); DESIGNS[nm]={"name":nm,"parent":old,"status":"untested","note":reason,"physical_verified":False,"created_at":now(),"updated_at":now()}; ACTIVE_DESIGN=nm; persist(); return PROJECT

def switch_branch(name: str) -> dict[str, Any]:
    global ACTIVE_DESIGN
    with LOCK:
        if name not in BRANCHES: raise KeyError(name)
        BRANCHES[ACTIVE_DESIGN]=_snap(PROJECT); ACTIVE_DESIGN=name; PROJECT.clear();PROJECT.update(_snap(BRANCHES[name])); HISTORY.clear();HISTORY.append(_snap(PROJECT)); REDO.clear();persist();return PROJECT

def list_branches() -> dict[str, Any]:
    return {"active":ACTIVE_DESIGN,"designs":[deepcopy(DESIGNS[k])|{"active":k==ACTIVE_DESIGN} for k in sorted(DESIGNS)]}
def set_design_status(name: str, status: str, note: str="", physical_verified: bool=False) -> dict[str, Any]:
    if name not in DESIGNS: raise KeyError(name)
    status=status.lower().replace(" ","_"); DESIGNS[name].update({"status":status,"note":note,"physical_verified":bool(physical_verified),"updated_at":now()});persist();return deepcopy(DESIGNS[name])
def ensure_mutable(actor: str, reason: str) -> str|None:
    meta=DESIGNS.get(ACTIVE_DESIGN,{})
    if meta.get("physical_verified") or meta.get("status") in {"working","working_in_real_life"}:
        stamp=datetime.now().strftime("%Y%m%d-%H%M%S"); create_branch(f"experiment-{stamp}",reason=f"Protected baseline branched before mutation: {reason}"); return ACTIVE_DESIGN
    return None

def _branch_state(name: str) -> dict[str, Any]:
    if name==ACTIVE_DESIGN: return PROJECT
    if name not in BRANCHES: raise KeyError(name)
    return BRANCHES[name]
def compare_branch(name: str, other: str|None=None) -> dict[str, Any]:
    a=_branch_state(other or ACTIVE_DESIGN); b=_branch_state(name)
    amap={x["id"]:x for x in a.get("objects",[])};bmap={x["id"]:x for x in b.get("objects",[])}; ids=sorted(set(amap)|set(bmap)); changes=[]
    for i in ids:
        if i not in amap: changes.append({"id":i,"type":"only_in_target","name":bmap[i].get("name")})
        elif i not in bmap: changes.append({"id":i,"type":"only_in_source","name":amap[i].get("name")})
        elif json.dumps(amap[i],sort_keys=True)!=json.dumps(bmap[i],sort_keys=True): changes.append({"id":i,"type":"modified","name":amap[i].get("name"),"source":amap[i],"target":bmap[i]})
    return {"source":other or ACTIVE_DESIGN,"target":name,"changes":changes,"count":len(changes)}


def mark_simulations_stale(object_id: str|None=None) -> int:
    n=0
    for s in PROJECT.get("simulations",[]):
        if object_id is None or s.get("object_id")==object_id:
            if not s.get("stale"): s["stale"]=True;n+=1
    return n

def record_simulation(kind: str, object_id: str|None, params: dict[str,Any], result: dict[str,Any]) -> dict[str,Any]:
    item={"id":uid(),"kind":kind,"object_id":object_id,"params":deepcopy(params),"result":deepcopy(result),"at":now(),"design":ACTIVE_DESIGN,"stale":False};PROJECT.setdefault("simulations",[]).append(item);persist();return item

def requirement_checks() -> list[dict[str,Any]]:
    m=project_metrics(); latest={}
    for s in PROJECT.get("simulations",[]):
        if not s.get("stale"): latest[s.get("kind")]=s.get("result") or {}
    out=[]
    for r in PROJECT.get("requirements",[]):
        metric=str(r.get("metric","")); val=None
        if metric in m: val=m[metric]
        else:
            for res in latest.values():
                if metric in res: val=res[metric];break
        op=r.get("op","<="); target=float(r.get("target",0)); passed=None if val is None else ({"<=":val<=target,">=":val>=target,"<":val<target,">":val>target,"==":val==target}.get(op,False))
        out.append({**r,"value":val,"passed":passed})
    return out


def _component_bom_upsert(component_id: str, qty_delta: int=1) -> dict[str,Any]:
    for item in PROJECT.setdefault("bom",[]):
        if item.get("component_ref")==component_id:
            item["qty"]=max(0,int(item.get("qty",0))+int(qty_delta));return item
    item=component_registry.bom_item(component_id,int(qty_delta));item.setdefault("id",uid());PROJECT["bom"].append(item);return item

def _component_instance_args(component_id: str, name: str|None=None, transform: dict[str,Any]|None=None) -> dict[str,Any]:
    args=component_registry.make_project_object(component_id,name=name,transform=transform);args.setdefault("transform",_transform());args.setdefault("features",[]);args.setdefault("visible",True);return args

def reality_check() -> dict[str,Any]:
    system=system_validation.validate_system(PROJECT)
    try:
        import assembly_validation
        assembly=assembly_validation.validate_assembly(PROJECT,build_shape,min_clearance_mm=1.0)
    except Exception as e:
        assembly={"ok":True,"counts":{"error":0,"warning":1,"info":0},"risks":[{"severity":"warning","code":"assembly_check_unavailable","message":str(e)}],"collisions":[],"low_clearances":[]}
    risks=list(system.get("risks",[]))+list(assembly.get("risks",[]));counts={s:sum(r.get("severity")==s for r in risks) for s in ("error","warning","info")}
    return {**system,"ok":counts["error"]==0,"counts":counts,"risks":risks,"assembly":assembly}

def execute(op: str, args: dict[str,Any]|None=None, actor: str="human", reason: str="") -> dict[str,Any]:
    args=deepcopy(args or {})
    with LOCK:
        mutation=op not in {"project_name","settings"}
        if mutation: ensure_mutable(actor,reason or op)
        if op=="add":
            if args.get("kind")=="component":raise ValueError("Purchased components must be instantiated with add_component so registry identity, provenance, interfaces and BOM remain authoritative")
            obj={"id":uid(),"name":args.get("name","Part"),"kind":args.get("kind","box"),"params":args.get("params",{"x":20,"y":20,"z":20}),"material":args.get("material","aluminum_6061_t6"),"transform":args.get("transform",_transform()),"features":deepcopy(args.get("features",[])),"semantic":args.get("semantic",{}),"visible":True}
            for optional in ("component_ref","component_snapshot","interfaces","code"):
                if optional in args: obj[optional]=deepcopy(args[optional])
            PROJECT["objects"].append(obj); changed=obj["id"]
        elif op=="add_component":
            cid=str(args.get("component_id") or args.get("id") or "");data=_component_instance_args(cid,args.get("name"),args.get("transform"));obj={"id":uid(),**deepcopy(data)};PROJECT["objects"].append(obj);_component_bom_upsert(cid,1);changed=obj["id"]
        elif op=="update":
            obj=object_by_id(str(args.pop("id"))); changed=obj["id"]
            if obj.get("kind")=="component":
                forbidden=set(args)&{"params","material","component_ref","component_snapshot","interfaces","features"}
                if forbidden:raise ValueError("Purchased component engineering data is immutable; use replace_component or explicit sync_component instead of editing "+", ".join(sorted(forbidden)))
            for k,v in args.items():
                if k in {"name","params","material","semantic","visible","component_ref"}: obj[k]=v
        elif op=="transform":
            obj=object_by_id(str(args.get("id"))); changed=obj["id"]; t=obj.setdefault("transform",_transform())
            if obj.get("kind")=="component" and "scale" in args and any(abs(float(x)-1.0)>1e-9 for x in args["scale"]):raise ValueError("Purchased components cannot be scaled; their physical dimensions are authoritative")
            for k in ("position","rotation_deg","scale"):
                if k in args:t[k]=[float(x) for x in args[k]]
        elif op=="mate_components":
            source=object_by_id(str(args.get("source_id")));target=object_by_id(str(args.get("target_id")));physical_components.mate_objects(source,target,str(args.get("source_interface")),str(args.get("target_interface")),float(args.get("gap_mm",0)));physical_components.connect_interfaces(PROJECT,source,str(args.get("source_interface")),target,str(args.get("target_interface")),"mechanical");changed=source["id"]
        elif op=="connect_interfaces":
            a=object_by_id(str(args.get("a_id")));b=object_by_id(str(args.get("b_id")));physical_components.connect_interfaces(PROJECT,a,str(args.get("a_interface")),b,str(args.get("b_interface")),str(args.get("kind","auto")));changed=None
        elif op=="disconnect":
            iid=str(args.get("id"));before=len(PROJECT.setdefault("connections",[]));PROJECT["connections"][:]=[x for x in PROJECT["connections"] if str(x.get("id"))!=iid];
            if len(PROJECT["connections"])==before:raise KeyError(iid)
            changed=None
        elif op=="sync_component":
            obj=object_by_id(str(args.get("id")));cid=str(obj.get("component_ref") or "");fresh=component_registry.component_snapshot(cid);obj["component_snapshot"]=fresh;obj["interfaces"]=deepcopy(fresh.get("interfaces",[]));dims=fresh.get("dimensions_mm",[20,20,20]);obj["params"].update({"x":float(dims[0]),"y":float(dims[1]),"z":float(dims[2])});obj.setdefault("semantic",{}).update({"geometry_fidelity":fresh.get("geometry",{}).get("fidelity"),"trust_score":fresh.get("trust_score",0)});changed=obj["id"]
        elif op=="replace_component":
            obj=object_by_id(str(args.get("id")));old_cid=obj.get("component_ref");cid=str(args.get("component_id"));preserve_transform=deepcopy(obj.get("transform",_transform()));preserve_name=obj.get("name");data=_component_instance_args(cid,args.get("name") or preserve_name,preserve_transform);obj.clear();obj.update({"id":str(args.get("id")),**data});
            if old_cid:_component_bom_upsert(str(old_cid),-1)
            _component_bom_upsert(cid,1);PROJECT["bom"][:]=[x for x in PROJECT["bom"] if int(x.get("qty",1) or 0)>0];changed=obj["id"]
        elif op=="delete":
            oid=str(args.get("id"));victim=next((o for o in PROJECT["objects"] if o["id"]==oid),None);PROJECT["objects"][:]=[o for o in PROJECT["objects"] if o["id"]!=oid];PROJECT.setdefault("connections",[])[:]=[x for x in PROJECT["connections"] if x.get("a",{}).get("object_id")!=oid and x.get("b",{}).get("object_id")!=oid];
            if victim and victim.get("component_ref"):_component_bom_upsert(str(victim["component_ref"]),-1)
            PROJECT["bom"][:]=[x for x in PROJECT["bom"] if int(x.get("qty",1) or 0)>0];changed=oid
        elif op=="add_feature":
            obj=object_by_id(str(args.get("id")));
            if obj.get("kind")=="component":raise ValueError("Purchased component geometry cannot receive CAD features. Model machining as a custom/fabricated derivative instead.")
            obj.setdefault("features",[]).append(deepcopy(args.get("feature") or {}));changed=obj["id"]
        elif op=="delete_feature":
            obj=object_by_id(str(args.get("id")));
            if obj.get("kind")=="component":raise ValueError("Purchased component geometry is immutable")
            idx=int(args.get("index",-1));obj["features"].pop(idx);changed=obj["id"]
        elif op in {"add_joint","add_load","add_constraint","set_requirement","add_bom_item","add_note"}:
            mapping={"add_joint":"joints","add_load":"loads","add_constraint":"constraints","set_requirement":"requirements","add_bom_item":"bom","add_note":"notebook"}; key=mapping[op]; item=deepcopy(args);item.setdefault("id",uid());PROJECT[key].append(item);changed=None
        elif op in {"delete_joint","delete_load","delete_constraint","delete_requirement","delete_bom_item"}:
            mapping={"delete_joint":"joints","delete_load":"loads","delete_constraint":"constraints","delete_requirement":"requirements","delete_bom_item":"bom"};key=mapping[op];iid=str(args.get("id"));PROJECT[key][:]=[x for x in PROJECT[key] if x.get("id")!=iid];changed=None
        elif op=="update_bom_item":
            item=next(x for x in PROJECT["bom"] if x.get("id")==args.get("id"));item.update({k:v for k,v in args.items() if k!="id"});changed=None
        elif op=="code_write":
            obj=object_by_id(str(args.get("id"))); path=str(args.get("path","main.py")); _validate_code_path(path); obj.setdefault("code",{"platform":"generic","entrypoint":path,"files":{}})["files"][path]=str(args.get("content","")); changed=obj["id"]
        elif op=="code_delete":
            obj=object_by_id(str(args.get("id")));path=str(args.get("path"));_validate_code_path(path);obj.setdefault("code",{}).setdefault("files",{}).pop(path,None);changed=obj["id"]
        elif op=="code_rename":
            obj=object_by_id(str(args.get("id")));old=str(args.get("old_path"));new=str(args.get("new_path"));_validate_code_path(old);_validate_code_path(new);files=obj.setdefault("code",{}).setdefault("files",{});files[new]=files.pop(old);changed=obj["id"]
        elif op=="project_name": PROJECT["name"]=str(args.get("name","ForgeCAD Project"));changed=None
        elif op=="settings": PROJECT.setdefault("settings",{}).update(args);changed=None
        else: raise ValueError(f"Unsupported operation: {op}")
        if mutation: mark_simulations_stale(changed)
        push_history(op,actor,reason);persist();return {"ok":True,"op":op,"project":PROJECT,"active_design":ACTIVE_DESIGN}

def _validate_code_path(path: str) -> None:
    p=Path(path)
    if p.is_absolute() or ".." in p.parts or not path.strip(): raise ValueError("Unsafe workspace path")

load(); HISTORY.append(_snap(PROJECT))
