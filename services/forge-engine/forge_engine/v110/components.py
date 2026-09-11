from __future__ import annotations
import json, math
from copy import deepcopy
from pathlib import Path
from typing import Any

REGISTRY: list[dict[str,Any]]=[]
def add(id,category,manufacturer,model,**kw):
    REGISTRY.append({"id":id,"category":category,"manufacturer":manufacturer,"model":model,"name":f"{manufacturer} {model}",**kw})

# Compute / controllers
add("compute.raspberry_pi_5_8gb","compute","Raspberry Pi","5 8GB",dimensions_mm=[85,56,17],mass_g=46,power_w=12,voltage_v=5,programmable=True,code_platform="python/linux",material="pcb_fr4",geometry_profile="raspberry_pi_5",mounting_pattern_mm=[58,49],mount_hole_diameter_mm=2.7,mechanical_source="https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf",official_step_available=True,tags=["sbc","linux","gpio","physical-cad"])
add("compute.raspberry_pi_zero_2w","compute","Raspberry Pi","Zero 2 W",dimensions_mm=[65,30,13],mass_g=12,power_w=3,voltage_v=5,programmable=True,code_platform="python/linux",tags=["sbc","linux","compact"])
add("mcu.raspberry_pi_pico_2","microcontroller","Raspberry Pi","Pico 2",dimensions_mm=[51,21,4],mass_g=5,power_w=.5,voltage_v=3.3,programmable=True,code_platform="micropython",tags=["mcu","rp2350"])
add("mcu.arduino_nano_esp32","microcontroller","Arduino","Nano ESP32",dimensions_mm=[45,18,6],mass_g=7,power_w=1,voltage_v=3.3,programmable=True,code_platform="arduino/c++",tags=["wifi","bluetooth","esp32"])
add("mcu.teensy_41","microcontroller","PJRC","Teensy 4.1",dimensions_mm=[61,18,5],mass_g=6,power_w=1.2,voltage_v=3.3,programmable=True,code_platform="arduino/c++",tags=["realtime","fast"])
# Motors / servos / solenoids
for nema,face,length,torque,mass in [(8,20,33,.04,80),(11,28,34,.10,180),(14,35,36,.22,280),(17,42,40,.45,350),(17,42,48,.59,480),(23,57,56,1.2,700),(23,57,76,2.0,1050)]:
    add(f"motor.nema{nema}.{length}","stepper_motor","Generic",f"NEMA {nema} {length}mm",dimensions_mm=[face,face,length],mass_g=mass,holding_torque_nm=torque,voltage_v=24,tags=["stepper",f"nema{nema}"])
for model,torque,speed,mass,size in [("SG90",.18,.12,9,[23,12,29]),("MG996R",1.0,.17,55,[41,20,44]),("DS3218",2.0,.16,60,[40,20,40])]:
    add(f"servo.{model.lower()}","servo","Generic",model,dimensions_mm=size,mass_g=mass,stall_torque_nm=torque,speed_s_60deg=speed,voltage_v=6,tags=["servo"])
for stroke,force in [(5,5),(10,10),(15,20),(20,30),(30,45),(40,60)]:
    add(f"solenoid.pushpull.{stroke}.{force}","solenoid","Generic",f"Push-Pull {stroke}mm {force}N",dimensions_mm=[25,25,55+stroke],mass_g=180+stroke*2,stroke_mm=stroke,force_n=force,voltage_v=12,duty_cycle=.25,tags=["linear","push-pull"])
# Bearings
for series,od_factor,width_factor in [("6000",2.6,.8),("6200",2.8,.85),("6300",3.1,.95)]:
    for bore in [5,6,8,10,12,15,17,20,25,30]:
        od=round(max(bore+8,bore*od_factor)); width=round(max(5,bore*width_factor));
        add(f"bearing.{series}.{bore}","bearing","Generic",f"{series} series {bore}mm bore",dimensions_mm=[od,od,width],mass_g=round(0.007*od*od*width,1),bore_mm=bore,outer_diameter_mm=od,width_mm=width,radial_load_n=round(120*od),tags=["deep-groove","ball-bearing"])
# Fans
for side in [20,25,30,40,50,60,80,92,120]:
    for thick in ([10] if side<40 else [10,15,25]):
        add(f"fan.{side}x{thick}","fan","Generic",f"{side}x{side}x{thick}mm PWM Fan",dimensions_mm=[side,side,thick],mass_g=round(side*side*thick/2500,1),voltage_v=12,airflow_cfm=round(side*side/190,1),pwm=True,tags=["cooling","pwm"])
# Sensors
for id_,maker,model,size,typ in [
 ("sensor.bno085","CEVA","BNO085 IMU",[20,20,4],"imu"),("sensor.vl53l1x","ST","VL53L1X ToF",[13,18,3],"distance"),("sensor.hx711","Avia","HX711 Load Cell ADC",[34,20,4],"load"),("sensor.bmp390","Bosch","BMP390",[10,10,3],"pressure"),("sensor.as5600","ams OSRAM","AS5600",[23,23,4],"angle")]:
    add(id_,"sensor",maker,model,dimensions_mm=size,mass_g=4,sensor_type=typ,voltage_v=3.3,tags=[typ])
# Batteries
for cells in [1,2,3,4,6]:
    for cap in [500,1000,2200,5000,10000]:
        v=3.7*cells; mass=cap*cells*.018
        add(f"battery.lipo.{cells}s.{cap}","battery","Generic",f"LiPo {cells}S {cap}mAh",dimensions_mm=[max(30,cap/100),max(20,cells*12),max(8,cells*5)],mass_g=round(mass),voltage_v=round(v,1),capacity_mah=cap,energy_wh=round(v*cap/1000,1),tags=["lipo",f"{cells}s"])
# Fasteners
for dia in [2,2.5,3,4,5,6,8,10,12]:
    for length in [6,8,10,12,16,20,25,30,40,50,60,80]:
        if length < dia*1.5: continue
        add(f"fastener.m{str(dia).replace('.','p')}x{length}","fastener","ISO",f"4762 M{dia}x{length} SHCS",dimensions_mm=[dia*1.7,dia*1.7,length+dia],mass_g=round(.00617*dia*dia*length,2),diameter_mm=dia,length_mm=length,grade="12.9",tags=["socket-head","metric"])
# Linear motion
for rail in [7,9,12,15,20,25]:
    for length in [100,200,300,500,800,1000]:
        add(f"linear.mgn{rail}.{length}","linear_motion","Generic",f"MGN{rail} rail {length}mm + carriage",dimensions_mm=[length,rail*2.2,rail*1.5],mass_g=round(length*rail*.015),rail_size_mm=rail,travel_mm=length-40,static_load_n=rail*400,tags=["linear-rail"])
# Power electronics
for amps in [3,5,10,20,30,40,60]:
    add(f"power.buck.{amps}","power","Generic",f"Buck Converter {amps}A",dimensions_mm=[50+amps*.5,35,15],mass_g=25+amps,max_current_a=amps,input_max_v=36,output_v=5,tags=["dc-dc","buck"])


def all_components(category: str|None=None):
    vals=REGISTRY if not category else [x for x in REGISTRY if x["category"]==category]
    return deepcopy(vals)
def component_by_id(cid: str):
    for c in REGISTRY:
        if c["id"]==cid:return deepcopy(c)
    raise KeyError(cid)
def categories():return sorted({x["category"] for x in REGISTRY})

def _constraint(c:dict[str,Any], key:str, target:Any)->tuple[bool,float]:
    if target is None:return True,0
    if key.startswith("max_"):
        field=key[4:]; val=c.get(field)
        if val is None:return False,1e4
        return float(val)<=float(target), max(0,(float(val)-float(target))/(abs(float(target))+1e-9))
    if key.startswith("min_"):
        field=key[4:];val=c.get(field)
        if val is None:return False,1e4
        return float(val)>=float(target),max(0,(float(target)-float(val))/(abs(float(target))+1e-9))
    val=c.get(key);ok=(val==target);return ok,0 if ok else 1

def search_components(query:str="",category:str|None=None,constraints:dict[str,Any]|None=None,weights:dict[str,float]|None=None,limit:int=20,include_infeasible:bool=True):
    q=query.lower().strip();constraints=constraints or {};weights=weights or {};rows=[]
    for c in REGISTRY:
        if category and c["category"]!=category:continue
        blob=json.dumps(c).lower()
        if q and not all(tok in blob for tok in q.split()):continue
        feasible=True; penalty=0
        for k,t in constraints.items():
            ok,p=_constraint(c,k,t);feasible &= ok;penalty += p*float(weights.get(k,1))
        if not feasible and not include_infeasible:continue
        text_bonus=sum(blob.count(tok) for tok in q.split()) if q else 0
        rows.append((0 if feasible else 1,penalty,-text_bonus,c))
    rows.sort(key=lambda x:(x[0],x[1],x[2],x[3]["name"]))
    return {"query":query,"category":category,"count":min(limit,len(rows)),"total_registry":len(REGISTRY),"results":[deepcopy(x[3])|{"feasible":x[0]==0,"constraint_penalty":x[1]} for x in rows[:limit]]}

def import_components(payload):
    items=payload if isinstance(payload,list) else [payload];added=[]
    for c in items:
        if not isinstance(c,dict):continue
        item=deepcopy(c);item.setdefault("id",f"custom.{len(REGISTRY)+1}");item.setdefault("category","custom");item.setdefault("manufacturer","Custom");item.setdefault("model",item["id"]);item.setdefault("name",f"{item['manufacturer']} {item['model']}")
        REGISTRY.append(item);added.append(item)
    return {"ok":True,"added":added,"total_registry":len(REGISTRY)}
def import_catalog_pack_bytes(filename,data):return import_components(json.loads(data.decode("utf-8")))
def provider_status():return {"providers":[],"note":"v1 ships a large offline deterministic registry; live supplier providers can be added without changing the canonical design model."}
def search_provider(provider,query,limit=25,import_results=False):raise RuntimeError("No live supplier provider configured")
