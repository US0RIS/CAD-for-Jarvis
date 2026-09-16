from __future__ import annotations

"""Deterministic mounting assistance for purchased components.

ForgeCAD only drills geometry that is justified by frozen component metadata.  When
mounting data is incomplete it returns an unresolved item instead of inventing a
hole pattern.  Fasteners are selected from the component registry by diameter and
minimum required length.
"""
from copy import deepcopy
from typing import Any
from . import component_registry as registry


def _spec(component:dict[str,Any], key:str):
    if key in component:return component.get(key)
    return component.get("specs",{}).get(key)


def _mount_points(interface:dict[str,Any])->tuple[list[list[float]],float|None,str|None]:
    meta=interface.get("metadata",{}) or {}
    explicit=meta.get("points_mm") or meta.get("mounting_points_mm")
    diameter=meta.get("hole_diameter_mm")
    if explicit:
        pts=[]
        for p in explicit:
            if isinstance(p,(list,tuple)) and len(p)>=2:pts.append([float(p[0]),float(p[1])])
        expected=meta.get("count")
        if expected is not None and pts and len(pts)!=int(expected):
            return [],float(diameter) if diameter is not None else None,f"explicit mounting-point count {len(pts)} does not match declared count {expected}"
        return pts,float(diameter) if diameter is not None else None,None if pts else "mount point list is empty"
    pattern=meta.get("pattern_mm") or meta.get("hole_spacing_mm")
    if isinstance(pattern,(list,tuple)) and len(pattern)>=2:
        # A two-value spacing only defines the four corners of a rectangular
        # pattern when the manufacturer actually declares four holes.  Never turn
        # a two-hole diagonal/offset dimension into four drilled holes.
        count=int(meta.get("count",4) or 4)
        if count!=4:
            return [],float(diameter) if diameter is not None else None,f"{count}-hole mounting pattern lacks explicit center coordinates"
        sx,sy=float(pattern[0]),float(pattern[1])
        return [[-sx/2,-sy/2],[sx/2,-sy/2],[sx/2,sy/2],[-sx/2,sy/2]],float(diameter) if diameter is not None else None,None
    return [],float(diameter) if diameter is not None else None,"component does not publish a usable mounting-point pattern"


def select_metric_fastener(diameter_mm:float, grip_mm:float, engagement_mm:float|None=None)->dict[str,Any]|None:
    """Pick the shortest registry fastener that satisfies nominal diameter and grip.

    Default engagement is max(2 mm, 1x nominal diameter).  This is a deterministic
    planning rule, not a substitute for thread-strength analysis.
    """
    d=float(diameter_mm);eng=max(2.0,d) if engagement_mm is None else float(engagement_mm);need=float(grip_mm)+eng;candidates=[]
    for c in registry.all_components("fastener"):
        cd=_spec(c,"diameter_mm");length=_spec(c,"length_mm")
        if cd is None or length is None:continue
        try:cd=float(cd);length=float(length)
        except (TypeError,ValueError):continue
        if abs(cd-d)<=0.06 and length+1e-9>=need:candidates.append((length,c.get("trust_score",0),c))
    if not candidates:return None
    candidates.sort(key=lambda row:(row[0],-int(row[1]),row[2].get("id","")));length,_,c=candidates[0]
    return {"component":deepcopy(c),"required_length_mm":need,"selected_length_mm":length,"engagement_mm":eng,"rule":"shortest catalog fastener meeting grip + engagement"}


def component_mount_plan(obj:dict[str,Any], plate_thickness_mm:float, standoff_mm:float=6.0)->dict[str,Any]:
    snap=obj.get("component_snapshot") or {}
    interfaces=obj.get("interfaces") or snap.get("interfaces",[]);position=(obj.get("transform") or {}).get("position",[0,0,0]);ox=float(position[0]);oy=float(position[1]);plans=[];unresolved=[]
    for interface in interfaces:
        if interface.get("kind") not in {"mount_pattern","mount_face","servo_mount"}:continue
        pts,d,why=_mount_points(interface)
        if why:
            unresolved.append({"object_id":obj.get("id"),"interface_id":interface.get("id"),"reason":why});continue
        if d is None:
            unresolved.append({"object_id":obj.get("id"),"interface_id":interface.get("id"),"reason":"mounting pattern lacks hole diameter"});continue
        fastener_hint=str((interface.get("metadata") or {}).get("fastener") or "")
        nominal=None
        if fastener_hint.upper().startswith("M"):
            try:nominal=float(fastener_hint[1:])
            except ValueError:nominal=None
        if nominal is None:nominal=max(1.0,d-0.2)
        fastener=select_metric_fastener(nominal,float(plate_thickness_mm)+float(standoff_mm))
        plans.append({"object_id":obj.get("id"),"component_ref":obj.get("component_ref"),"interface_id":interface.get("id"),"hole_diameter_mm":d,"points_mm":[[ox+x,oy+y] for x,y in pts],"fastener_nominal_mm":nominal,"fastener":fastener})
    return {"mounts":plans,"unresolved":unresolved}


def plan_mounting(project:dict[str,Any], plate_id:str, component_ids:list[str]|None=None, *, plate_thickness_mm:float|None=None, standoff_mm:float=6.0)->dict[str,Any]:
    objects={str(o.get("id")):o for o in project.get("objects",[])}
    if plate_id not in objects:raise KeyError(plate_id)
    plate=objects[plate_id];thickness=float(plate_thickness_mm if plate_thickness_mm is not None else (plate.get("params",{}).get("thickness") or plate.get("params",{}).get("z") or 3.0));wanted=set(component_ids or [oid for oid,o in objects.items() if o.get("kind")=="component"]);mounts=[];unresolved=[]
    for oid in sorted(wanted):
        obj=objects.get(oid)
        if not obj or obj.get("kind")!="component":continue
        p=component_mount_plan(obj,thickness,standoff_mm);mounts.extend(p["mounts"]);unresolved.extend(p["unresolved"])
    holes=[{"type":"hole","axis":"z","diameter":m["hole_diameter_mm"],"x":pt[0],"y":pt[1],"mount_for":m["object_id"]} for m in mounts for pt in m["points_mm"]]
    return {"plate_id":plate_id,"plate_thickness_mm":thickness,"mounts":mounts,"holes":holes,"unresolved":unresolved}


def apply_mounting_plan(project:dict[str,Any], plan:dict[str,Any])->dict[str,Any]:
    plate=next((o for o in project.get("objects",[]) if str(o.get("id"))==str(plan.get("plate_id"))),None)
    if not plate:raise KeyError(plan.get("plate_id"))
    existing={(round(float(f.get("x",0)),5),round(float(f.get("y",0)),5),round(float(f.get("diameter",0)),5)) for f in plate.setdefault("features",[]) if f.get("type")=="hole"}
    added=0
    for hole in plan.get("holes",[]):
        key=(round(float(hole.get("x",0)),5),round(float(hole.get("y",0)),5),round(float(hole.get("diameter",0)),5))
        if key not in existing:plate["features"].append(deepcopy(hole));existing.add(key);added+=1
    # Aggregate selected fasteners into BOM without pretending that a fastener was
    # placed when its exact assembly pose has not been solved.
    counts={}
    for mount in plan.get("mounts",[]):
        f=mount.get("fastener")
        if not f:continue
        cid=f["component"]["id"];counts[cid]=counts.get(cid,0)+len(mount.get("points_mm",[]))
    for cid,qty in counts.items():
        row=next((x for x in project.setdefault("bom",[]) if x.get("component_ref")==cid),None)
        if row:row["qty"]=max(int(row.get("qty",0)),qty)
        else:project["bom"].append(registry.bom_item(cid,qty))
    return {"ok":True,"holes_added":added,"fasteners":counts,"unresolved":deepcopy(plan.get("unresolved",[]))}
