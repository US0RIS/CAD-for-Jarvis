from __future__ import annotations

"""Cross-component validation for an electromechanical ForgeCAD assembly.

This is deterministic engineering screening, not circuit simulation. It checks the
semantic connection graph for topology, power, voltage/current constraints and
required interfaces using frozen component data in the canonical project.
"""
from collections import defaultdict,deque
from copy import deepcopy
from typing import Any
from . import physical_components
from . import component_registry as registry

POWER_OUTPUT_KINDS={"electrical_power_output","switched_power","motor_output","fan_power"}
POWER_INPUT_KINDS={"electrical_power_input","electrical_load","motor_power","fan_power","power_input"}
SIGNAL_KINDS={"digital_io","digital_input","digital_output","pwm_input","pwm_output","servo_signal","i2c","spi","uart"}
PASSTHROUGH_CATEGORIES={"load_driver","motor_driver","power","power_converter"}


def _objects(project):return {str(o.get("id")):o for o in project.get("objects",[]) if o.get("id")}
def _iface(obj,iid):
    try:return physical_components.object_interface(obj,iid)
    except Exception:return None
def _meta(i):return i.get("metadata",{}) if isinstance(i,dict) else {}
def _number(meta,*keys):
    for k in keys:
        if meta.get(k) is not None:
            try:return float(meta[k])
            except (TypeError,ValueError):pass
    return None
def _component(obj):return physical_components.component_definition(obj) or {}
def _category(obj):return str(_component(obj).get("category") or obj.get("semantic",{}).get("role") or "")
def _severity_sort(x):return {"error":0,"warning":1,"info":2}.get(x.get("severity"),3)

def _edge_records(project):
    objs=_objects(project);out=[]
    for edge in project.get("connections",[]):
        a=edge.get("a",{});b=edge.get("b",{});ao=objs.get(str(a.get("object_id")));bo=objs.get(str(b.get("object_id")))
        ai=_iface(ao,str(a.get("interface_id"))) if ao else None;bi=_iface(bo,str(b.get("interface_id"))) if bo else None
        out.append({"edge":edge,"a_obj":ao,"b_obj":bo,"a_if":ai,"b_if":bi})
    return out

def _orient_power(rec):
    ai,bi=rec.get("a_if"),rec.get("b_if")
    if not ai or not bi:return None
    ak,bk=str(ai.get("kind")),str(bi.get("kind"))
    ag,bg=str(ai.get("gender","neutral")),str(bi.get("gender","neutral"))
    if ak in POWER_OUTPUT_KINDS or ag=="output":return rec["a_obj"],ai,rec["b_obj"],bi
    if bk in POWER_OUTPUT_KINDS or bg=="output":return rec["b_obj"],bi,rec["a_obj"],ai
    return None

def validate_connections(project:dict[str,Any])->list[dict[str,Any]]:
    risks=[];seen_inputs=defaultdict(list)
    for rec in _edge_records(project):
        edge=rec["edge"];eid=edge.get("id")
        if not rec["a_obj"] or not rec["b_obj"]:
            risks.append({"severity":"error","code":"dangling_connection","connection_id":eid,"message":"Connection references an object that no longer exists."});continue
        if not rec["a_if"] or not rec["b_if"]:
            risks.append({"severity":"error","code":"missing_interface","connection_id":eid,"message":"Connection references an interface that no longer exists in the frozen component definition."});continue
        compat=registry.interface_compatibility(rec["a_if"],rec["b_if"])
        if not compat["compatible"]:risks.append({"severity":"error","code":"connection_now_incompatible","connection_id":eid,"message":"Stored connection is incompatible: "+"; ".join(compat["reasons"])})
        for obj,interface in ((rec["a_obj"],rec["a_if"]),(rec["b_obj"],rec["b_if"])):
            kind=str(interface.get("kind",""));gender=str(interface.get("gender","neutral"))
            if gender=="input" or kind in POWER_INPUT_KINDS or kind in {"digital_input","pwm_input"}:seen_inputs[(obj["id"],interface["id"])].append(eid)
    for (oid,iid),edges in seen_inputs.items():
        if len(edges)>1:risks.append({"severity":"error","code":"multiple_drivers_on_input","object_id":oid,"interface_id":iid,"connection_ids":edges,"message":f"Input {iid} has {len(edges)} independent connections; verify this is an intentional bus rather than multiple drivers."})
    return risks

def _propagate_supply(project):
    """Return component input voltage inferred from modeled DC power paths."""
    inferred={};queue=deque();records=_edge_records(project)
    for rec in records:
        oriented=_orient_power(rec)
        if not oriented:continue
        so,si,do,di=oriented;sm=_meta(si);v=_number(sm,"voltage_v","nominal_voltage_v","output_v")
        if v is not None:inferred[do["id"]]=v;queue.append(do["id"])
    objs=_objects(project);changed=True
    while changed:
        changed=False
        for rec in records:
            oriented=_orient_power(rec)
            if not oriented:continue
            so,si,do,di=oriented
            if so["id"] in inferred and do["id"] not in inferred and _category(so) in PASSTHROUGH_CATEGORIES:
                inferred[do["id"]]=inferred[so["id"]];changed=True
            # A driver receives its rail from upstream, so its switched output carries that rail.
            if so["id"] in inferred and _category(so) in PASSTHROUGH_CATEGORIES and do["id"] not in inferred:
                inferred[do["id"]]=inferred[so["id"]];changed=True
    return inferred

def validate_power(project:dict[str,Any])->list[dict[str,Any]]:
    risks=[];records=_edge_records(project);inferred=_propagate_supply(project);source_loads=defaultdict(float)
    for rec in records:
        oriented=_orient_power(rec)
        if not oriented:continue
        so,si,do,di=oriented;sm,dm=_meta(si),_meta(di);sv=_number(sm,"voltage_v","nominal_voltage_v","output_v")
        if sv is None:sv=inferred.get(so["id"])
        dv=_number(dm,"voltage_v","nominal_voltage_v")
        dmin=_number(dm,"min_voltage_v","input_min_v","logic_min_v");dmax=_number(dm,"max_voltage_v","input_max_v","logic_max_v")
        if sv is not None:
            if dv is not None and abs(sv-dv)>max(.25,.05*max(abs(sv),abs(dv))):risks.append({"severity":"error","code":"voltage_mismatch","connection_id":rec["edge"].get("id"),"message":f"{so.get('name')} supplies approximately {sv:g} V but {do.get('name')} expects {dv:g} V."})
            if dmin is not None and sv<dmin:risks.append({"severity":"error","code":"undervoltage","connection_id":rec["edge"].get("id"),"message":f"{do.get('name')} input minimum is {dmin:g} V; modeled supply is {sv:g} V."})
            if dmax is not None and sv>dmax:risks.append({"severity":"error","code":"overvoltage","connection_id":rec["edge"].get("id"),"message":f"{do.get('name')} input maximum is {dmax:g} V; modeled supply is {sv:g} V."})
        load_current=_number(dm,"current_a","rated_current_a","max_current_a","recommended_current_a")
        source_max=_number(sm,"max_current_a","continuous_current_a","peak_current_a")
        if load_current is not None and source_max is not None and load_current>source_max+1e-9:risks.append({"severity":"error","code":"driver_overcurrent","connection_id":rec["edge"].get("id"),"message":f"{do.get('name')} requires {load_current:g} A but {so.get('name')} interface is rated {source_max:g} A."})
        if load_current is not None:source_loads[so["id"]]+=load_current
    # Trace final load current through one upstream driver stage to a DC source.
    objs=_objects(project)
    incoming={}
    outgoing=defaultdict(list)
    for rec in records:
        oriented=_orient_power(rec)
        if oriented:
            so,si,do,di=oriented;outgoing[so["id"]].append((do,di));incoming[do["id"]]=(so,si)
    final_currents={}
    for oid,obj in objs.items():
        total=0.0
        for do,di in outgoing.get(oid,[]):
            cur=_number(_meta(di),"current_a","rated_current_a","max_current_a")
            if cur is not None:total+=cur
        if total:final_currents[oid]=total
    for driver_id,current in final_currents.items():
        upstream=incoming.get(driver_id)
        if upstream:
            source,source_if=upstream;limit=_number(_meta(source_if),"max_current_a","continuous_current_a")
            if limit is not None and current>limit+1e-9:risks.append({"severity":"error","code":"supply_overload","object_id":source["id"],"message":f"Downstream modeled loads require at least {current:g} A while {source.get('name')} output is rated {limit:g} A."})
    return risks

def validate_signals(project:dict[str,Any])->list[dict[str,Any]]:
    risks=[]
    for rec in _edge_records(project):
        ai,bi=rec.get("a_if"),rec.get("b_if")
        if not ai or not bi:continue
        if str(ai.get("kind")) not in SIGNAL_KINDS and str(bi.get("kind")) not in SIGNAL_KINDS:continue
        am,bm=_meta(ai),_meta(bi);av=_number(am,"logic_voltage_v","voltage_v");bv=_number(bm,"logic_voltage_v","voltage_v");bmin=_number(bm,"logic_min_v","min_voltage_v");bmax=_number(bm,"logic_max_v","max_voltage_v")
        if av is not None and bmin is not None and av<bmin:risks.append({"severity":"error","code":"logic_undervoltage","connection_id":rec["edge"].get("id"),"message":f"Logic source {av:g} V is below receiver minimum {bmin:g} V."})
        if av is not None and bmax is not None and av>bmax:risks.append({"severity":"error","code":"logic_overvoltage","connection_id":rec["edge"].get("id"),"message":f"Logic source {av:g} V exceeds receiver maximum {bmax:g} V."})
        if bv is not None and av is not None and abs(av-bv)>1.0:risks.append({"severity":"warning","code":"logic_level_difference","connection_id":rec["edge"].get("id"),"message":f"Connected logic interfaces advertise {av:g} V and {bv:g} V; verify level compatibility."})
    return risks

def validate_system(project:dict[str,Any])->dict[str,Any]:
    base=physical_components.reality_check(project);risks=list(base.get("risks",[]));risks.extend(validate_connections(project));risks.extend(validate_power(project));risks.extend(validate_signals(project));risks.sort(key=_severity_sort);counts={s:sum(x.get("severity")==s for x in risks) for s in ("error","warning","info")};return {"ok":counts["error"]==0,"counts":counts,"risks":risks,"components":base.get("components",0),"connections":len(project.get("connections",[])),"scope":"deterministic topology/power/interface screening; not SPICE, certification, or physical validation"}
