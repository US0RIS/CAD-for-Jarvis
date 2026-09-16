from __future__ import annotations
import json, math
from copy import deepcopy
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

for cid,maker,model,dims,mass,platform,tags in [
    ("compute.raspberry_pi_4b","Raspberry Pi","4 Model B",[85,56,17],46,"python/linux",["sbc","linux","gpio"]),
    ("compute.raspberry_pi_3b_plus","Raspberry Pi","3 Model B+",[85,56,17],50,"python/linux",["sbc","linux","gpio"]),
    ("compute.jetson_orin_nano","NVIDIA","Jetson Orin Nano Developer Kit",[100,79,22],171,"python/linux",["sbc","linux","cuda","ai"]),
    ("compute.beaglebone_black","BeagleBoard","BeagleBone Black",[86.4,53.3,18],40,"python/linux",["sbc","linux","gpio"]),
    ("mcu.arduino_uno_r4_wifi","Arduino","UNO R4 WiFi",[68.9,53.4,15],32,"arduino/c++",["mcu","wifi","uno"]),
    ("mcu.arduino_mega_2560","Arduino","Mega 2560 Rev3",[101.5,53.3,15],37,"arduino/c++",["mcu","mega","gpio"]),
    ("mcu.arduino_nano_every","Arduino","Nano Every",[45,18,6],5,"arduino/c++",["mcu","nano"]),
    ("mcu.esp32_devkitc","Espressif","ESP32-DevKitC",[54.4,27.9,10],10,"esp-idf",["mcu","wifi","bluetooth","esp32"]),
    ("mcu.adafruit_feather_rp2040","Adafruit","Feather RP2040",[51,23,8],6,"circuitpython",["mcu","rp2040","feather"]),
    ("mcu.adafruit_feather_esp32s3","Adafruit","Feather ESP32-S3",[51,23,8],7,"circuitpython",["mcu","wifi","bluetooth","esp32s3","feather"]),
    ("mcu.seeed_xiao_rp2040","Seeed Studio","XIAO RP2040",[21,17.5,4],3,"arduino/c++",["mcu","rp2040","xiao"]),
    ("mcu.seeed_xiao_esp32s3","Seeed Studio","XIAO ESP32S3",[21,17.5,4],3,"arduino/c++",["mcu","wifi","bluetooth","xiao"]),
    ("mcu.stm32_nucleo_f446re","STMicroelectronics","NUCLEO-F446RE",[70,82.5,15],33,"mbed/c++",["mcu","stm32","nucleo"]),
    ("mcu.microbit_v2","BBC","micro:bit v2",[52,43,6],8,"micropython",["mcu","education","bluetooth"]),
]:
    category="compute" if cid.startswith("compute.") else "microcontroller"
    add(cid,category,maker,model,dimensions_mm=dims,mass_g=mass,voltage_v=5 if category=="compute" else 3.3,programmable=True,code_platform=platform,tags=tags)

# Motors / servos / solenoids
for nema,face,length,torque,mass in [(8,20,33,.04,80),(11,28,34,.10,180),(14,35,36,.22,280),(17,42,40,.45,350),(17,42,48,.59,480),(23,57,56,1.2,700),(23,57,76,2.0,1050)]:
    add(f"motor.nema{nema}.{length}","stepper_motor","Generic",f"NEMA {nema} {length}mm",dimensions_mm=[face,face,length],mass_g=mass,holding_torque_nm=torque,voltage_v=24,tags=["stepper",f"nema{nema}"])
for model,torque,speed,mass,size in [("SG90",.18,.12,9,[23,12,29]),("MG996R",1.0,.17,55,[41,20,44]),("DS3218",2.0,.16,60,[40,20,40])]:
    add(f"servo.{model.lower()}","servo","Generic",model,dimensions_mm=size,mass_g=mass,stall_torque_nm=torque,speed_s_60deg=speed,voltage_v=6,tags=["servo"])
for stroke,force in [(5,5),(10,10),(15,20),(20,30),(30,45),(40,60)]:
    add(f"solenoid.pushpull.{stroke}.{force}","solenoid","Generic",f"Push-Pull {stroke}mm {force}N",dimensions_mm=[25,25,55+stroke],mass_g=180+stroke*2,stroke_mm=stroke,force_n=force,voltage_v=12,duty_cycle=.25,tags=["linear","push-pull"])

for frame,length,current,torque in [(17,20,.7,.18),(17,34,1.0,.30),(17,60,2.0,.75),(23,41,1.8,.9),(23,100,3.0,3.0),(34,66,4.0,5.5)]:
    face={17:42,23:57,34:86}[frame]
    add(f"motor.stepper.nema{frame}.{length}mm","stepper_motor","Generic",f"NEMA {frame} {length}mm High-Torque Stepper",dimensions_mm=[face,face,length],mass_g=round(face*length*.18),holding_torque_nm=torque,rated_current_a=current,voltage_v=24,tags=["stepper",f"nema{frame}","high-torque"])

for can,d,l,mass in [("130",20,25,18),("180",24,32,30),("370",24,38,70),("550",36,57,220),("775",42,67,350),("895",48,70,500)]:
    for voltage in (6,12,24):
        add(f"motor.dc.{can}.{voltage}v","dc_motor","Generic",f"RS-{can} Brushed DC Motor {voltage}V",dimensions_mm=[d,d,l],mass_g=mass,voltage_v=voltage,no_load_rpm=round(18000*12/voltage),tags=["dc-motor","brushed",f"{voltage}v"])

for diameter in (16,20,25,37):
    for ratio in (10,20,30,50,100,150,300):
        for voltage in (6,12):
            length=30+diameter*.7
            add(f"motor.gear.{diameter}mm.{ratio}to1.{voltage}v","gearmotor","Generic",f"{diameter}mm Metal Gearmotor {ratio}:1 {voltage}V",dimensions_mm=[diameter,diameter,length],mass_g=round(diameter*length*.11),voltage_v=voltage,gear_ratio=ratio,no_load_rpm=max(8,round(12000/ratio)),tags=["dc-motor","gearmotor","metal-gear",f"{ratio}:1"])

for diameter,length in [(22,28),(28,36),(35,42),(42,50),(50,55),(63,65)]:
    for kv in (300,500,800,1100,1500):
        add(f"motor.bldc.{diameter}x{length}.{kv}kv","bldc_motor","Generic",f"{diameter}x{length}mm Brushless Motor {kv}KV",dimensions_mm=[diameter,diameter,length],mass_g=round(diameter*length*.08),kv_rpm_per_v=kv,max_voltage_v=24,tags=["bldc","brushless",f"{kv}kv"])

for width,torque in [(12,.18),(17,.35),(20,.7),(20,1.2),(25,2.0),(30,3.5)]:
    for voltage in (5,6,7.4):
        add(f"servo.standard.{width}mm.{str(voltage).replace('.','p')}v","servo","Generic",f"{width}mm Digital Servo {voltage}V",dimensions_mm=[width*2,width,width*2.1],mass_g=round(width*1.4),stall_torque_nm=torque,speed_s_60deg=.12,voltage_v=voltage,tags=["servo","digital"])

# Bearings
for series,od_factor,width_factor in [("6000",2.6,.8),("6200",2.8,.85),("6300",3.1,.95)]:
    for bore in [5,6,8,10,12,15,17,20,25,30]:
        od=round(max(bore+8,bore*od_factor)); width=round(max(5,bore*width_factor))
        add(f"bearing.{series}.{bore}","bearing","Generic",f"{series} series {bore}mm bore",dimensions_mm=[od,od,width],mass_g=round(0.007*od*od*width,1),bore_mm=bore,outer_diameter_mm=od,width_mm=width,radial_load_n=round(120*od),tags=["deep-groove","ball-bearing"])
for family,od_factor,width_factor in [("flanged",2.5,.8),("thin",2.0,.45),("heavy",3.2,1.0)]:
    for bore in [3,4,5,6,8,10,12,15,17,20,25,30,35,40]:
        od=round(max(bore+6,bore*od_factor)); width=round(max(4,bore*width_factor))
        add(f"bearing.{family}.{bore}","bearing","Generic",f"{family.title()} Ball Bearing {bore}mm Bore",dimensions_mm=[od,od,width],mass_g=round(.006*od*od*width,1),bore_mm=bore,outer_diameter_mm=od,width_mm=width,tags=["bearing",family])
for bore in [8,10,12,15,17,20,25,30,35,40]:
    add(f"bearing.pillowblock.ucp.{bore}","bearing","Generic",f"UCP Pillow Block {bore}mm",dimensions_mm=[bore*4.8,bore*2.3,bore*2.8],mass_g=round(bore*18),bore_mm=bore,outer_diameter_mm=bore*2.1,width_mm=bore*1.2,tags=["pillow-block","mounted-bearing"])

# Fans
for side in [20,25,30,40,50,60,80,92,120]:
    for thick in ([10] if side<40 else [10,15,25]):
        add(f"fan.{side}x{thick}","fan","Generic",f"{side}x{side}x{thick}mm PWM Fan",dimensions_mm=[side,side,thick],mass_g=round(side*side*thick/2500,1),voltage_v=12,airflow_cfm=round(side*side/190,1),pwm=True,tags=["cooling","pwm"])

# Sensors
for id_,maker,model,size,typ in [
 ("sensor.bno085","CEVA","BNO085 IMU",[20,20,4],"imu"),("sensor.vl53l1x","ST","VL53L1X ToF",[13,18,3],"distance"),("sensor.hx711","Avia","HX711 Load Cell ADC",[34,20,4],"load"),("sensor.bmp390","Bosch","BMP390",[10,10,3],"pressure"),("sensor.as5600","ams OSRAM","AS5600",[23,23,4],"angle")]:
    add(id_,"sensor",maker,model,dimensions_mm=size,mass_g=4,sensor_type=typ,voltage_v=3.3,tags=[typ])
sensor_families=[
    ("imu","9-axis IMU"),("accelerometer","3-axis Accelerometer"),("gyro","3-axis Gyroscope"),("magnetometer","Magnetometer"),
    ("distance","Time-of-Flight Distance"),("ultrasonic","Ultrasonic Distance"),("pressure","Barometric Pressure"),("temperature","Digital Temperature"),
    ("humidity","Humidity"),("current","Current Sensor"),("voltage","Voltage Sensor"),("load","Load Cell Interface"),("angle","Magnetic Angle"),
    ("encoder","Quadrature Encoder"),("hall","Hall Effect"),("light","Ambient Light"),("color","RGB Color"),("gas","Gas / VOC"),
    ("sound","MEMS Microphone"),("pir","PIR Motion")
]
for idx,(typ,label) in enumerate(sensor_families):
    for variant in range(1,3):
        side=12+((idx+variant)%4)*4
        add(f"sensor.generic.{typ}.{variant}","sensor","Generic",f"{label} Module {variant}",dimensions_mm=[side,side,4+variant],mass_g=3+variant,sensor_type=typ,voltage_v=3.3,tags=["sensor",typ,"module"])

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
for dia in [1.6,2,2.5,3,4,5,6,8,10,12]:
    for kind,height_factor in [("hex_nut",.8),("nyloc_nut",1.0),("thin_nut",.5),("flange_nut",1.0)]:
        add(f"nut.{kind}.m{str(dia).replace('.','p')}","nut","ISO",f"M{dia} {kind.replace('_',' ').title()}",dimensions_mm=[dia*2.0,dia*2.0,max(1.2,dia*height_factor)],mass_g=round(dia**3*.008,2),diameter_mm=dia,tags=["nut","metric",kind.replace("_","-")])
    for kind,od_factor,thick in [("flat",2.2,.18),("fender",3.5,.18),("spring",2.0,.28)]:
        add(f"washer.{kind}.m{str(dia).replace('.','p')}","washer","ISO",f"M{dia} {kind.title()} Washer",dimensions_mm=[dia*od_factor,dia*od_factor,max(.3,dia*thick)],mass_g=round(dia**2*.012,2),diameter_mm=dia,tags=["washer","metric",kind])
for dia in [2,2.5,3,4,5,6,8]:
    for length in [4,6,8,10,12,15]:
        add(f"insert.heatset.m{str(dia).replace('.','p')}x{length}","insert","Generic",f"M{dia} Heat-Set Insert {length}mm",dimensions_mm=[dia*1.8,dia*1.8,length],mass_g=round(dia*length*.06,2),diameter_mm=dia,length_mm=length,tags=["heat-set","threaded-insert","3d-printing"])
    for length in [6,8,10,12,15,20,25,30,40,50]:
        add(f"standoff.hex.m{str(dia).replace('.','p')}x{length}","standoff","Generic",f"M{dia} Hex Standoff {length}mm",dimensions_mm=[dia*2,dia*2,length],mass_g=round(dia*length*.08,2),diameter_mm=dia,length_mm=length,tags=["standoff","spacer","metric"])

# Linear motion
for rail in [7,9,12,15,20,25]:
    for length in [100,200,300,500,800,1000]:
        add(f"linear.mgn{rail}.{length}","linear_motion","Generic",f"MGN{rail} rail {length}mm + carriage",dimensions_mm=[length,rail*2.2,rail*1.5],mass_g=round(length*rail*.015),rail_size_mm=rail,travel_mm=length-40,static_load_n=rail*400,tags=["linear-rail"])
for bore,od,length in [(6,12,19),(8,15,24),(10,19,29),(12,21,30),(16,28,37),(20,32,42),(25,40,59),(30,45,64)]:
    for style in ("standard","long","flanged","pillow"):
        scale=1.0 if style=="standard" else 1.8 if style=="long" else 1.25
        add(f"linear_bearing.lm{bore}.{style}","linear_bearing","Generic",f"LM{bore}UU {style.title()} Linear Bearing",dimensions_mm=[od,od,length*scale],mass_g=round(od*length*.12*scale),bore_mm=bore,tags=["linear-bearing",style,f"{bore}mm"])
for diameter,pitch in [(8,2),(8,8),(10,2),(10,8),(12,3),(12,8),(16,4),(16,10)]:
    for length in [100,200,300,400,500,750,1000,1500]:
        add(f"leadscrew.tr{diameter}x{pitch}.{length}","lead_screw","Generic",f"TR{diameter}x{pitch} Lead Screw {length}mm",dimensions_mm=[diameter,diameter,length],mass_g=round(diameter*diameter*length*.0062),diameter_mm=diameter,pitch_mm=pitch,length_mm=length,tags=["lead-screw","trapezoidal",f"{diameter}mm"])

# Shafts, couplers, pulleys, gears, belts and extrusion
for diameter in [2,3,4,5,6,8,10,12,15,16,20,25,30,40]:
    for length in [50,75,100,150,200,300,400,500,750,1000]:
        add(f"shaft.{diameter}x{length}","shaft","Generic",f"{diameter}mm Precision Shaft {length}mm",dimensions_mm=[diameter,diameter,length],mass_g=round(diameter*diameter*length*.0062),diameter_mm=diameter,length_mm=length,tags=["shaft","round","steel",f"{diameter}mm"])
for a,b in [(3,3),(3,5),(4,5),(5,5),(5,6),(5,8),(6,8),(8,8),(8,10),(10,10),(10,12),(12,12)]:
    for style in ("rigid","beam","jaw"):
        od=max(12,max(a,b)*2.8); length=max(18,max(a,b)*3.2)
        add(f"coupler.{style}.{a}x{b}","coupler","Generic",f"{style.title()} Shaft Coupler {a}mm to {b}mm",dimensions_mm=[od,od,length],mass_g=round(od*length*.16),bore_a_mm=a,bore_b_mm=b,tags=["shaft-coupler",style,f"{a}mm",f"{b}mm"])
for pitch in (2,3,5):
    for teeth in (12,16,20,24,30,36,40,48,60,72):
        diameter=teeth*pitch/math.pi
        add(f"pulley.gt{pitch}.{teeth}t","pulley","Generic",f"GT{pitch} Timing Pulley {teeth}T",dimensions_mm=[diameter+4,diameter+4,16],mass_g=round(diameter*1.8),pitch_mm=pitch,teeth=teeth,bore_mm=5 if pitch<=3 else 8,tags=["timing-pulley",f"gt{pitch}",f"{teeth}t"])
    for length in (200,300,400,500,600,750,1000,1200):
        add(f"belt.gt{pitch}.{length}","belt","Generic",f"GT{pitch} Timing Belt {length}mm",dimensions_mm=[length,9,2.5],mass_g=round(length*.018),pitch_mm=pitch,length_mm=length,tags=["timing-belt",f"gt{pitch}"])
for module in (.5,1.0,1.5,2.0):
    key=str(module).replace(".","p")
    for teeth in range(10,61,5):
        od=module*(teeth+2)
        add(f"gear.spur.m{key}.{teeth}t","gear","Generic",f"Module {module:g} Spur Gear {teeth}T",dimensions_mm=[od,od,max(6,module*8)],mass_g=round(od*od*.015),module=module,teeth=teeth,bore_mm=max(3,module*4),tags=["spur-gear",f"module-{module:g}",f"{teeth}t"])
for profile,w,h in [("2020",20,20),("2040",20,40),("2060",20,60),("3030",30,30),("3060",30,60),("4040",40,40),("4080",40,80)]:
    for length in [100,200,300,400,500,600,750,1000,1500,2000]:
        add(f"extrusion.{profile}.{length}","extrusion","Generic",f"{profile} T-Slot Extrusion {length}mm",dimensions_mm=[w,h,length],mass_g=round(w*h*length*.0011),length_mm=length,tags=["t-slot","aluminum-extrusion",profile])

# Springs and magnets
for od in [4,6,8,10,12,15,20,25]:
    for length in [10,15,20,25,30,40,50,60,80,100]:
        add(f"spring.compression.{od}x{length}","spring","Generic",f"Compression Spring {od}x{length}mm",dimensions_mm=[od,od,length],mass_g=round(od*length*.015,2),outer_diameter_mm=od,free_length_mm=length,tags=["spring","compression"])
for dia in [3,5,6,8,10,12,15,20]:
    for thick in [1,2,3,4,5]:
        add(f"magnet.neodymium.{dia}x{thick}","magnet","Generic",f"Neodymium Disc Magnet {dia}x{thick}mm",dimensions_mm=[dia,dia,thick],mass_g=round(dia*dia*thick*.006,2),tags=["magnet","neodymium","disc"])

# Power electronics
for amps in [3,5,10,20,30,40,60]:
    add(f"power.buck.{amps}","power","Generic",f"Buck Converter {amps}A",dimensions_mm=[50+amps*.5,35,15],mass_g=25+amps,max_current_a=amps,input_max_v=36,output_v=5,tags=["dc-dc","buck"])
for output_v in (3.3,5,9,12,24):
    for amps in (1,2,3,5,10,20):
        add(f"power.converter.{str(output_v).replace('.','p')}v.{amps}a","power","Generic",f"DC-DC Converter {output_v:g}V {amps}A",dimensions_mm=[35+amps*2,25+amps,10+min(amps,10)],mass_g=18+amps*3,max_current_a=amps,input_max_v=36,output_v=output_v,tags=["dc-dc","converter",f"{output_v:g}v"])

# Switches, relays, connectors, displays, cameras, pumps and valves
for kind,w,h,d in [("limit",20,10,6),("micro",13,6,6),("toggle",28,13,30),("rocker",30,22,25),("pushbutton",24,24,30)]:
    for variant in range(1,6):
        add(f"switch.{kind}.{variant}","switch","Generic",f"{kind.title()} Switch {variant}",dimensions_mm=[w,h,d],mass_g=5+variant*2,voltage_v=24,tags=["switch",kind,"digital-input"])
for coil in (5,12,24):
    for poles in ("spst","spdt","dpdt"):
        for amps in (5,10,20):
            add(f"relay.{poles}.{coil}v.{amps}a","relay","Generic",f"{poles.upper()} Relay {coil}V Coil {amps}A",dimensions_mm=[28,20,16],mass_g=22,voltage_v=coil,max_current_a=amps,tags=["relay",poles,f"{coil}v"])
for family,pitches in [("jst_ph",[2.0]),("jst_xh",[2.5]),("dupont",[2.54]),("molex_microfit",[3.0]),("terminal_block",[3.5,5.08]),("xt",[2.0])]:
    for pitch in pitches:
        for pins in (2,3,4,5,6,8,10,12):
            w=max(6,pins*pitch+3)
            add(f"connector.{family}.{str(pitch).replace('.','p')}.{pins}p","connector","Generic",f"{family.replace('_',' ').upper()} {pins}-Pin {pitch:g}mm",dimensions_mm=[w,8+pitch,8],mass_g=round(pins*.8,1),pin_count=pins,pitch_mm=pitch,tags=["connector",family.replace("_","-"),f"{pins}-pin"])
for inches,w,h in [(0.96,27,27),(1.3,35,33),(1.54,42,36),(2.0,52,35),(2.4,60,43),(2.8,70,50),(3.5,85,56),(4.0,96,65),(5.0,121,77),(7.0,165,100)]:
    for typ in ("oled","tft"):
        add(f"display.{typ}.{str(inches).replace('.','p')}in","display","Generic",f"{inches:g}\" {typ.upper()} Display Module",dimensions_mm=[w,h,6],mass_g=round(w*h*.012),voltage_v=3.3 if typ=="oled" else 5,tags=["display",typ,f"{inches:g}-inch"])
for variant in range(1,16):
    w=18+(variant%4)*4; h=18+((variant+1)%4)*4
    add(f"camera.module.{variant}","camera","Generic",f"Camera Module {variant}",dimensions_mm=[w,h,10],mass_g=5+variant%5,voltage_v=3.3,tags=["camera","vision","module"])
for voltage in (5,12,24):
    for flow in (100,250,500,1000,2000):
        add(f"pump.dc.{voltage}v.{flow}mlmin","pump","Generic",f"DC Pump {voltage}V {flow}mL/min",dimensions_mm=[45,30,35],mass_g=85,voltage_v=voltage,flow_ml_min=flow,tags=["pump","fluid",f"{voltage}v"])
for voltage in (5,12,24):
    for port in (4,6,8,10,12):
        add(f"valve.solenoid.{voltage}v.{port}mm","valve","Generic",f"Solenoid Valve {voltage}V {port}mm Port",dimensions_mm=[45,30,55],mass_g=140,voltage_v=voltage,port_diameter_mm=port,tags=["valve","solenoid","fluid"])

# Enclosures
for x,y,z in [(60,40,20),(80,50,25),(100,70,30),(120,80,40),(150,100,50),(200,120,60),(250,160,80),(300,200,100)]:
    for material in ("abs","aluminum"):
        add(f"enclosure.{material}.{x}x{y}x{z}","enclosure","Generic",f"{material.upper()} Enclosure {x}x{y}x{z}mm",dimensions_mm=[x,y,z],mass_g=round(x*y*z*(.00055 if material=="abs" else .0012)),material=material,tags=["enclosure",material,"project-box"])


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
        blob=json.dumps(c).lower().replace("_"," ").replace("-"," ")
        if q and not all(tok in blob for tok in q.replace("_"," ").replace("-"," ").split()):continue
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