from __future__ import annotations

"""Physical assembly collision and clearance screening for ForgeCAD v1.1.

The checker uses transformed OpenCascade geometry supplied by the CAD core.  AABB
broad phase keeps it inexpensive; overlapping candidates are confirmed with a
boolean common when possible.  Mechanical mates are excluded from collision errors
because intended contact belongs to the joint definition, not the clearance screen.
"""
import math
from itertools import combinations
from typing import Any,Callable


def _box(shape):
    b=shape.BoundingBox();return (float(b.xmin),float(b.xmax),float(b.ymin),float(b.ymax),float(b.zmin),float(b.zmax))

def _overlap(a,b):
    return [min(a[1],b[1])-max(a[0],b[0]),min(a[3],b[3])-max(a[2],b[2]),min(a[5],b[5])-max(a[4],b[4])]

def _distance(a,b):
    gaps=[]
    for lo1,hi1,lo2,hi2 in ((a[0],a[1],b[0],b[1]),(a[2],a[3],b[2],b[3]),(a[4],a[5],b[4],b[5])):
        gaps.append(max(0.0,lo2-hi1,lo1-hi2))
    return math.sqrt(sum(x*x for x in gaps))

def _mechanically_connected(project):
    pairs=set()
    for edge in project.get("connections",[]):
        if str(edge.get("kind"))!="mechanical":continue
        a=str((edge.get("a") or {}).get("object_id") or "");b=str((edge.get("b") or {}).get("object_id") or "")
        if a and b:pairs.add(tuple(sorted((a,b))))
    return pairs

def _keepout_aabbs(obj):
    out=[];pos=(obj.get("transform") or {}).get("position",[0,0,0]);ox,oy,oz=[float(x) for x in pos]
    snap=obj.get("component_snapshot") or {}
    for ko in snap.get("keepouts",[]):
        dims=ko.get("dimensions_mm") or ko.get("size_mm");center=ko.get("center_mm") or ko.get("position_mm") or [0,0,0]
        if not isinstance(dims,(list,tuple)) or len(dims)<3:continue
        cx,cy,cz=[float(x) for x in center[:3]];x,y,z=[float(x) for x in dims[:3]]
        out.append((ox+cx-x/2,ox+cx+x/2,oy+cy-y/2,oy+cy+y/2,oz+cz-z/2,oz+cz+z/2,ko))
    return out

def validate_assembly(project:dict[str,Any], shape_builder:Callable[[dict[str,Any]],Any], *, min_clearance_mm:float=1.0, intersection_tolerance_mm3:float=0.01)->dict[str,Any]:
    shapes={};bounds={};risks=[]
    visible=[o for o in project.get("objects",[]) if o.get("visible",True)]
    for obj in visible:
        try:
            sh=shape_builder(obj);shapes[str(obj["id"])]=sh;bounds[str(obj["id"])]=_box(sh)
        except Exception as e:
            risks.append({"severity":"warning","code":"geometry_unavailable_for_collision","object_id":obj.get("id"),"message":f"Could not build {obj.get('name')} for collision screening: {e}"})
    connected=_mechanically_connected(project);collisions=[];clearances=[]
    objects={str(o.get("id")):o for o in visible}
    for aid,bid in combinations(sorted(bounds),2):
        a,b=bounds[aid],bounds[bid];pair=tuple(sorted((aid,bid)));ov=_overlap(a,b)
        if all(x>0 for x in ov):
            if pair in connected:continue
            volume=max(0.0,ov[0]*ov[1]*ov[2]);exact=False
            try:
                common=shapes[aid].intersect(shapes[bid]);volume=float(common.Volume());exact=True
            except Exception:pass
            if volume>float(intersection_tolerance_mm3):
                item={"a_id":aid,"b_id":bid,"a_name":objects[aid].get("name"),"b_name":objects[bid].get("name"),"intersection_mm3":volume,"exact_boolean":exact};collisions.append(item);risks.append({"severity":"error","code":"physical_collision",**item,"message":f"{item['a_name']} intersects {item['b_name']} by approximately {volume:.3f} mm³."})
        else:
            d=_distance(a,b)
            if 0<d<float(min_clearance_mm) and pair not in connected:
                item={"a_id":aid,"b_id":bid,"a_name":objects[aid].get("name"),"b_name":objects[bid].get("name"),"clearance_mm":d};clearances.append(item);risks.append({"severity":"warning","code":"low_clearance",**item,"message":f"{item['a_name']} and {item['b_name']} have only {d:.3f} mm broad-phase clearance."})
    # Keepouts remain conservative AABBs. They are useful even when an electrical
    # connector has no detailed solid geometry.
    for owner in visible:
        for ko in _keepout_aabbs(owner):
            kb=ko[:6];meta=ko[6]
            for oid,ob in bounds.items():
                if oid==str(owner.get("id")):continue
                ov=_overlap(kb,ob)
                if all(x>0 for x in ov):
                    risks.append({"severity":"error","code":"keepout_violation","object_id":oid,"keepout_owner_id":owner.get("id"),"message":f"{objects[oid].get('name')} intrudes into {owner.get('name')} keepout {meta.get('name') or meta.get('id') or 'region'}."})
    counts={s:sum(r.get("severity")==s for r in risks) for s in ("error","warning","info")}
    return {"ok":counts["error"]==0,"counts":counts,"risks":risks,"collisions":collisions,"low_clearances":clearances,"objects_checked":len(bounds),"min_clearance_mm":float(min_clearance_mm),"scope":"geometric interference/clearance screening; manufacturing tolerances and flexible wiring are not modeled"}
