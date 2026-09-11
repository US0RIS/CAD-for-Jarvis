from __future__ import annotations

"""Geometry, mating and reality checks for ForgeCAD v1.1 purchased components."""
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
import cadquery as cq
from . import component_registry as registry


def _box(x:float,y:float,z:float,color:str="#888888",center=(0,0,0),radius:float=0.0):
    cx,cy,cz=center;wp=cq.Workplane("XY").workplane(offset=cz-z/2).box(x,y,z,centered=(True,True,False))
    if radius>0:
        try:wp=wp.edges("|Z").fillet(min(radius,x/2-.01,y/2-.01))
        except Exception:pass
    return wp.val().translate((cx,cy,0)),color

def _cyl(d:float,h:float,color:str="#888888",center=(0,0,0),axis="z"):
    cx,cy,cz=center
    # CadQuery ``both=True`` extrudes the requested distance in both directions.
    # ``h`` is the engineering full length, so use h/2 on each side.
    half=float(h)/2.0
    if axis=="x":sh=cq.Workplane("YZ").circle(d/2).extrude(half,both=True).val().translate((cx,cy,cz))
    elif axis=="y":sh=cq.Workplane("XZ").circle(d/2).extrude(half,both=True).val().translate((cx,cy,cz))
    else:sh=cq.Workplane("XY").circle(d/2).extrude(half,both=True).val().translate((cx,cy,cz))
    return sh,color

def _cut_holes(shape,points,diameter,depth,offset_z):
    out=shape
    for x,y in points:out=out.cut(cq.Workplane("XY").workplane(offset=offset_z).center(x,y).circle(diameter/2).extrude(depth).val())
    return out

def _pi5_parts():
    parts=[];board,_=_box(85,56,1.6,"#16813e",radius=3);board=_cut_holes(board,[(-29,-24.5),(29,-24.5),(29,24.5),(-29,24.5)],2.7,3,-1.5);parts.append((board,"#16813e"))
    for args in [(17.2,17.2,1.7,"#202327",(-8,-1,1.65)),(12.5,12.5,1.4,"#24272b",(11,2,1.5)),(7,7,1.2,"#2a2d31",(-20,11,1.4)),(8,6,1.1,"#303338",(19,-12,1.35)),(19,17,13.5,"#aeb5bc",(42.5,-16.5,7.55)),(17,14,15.2,"#aab2ba",(43.5,3,8.4)),(17,14,15.2,"#aab2ba",(43.5,19,8.4)),(9.2,8,3.4,"#b9bec4",(-31,-29.3,2.5)),(7.6,7.2,3.2,"#b8bdc3",(-14,-29,2.4)),(7.6,7.2,3.2,"#b8bdc3",(-2,-29,2.4)),(15,13,1.7,"#9da5ac",(-35,1,-1.65)),(51,5.2,2.5,"#17191b",(-5,24.2,2.05))]:parts.append(_box(*args))
    pins=[];x0=-29.13
    for col in range(20):
        for row in range(2):pins.append(_box(.65,.65,8,"#d7a928",(x0+col*2.54,22.93+row*2.54,5.3))[0])
    parts.append((cq.Compound.makeCompound(pins),"#d7a928"))
    for args in [(17,3.8,3.1,"#e2ded4",(17.5,-23.5,2.35)),(17,3.8,3.1,"#e2ded4",(17.5,15.5,2.35)),(11,3.5,2.8,"#e2ded4",(-30,22,2.2)),(6,4,3.3,"#eee9df",(25,23,2.45)),(4.5,4.5,2.8,"#d9dde0",(-39,18,2.2))]:parts.append(_box(*args))
    return parts

def _bearing_parts(c):
    s=c.get("specs",{});d=float(s.get("outer_diameter_mm") or c.get("dimensions_mm",[22])[0]);b=float(s.get("bore_mm") or max(3,d*.35));w=float(s.get("width_mm") or c.get("dimensions_mm",[0,0,7])[2]);outer=cq.Workplane("XY").circle(d/2).circle(b/2).extrude(w/2,both=True).val();shield=cq.Workplane("XY").circle(d*.44).circle(b*.54).extrude(w*.41,both=True).val();return [(outer,"#aeb4ba"),(shield,"#6e747b")]
def _stepper_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];face=min(x,y);body,_=_box(x*.96,y*.96,z,"#25282c",radius=2);front,_=_box(x,y,3,"#9ba2a8",(0,0,z/2-1.5),1.5);rear,_=_box(x*.94,y*.94,2,"#6f747a",(0,0,-z/2+1),1);pilot=_cyl(max(16,face*.52),2,"#aab0b5",(0,0,z/2+1))[0];shaft_d=5 if face<=42 else 6.35;shaft=_cyl(shaft_d,20,"#c4c9cd",(0,0,z/2+10))[0];spacing={20:15.4,28:23,35:26,42:31,57:47.14}.get(round(face),face*.73);pts=[(-spacing/2,-spacing/2),(spacing/2,-spacing/2),(spacing/2,spacing/2),(-spacing/2,spacing/2)];front=_cut_holes(front,pts,3 if face<=42 else 5,5,z/2-3);return [(body,"#25282c"),(front,"#9ba2a8"),(rear,"#6f747a"),(pilot,"#aab0b5"),(shaft,"#c4c9cd")]
def _servo_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];body,_=_box(x*.88,y,z*.82,"#2b2d30",(0,0,-z*.04),2);ear,_=_box(x*1.14,y*1.05,z*.10,"#25272a",(0,0,z*.22),1);top=_cyl(min(x,y)*.42,z*.16,"#d0d3d6",(x*.20,0,z*.46))[0];spline=_cyl(min(x,y)*.18,z*.10,"#d5d8da",(x*.20,0,z*.59))[0];return [(body,"#2b2d30"),(ear,"#25272a"),(top,"#d0d3d6"),(spline,"#d5d8da")]
def _solenoid_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];stroke=float(c.get("specs",{}).get("stroke_mm") or 10);body,_=_box(x,y,max(10,z-stroke),"#303337",(0,0,-stroke/2),2);cap,_=_box(x*1.05,y*1.05,3,"#9aa0a5",(0,0,z/2-stroke-1.5),1);plunger=_cyl(min(x,y)*.24,stroke+18,"#c4c8cb",(0,0,z/2-stroke/2+6))[0];return [(body,"#303337"),(cap,"#9aa0a5"),(plunger,"#c4c8cb")]
def _fan_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];frame,_=_box(x,y,z,"#22262a",radius=max(1,x*.06));frame=frame.cut(cq.Workplane("XY").circle(min(x,y)*.39).extrude(z+2,both=True).val());hole_space=min(x,y)*.82;frame=_cut_holes(frame,[(-hole_space/2,-hole_space/2),(hole_space/2,-hole_space/2),(hole_space/2,hole_space/2),(-hole_space/2,hole_space/2)],max(2.5,x*.04),z+4,-z);hub=_cyl(min(x,y)*.24,z*.55,"#3a3e43")[0];blades=[]
    for i in range(7):blade,_=_box(min(x,y)*.30,min(x,y)*.07,z*.22,"#34383d",(min(x,y)*.20,0,0),min(x,y)*.025);blades.append(blade.rotate((0,0,0),(0,0,1),i*360/7+25))
    return [(frame,"#22262a"),(hub,"#3a3e43"),(cq.Compound.makeCompound(blades),"#34383d")]
def _fastener_parts(c):
    s=c.get("specs",{});d=float(s.get("diameter_mm") or c.get("legacy",{}).get("diameter_mm") or 3);length=float(s.get("length_mm") or c.get("legacy",{}).get("length_mm") or 12);head_d=d*1.7;head_h=d;shaft=_cyl(d,length,"#aeb4ba",(0,0,-length/2))[0];head=_cyl(head_d,head_h,"#8e959b",(0,0,head_h/2))[0];socket=cq.Workplane("XY").polygon(6,d*.62).extrude(head_h*.55).val().translate((0,0,head_h*.58));return [(shaft,"#aeb4ba"),(head.cut(socket),"#8e959b")]
def _rail_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];rail,_=_box(x,max(3,y*.45),max(2,z*.34),"#a3a9ae",(0,0,-z*.25),.5);carriage,_=_box(min(50,max(20,y*1.8)),y,z*.62,"#686e74",(0,0,z*.08),1);return [(rail,"#a3a9ae"),(carriage,"#686e74")]
def _pcb_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];board_h=min(1.6,max(.8,z*.25));board,_=_box(x,y,board_h,"#167a3b",radius=min(3,min(x,y)*.06));chip,_=_box(min(16,x*.28),min(16,y*.35),max(1,min(2,z*.2)),"#25282b",(0,0,board_h/2+1));header,_=_box(min(x*.65,35),min(5,y*.18),max(2,min(7,z*.6)),"#17191b",(0,y*.38,max(1,z*.20)));conn,_=_box(min(10,x*.22),min(9,y*.28),max(3,min(8,z*.7)),"#b6bcc1",(x*.42,0,max(1,z*.24)));return [(board,"#167a3b"),(chip,"#25282b"),(header,"#17191b"),(conn,"#b6bcc1")]
def _battery_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];body,_=_box(x,y,z,"#45484d",radius=min(4,min(x,y,z)*.12));lead1=_cyl(1.2,min(15,x*.2),"#d43c35",(x/2+min(15,x*.2)/2,2,0),"x")[0];lead2=_cyl(1.2,min(15,x*.2),"#25282b",(x/2+min(15,x*.2)/2,-2,0),"x")[0];return [(body,"#45484d"),(lead1,"#d43c35"),(lead2,"#25282b")]
def _power_supply_parts(c):
    x,y,z=[float(v) for v in c["dimensions_mm"]];base,_=_box(x,y,1.2,"#aab0b4",(0,0,-z/2+.6),1);side1,_=_box(x,1.2,z,"#9ba1a6",(0,-y/2+.6,0),.5);side2,_=_box(x,1.2,z,"#9ba1a6",(0,y/2-.6,0),.5);end,_=_box(1.2,y,z,"#9ba1a6",(-x/2+.6,0,0),.5);top,_=_box(x*.72,y*.86,1.0,"#b4b9bd",(x*.08,0,z/2-.5),1);terminal,_=_box(12,min(55,y*.55),12,"#303337",(x/2-8,-y*.15,z/2-6),1);vents=[]
    for i in range(8):vents.append(_box(x*.34,2,.7,"#596066",(-x*.12,-y*.31+i*y*.075,z/2+.15),.2)[0])
    return [(base,"#aab0b4"),(side1,"#9ba1a6"),(side2,"#9ba1a6"),(end,"#9ba1a6"),(top,"#b4b9bd"),(terminal,"#303337"),(cq.Compound.makeCompound(vents),"#596066")]

def component_definition(obj):
    snap=obj.get("component_snapshot")
    if isinstance(snap,dict) and snap.get("id")==obj.get("component_ref"):return deepcopy(snap)
    if obj.get("component_ref"):
        try:return registry.component_by_id(obj["component_ref"])
        except KeyError:return None
    return None
def _step_asset(c):
    if not c:return None
    for a in c.get("geometry",{}).get("assets",[]):
        if a.get("role")=="geometry" and a.get("format") in {"step","stp"}:
            path=registry.resolve_asset_path(a)
            if path and path.is_file():return path
    return None
def component_parts(obj):
    c=component_definition(obj)
    if not c:return None
    step=_step_asset(c)
    if step:
        try:return [(cq.importers.importStep(str(step)).val(),"#aeb7c2")]
        except Exception:pass
    profile=str(c.get("geometry",{}).get("profile") or c.get("category") or "box")
    if profile=="raspberry_pi_5":return _pi5_parts()
    dispatch={"bearing":_bearing_parts,"stepper_motor":_stepper_parts,"servo":_servo_parts,"solenoid":_solenoid_parts,"fan":_fan_parts,"fastener":_fastener_parts,"linear_motion":_rail_parts,"compute":_pcb_parts,"microcontroller":_pcb_parts,"sensor":_pcb_parts,"power":_pcb_parts,"battery":_battery_parts,"power_supply":_power_supply_parts};fn=dispatch.get(profile) or dispatch.get(str(c.get("category")))
    if fn:
        try:return fn(c)
        except Exception:pass
    x,y,z=[float(v) for v in c.get("dimensions_mm",[20,20,20])];return [_box(x,y,z,"#727b84",radius=min(x,y,z)*.03)]
def component_shape(obj):
    p=component_parts(obj);return cq.Compound.makeCompound([s for s,_ in p]) if p else None

def _norm(v):
    n=math.sqrt(sum(float(x)*float(x) for x in v));return [float(x)/n for x in v] if n>1e-12 else [0,0,1]
def _dot(a,b):return sum(float(x)*float(y) for x,y in zip(a,b))
def _cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def _mat_vec(m,v):return [sum(m[i][j]*v[j] for j in range(3)) for i in range(3)]
def _mat_mul(a,b):return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def _rot_xyz(deg):
    x,y,z=[math.radians(float(v)) for v in deg];cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z);return _mat_mul([[cz,-sz,0],[sz,cz,0],[0,0,1]],_mat_mul([[cy,0,sy],[0,1,0],[-sy,0,cy]],[[1,0,0],[0,cx,-sx],[0,sx,cx]]))
def _align(a,b):
    a,b=_norm(a),_norm(b);v=_cross(a,b);c=max(-1,min(1,_dot(a,b)));s=math.sqrt(_dot(v,v))
    if s<1e-10:
        if c>0:return [[1,0,0],[0,1,0],[0,0,1]]
        trial=[1,0,0] if abs(a[0])<.9 else [0,1,0];v=_norm(_cross(a,trial));x,y,z=v;return [[2*x*x-1,2*x*y,2*x*z],[2*x*y,2*y*y-1,2*y*z],[2*x*z,2*y*z,2*z*z-1]]
    x,y,z=[q/s for q in v];C=1-c;return [[c+x*x*C,x*y*C-z*s,x*z*C+y*s],[y*x*C+z*s,c+y*y*C,y*z*C-x*s],[z*x*C-y*s,z*y*C+x*s,c+z*z*C]]
def _euler_xyz(m):
    y=math.asin(max(-1,min(1,-m[2][0])));x,z=(math.atan2(m[2][1],m[2][2]),math.atan2(m[1][0],m[0][0])) if abs(math.cos(y))>1e-8 else (math.atan2(-m[1][2],m[1][1]),0);return [math.degrees(x),math.degrees(y),math.degrees(z)]
def object_interface(obj,interface_id):
    for i in obj.get("interfaces",[]):
        if i.get("id")==interface_id:return deepcopy(i)
    c=component_definition(obj)
    if c:return registry.interface_by_id(c,interface_id)
    raise KeyError(interface_id)
def world_interface(obj,interface_id):
    i=object_interface(obj,interface_id);t=obj.get("transform",{});r=_rot_xyz(t.get("rotation_deg",[0,0,0]));p=t.get("position",[0,0,0]);wp=_mat_vec(r,i.get("position_mm",[0,0,0]));wa=_mat_vec(r,i.get("axis",[0,0,1]));return {**i,"world_position_mm":[wp[j]+float(p[j]) for j in range(3)],"world_axis":_norm(wa)}
def mate_objects(source,target,source_interface,target_interface,gap_mm=0.0):
    si=object_interface(source,source_interface);ti=world_interface(target,target_interface);compat=registry.interface_compatibility(si,ti)
    if not compat["compatible"]:raise ValueError("Incompatible interfaces: "+"; ".join(compat["reasons"]))
    R=_align(si.get("axis",[0,0,1]),[-v for v in ti["world_axis"]]);sp=_mat_vec(R,si.get("position_mm",[0,0,0]));tp=ti["world_position_mm"];axis=ti["world_axis"];pos=[tp[k]-sp[k]+float(gap_mm)*axis[k] for k in range(3)];source.setdefault("transform",{})["position"]=pos;source["transform"]["rotation_deg"]=_euler_xyz(R);source["transform"].setdefault("scale",[1,1,1]);return {"source":source.get("id"),"source_interface":source_interface,"target":target.get("id"),"target_interface":target_interface,"compatibility":compat,"transform":deepcopy(source["transform"])}
def connect_interfaces(project,a,ai,b,bi,connection_kind="auto"):
    ia,ib=object_interface(a,ai),object_interface(b,bi);compat=registry.interface_compatibility(ia,ib)
    if not compat["compatible"]:raise ValueError("Incompatible interfaces: "+"; ".join(compat["reasons"]))
    kind=connection_kind if connection_kind!="auto" else ("electrical" if "electrical" in str(ia.get("kind"))+str(ib.get("kind")) or any(x in str(ia.get("kind")) for x in ["digital","servo_signal","pwm","i2c","spi","uart"]) else "mechanical");item={"id":__import__('uuid').uuid4().hex,"kind":kind,"a":{"object_id":a["id"],"interface_id":ai},"b":{"object_id":b["id"],"interface_id":bi},"compatibility":compat};project.setdefault("connections",[]).append(item);return item

def json_stable(x):
    import json;return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def reality_check(project,object_lookup:Callable[[str],dict[str,Any]]|None=None):
    risks=[];connections=project.get("connections",[]);used={(e[s]["object_id"],e[s]["interface_id"]) for e in connections for s in ("a","b") if isinstance(e.get(s),dict)};objs=[o for o in project.get("objects",[]) if o.get("kind")=="component"]
    for o in objs:
        c=component_definition(o)
        if not c:risks.append({"severity":"error","code":"component_missing_registry","object_id":o.get("id"),"message":f"{o.get('name')} references missing component {o.get('component_ref')}"});continue
        fidelity=c.get("geometry",{}).get("fidelity","none");trust=int(c.get("trust_score",0))
        if registry.GEOMETRY_RANK.get(fidelity,0)<55:risks.append({"severity":"warning","code":"low_geometry_fidelity","object_id":o.get("id"),"message":f"{o.get('name')} uses {fidelity} geometry; verify fit against vendor CAD."})
        if trust<55:risks.append({"severity":"warning","code":"low_source_trust","object_id":o.get("id"),"message":f"{o.get('name')} component data trust score is {trust}/100."})
        for i in o.get("interfaces",c.get("interfaces",[])):
            if i.get("required") and (o.get("id"),i.get("id")) not in used:risks.append({"severity":"warning","code":"required_interface_open","object_id":o.get("id"),"interface_id":i.get("id"),"message":f"{o.get('name')} required interface {i.get('id')} is not connected."})
        try:
            live=registry.component_by_id(o.get("component_ref"));snap=o.get("component_snapshot")
            if snap and json_stable({k:v for k,v in live.items() if k!="legacy"})!=json_stable(snap):risks.append({"severity":"info","code":"registry_revision_changed","object_id":o.get("id"),"message":f"Registry data for {o.get('name')} changed after this design snapshot; review before syncing."})
        except KeyError:pass
    bom_refs={x.get("component_ref") for x in project.get("bom",[])}
    for o in objs:
        if o.get("component_ref") not in bom_refs:risks.append({"severity":"warning","code":"bom_missing_component","object_id":o.get("id"),"message":f"{o.get('name')} is not represented in the BOM."})
    return {"ok":not any(r["severity"]=="error" for r in risks),"risks":risks,"counts":{s:sum(r["severity"]==s for r in risks) for s in ["error","warning","info"]},"components":len(objs),"connections":len(connections)}


# ForgeCAD high-fidelity purchased-component override
# Manufacturer STEP or a part-specific detailed model is attempted before the
# broad legacy envelope catalog. Generic geometry remains available only for
# catalog entries that do not yet have a high-fidelity implementation.
from . import realistic_components as _realistic_components
_legacy_component_parts = component_parts

def component_parts(obj):
    component = component_definition(obj)
    realistic = _realistic_components.component_parts(obj, component, allow_download=False) if component else None
    return realistic if realistic else _legacy_component_parts(obj)

def component_geometry_status(obj):
    component = component_definition(obj) or {}
    status = _realistic_components.geometry_status(obj, component)
    if status.get("resolved"):
        return status
    return {
        **status,
        "geometry_source": str((component.get("geometry") or {}).get("trust") or "legacy_fallback"),
        "geometry_fidelity": str((component.get("geometry") or {}).get("fidelity") or "none"),
    }
