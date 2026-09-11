from __future__ import annotations

"""ForgeCAD v1.1 acceptance assembly.

This deliberately exercises the product thesis with real purchased parts instead
of synthetic boxes: Raspberry Pi 5 control, a manufacturer-sourced 12->5 V
converter, a MOSFET load driver, a 12 V solenoid, and a 12 V AC/DC supply mounted
on a fabricated plate.  The project is deterministic and requires no LLM, making
it suitable for CI as well as a built-in demo/template.
"""
from copy import deepcopy
from datetime import datetime,timezone
from typing import Any
from . import component_registry as registry
from . import mounting
from . import physical_components
from . import system_validation

IDS={
    "plate":"v110-acceptance-plate",
    "pi":"v110-acceptance-pi5",
    "driver":"v110-acceptance-mosfet",
    "solenoid":"v110-acceptance-solenoid",
    "supply":"v110-acceptance-supply",
    "buck":"v110-acceptance-buck",
}
COMPONENTS={
    "pi":"compute.raspberry_pi_5_8gb",
    "driver":"driver.adafruit.mosfet_5648",
    "solenoid":"solenoid.adafruit.412",
    "supply":"power.meanwell.lrs_75_12",
    "buck":"power.pololu.d24v50f5",
}
POSITIONS={
    "supply":[-62.0,35.0,17.0],
    "pi":[55.0,35.0,8.0],
    # The solenoid parametric model extends below its nominal envelope because the
    # return/plunger geometry is represented explicitly.  11 mm gives real plate
    # clearance rather than suppressing an interference reported by the checker.
    "solenoid":[-63.0,-55.0,11.0],
    "driver":[18.0,-52.0,5.0],
    "buck":[65.0,-52.0,6.0],
}


def _transform(position):return {"position":[float(x) for x in position],"rotation_deg":[0.0,0.0,0.0],"scale":[1.0,1.0,1.0]}

def _instance(key:str)->dict[str,Any]:
    cid=COMPONENTS[key];obj=registry.make_project_object(cid,name=None,transform=_transform(POSITIONS[key]));obj.update({"id":IDS[key],"features":[],"visible":True});return obj

def _bom_for(objects):
    counts={}
    for o in objects:
        cid=o.get("component_ref")
        if cid:counts[cid]=counts.get(cid,0)+1
    return [registry.bom_item(cid,qty) for cid,qty in sorted(counts.items())]

def _plate()->dict[str,Any]:
    return {"id":IDS["plate"],"name":"v1.1 Acceptance Mounting Plate","kind":"box","params":{"x":240.0,"y":180.0,"z":3.0},"material":"aluminum_6061_t6","transform":_transform([0,0,-1.5]),"features":[
        {"type":"hole","diameter":4.0,"axis":"z","x":-110.0,"y":-80.0,"purpose":"chassis_mount"},
        {"type":"hole","diameter":4.0,"axis":"z","x":110.0,"y":-80.0,"purpose":"chassis_mount"},
        {"type":"hole","diameter":4.0,"axis":"z","x":110.0,"y":80.0,"purpose":"chassis_mount"},
        {"type":"hole","diameter":4.0,"axis":"z","x":-110.0,"y":80.0,"purpose":"chassis_mount"},
    ],"interfaces":[],"semantic":{"role":"fabricated_mounting_structure","tags":["v1.1-acceptance","fabricated","mounting-plate"],"description":"Generated aluminum base for the ForgeCAD v1.1 real-component acceptance assembly."},"visible":True}

def _connect(project,a_key,a_if,b_key,b_if,kind="auto"):
    objects={o["id"]:o for o in project["objects"]};a=objects[IDS[a_key]];b=objects[IDS[b_key]];return physical_components.connect_interfaces(project,a,a_if,b,b_if,kind)


def build_project()->dict[str,Any]:
    missing=[]
    for cid in COMPONENTS.values():
        try:registry.component_by_id(cid)
        except KeyError:missing.append(cid)
    if missing:raise RuntimeError("Acceptance catalog incomplete: "+", ".join(missing))
    purchased=[_instance(k) for k in ("supply","pi","solenoid","driver","buck")];plate=_plate();stamp=datetime.now(timezone.utc).isoformat();project={
        "schema":4,"version":"1.1.0-dev","name":"ForgeCAD v1.1 Real-System Acceptance Assembly","created_at":stamp,"updated_at":stamp,
        "objects":[plate,*purchased],"joints":[],"loads":[],"constraints":[],"requirements":[
            {"id":"req-real-components","metric":"object_count","op":">=","target":6,"description":"Acceptance assembly contains fabricated structure plus real purchased hardware."}
        ],"bom":_bom_for(purchased),"connections":[],"simulations":[],"notebook":[
            {"id":"acceptance-purpose","text":"v1.1 acceptance: Pi 5 controls a 12 V solenoid through a real MOSFET driver; the MEAN WELL supply powers both the solenoid rail and a Pololu 5 V regulator for the Pi."}
        ],"settings":{"units":"mm","coordinate_system":"Z-up"},"ledger":[]}
    # Electrical/control graph.
    _connect(project,"supply","dc_out","driver","power_in","electrical")
    _connect(project,"supply","dc_out","buck","vin","electrical")
    _connect(project,"buck","vout","pi","usb_c_power","electrical")
    _connect(project,"pi","gpio40","driver","signal","electrical")
    _connect(project,"driver","load_out","solenoid","coil","electrical")
    # Generate only mounting holes supported by frozen manufacturer metadata.
    plan=mounting.plan_mounting(project,IDS["plate"],[IDS["pi"],IDS["buck"],IDS["supply"],IDS["solenoid"]],plate_thickness_mm=3.0,standoff_mm=6.0)
    mounting.apply_mounting_plan(project,plan)
    # The Pi pattern is fully defined. Record the mechanical relation in the same
    # canonical connection graph; unresolved mount metadata stays explicit below.
    pi_mount=next((m for m in plan["mounts"] if m["object_id"]==IDS["pi"]),None)
    if pi_mount:
        plate["interfaces"].append({"id":"pi_standoffs","kind":"board_standoffs","position_mm":[POSITIONS["pi"][0],POSITIONS["pi"][1],0.0],"axis":[0,0,1],"gender":"neutral","required":False,"mate":["mount_pattern"],"metadata":{"generated_from":COMPONENTS["pi"]}})
        objects={o["id"]:o for o in project["objects"]};physical_components.connect_interfaces(project,plate,"pi_standoffs",objects[IDS["pi"]],"mount","mechanical")
    project["notebook"].append({"id":"mounting-resolution","text":"Mounting automation generated only manufacturer-supported hole patterns.","mounting_unresolved":deepcopy(plan["unresolved"])})
    return project


def acceptance_report(project:dict[str,Any],shape_builder=None)->dict[str,Any]:
    system=system_validation.validate_system(project);report={"system":system,"mounting_unresolved":next((n.get("mounting_unresolved",[]) for n in project.get("notebook",[]) if n.get("id")=="mounting-resolution"),[])}
    if shape_builder is not None:
        import assembly_validation
        report["assembly"]=assembly_validation.validate_assembly(project,shape_builder,min_clearance_mm=1.0)
    report["ok"]=system.get("ok",False) and report.get("assembly",{"ok":True}).get("ok",True)
    return report


def install_into_core()->dict[str,Any]:
    """Replace the active workspace with a clean acceptance project/template."""
    import core
    project=core.upgrade_project(build_project())
    with core.LOCK:
        core.PROJECT.clear();core.PROJECT.update(project);core.BRANCHES.clear();core.DESIGNS.clear();core.ACTIVE_DESIGN="main"
        core.BRANCHES["main"]=core._snap(core.PROJECT);core.DESIGNS["main"]={"name":"main","parent":None,"status":"untested","note":"v1.1 deterministic acceptance assembly","physical_verified":False,"created_at":core.now(),"updated_at":core.now()};core.HISTORY.clear();core.REDO.clear();core.HISTORY.append(core._snap(core.PROJECT));core.persist()
    return core.PROJECT
