from __future__ import annotations
import itertools, math, os, platform, shutil
from copy import deepcopy
from typing import Any
from . import core


def _axis_dims(obj:dict[str,Any],axis:str):
    m=core.object_metrics(obj);b=m["bounds_mm"];axis=axis.lower()
    if axis=="y":return b["y"],b["x"],b["z"]
    if axis=="z":return b["z"],b["x"],b["y"]
    return b["x"],b["y"],b["z"]
def _mat(obj):return core.MATERIALS.get(obj.get("material"),core.MATERIALS["aluminum_6061_t6"])

def quick_cantilever(obj:dict[str,Any],force_n:float=100,length_mm:float|None=None,axis:str="x"):
    L,w,h=_axis_dims(obj,axis);L=float(length_mm or L);F=float(force_n);mat=_mat(obj);E=float(mat["youngs_modulus_gpa"])*1000
    I=max(w*h**3/12,1e-9);delta=F*L**3/(3*E*I);sigma=F*L*(h/2)/I;fos=float(mat["yield_mpa"])/max(sigma,1e-12)
    return {"method":"Euler-Bernoulli cantilever screening","force_n":F,"length_mm":L,"max_deflection_mm":delta,"max_bending_stress_mpa":sigma,"yield_fos":fos,"youngs_modulus_mpa":E,"limitations":["Equivalent rectangular section from bounding box","No stress concentrations, contact, preload, geometric nonlinearity, or fatigue","Screening result; validate critical designs with a mature solver and physical tests"]}

def linear_fea(obj,force_n=100,support_axis="x",load_direction="z",resolution=10):
    base=quick_cantilever(obj,force_n,None,support_axis);n=max(4,min(int(resolution),40));L=base["length_mm"]
    xs=[L*i/n for i in range(n+1)];dmax=base["max_deflection_mm"]
    profile=[]
    for x in xs:
        xi=x/L if L else 0; profile.append({"x_mm":x,"displacement_mm":dmax*(xi*xi*(3-2*xi)),"stress_mpa":base["max_bending_stress_mpa"]*(1-xi)})
    return {**base,"method":"reduced-order structural preview","support_axis":support_axis,"load_direction":load_direction,"resolution":n,"profile":profile,"max_displacement_mm":dmax,"solver_grade":"screening"}

def modal_analysis(obj,support_axis="x",resolution=8,modes=6):
    L,w,h=_axis_dims(obj,support_axis);mat=_mat(obj);E=float(mat["youngs_modulus_gpa"])*1e9;rho=float(mat["density_kg_m3"]);Lm=max(L/1000,1e-6);wm=w/1000;hm=h/1000;A=max(wm*hm,1e-12);I=max(wm*hm**3/12,1e-18)
    betas=[1.875104,4.694091,7.854757,10.995541,14.137168,17.27876]; out=[]
    for i,b in enumerate(betas[:max(1,min(int(modes),6))],1):
        hz=(b*b/(2*math.pi*Lm*Lm))*math.sqrt(E*I/(rho*A));out.append({"mode":i,"frequency_hz":hz,"shape":"cantilever bending approximation"})
    return {"method":"Euler-Bernoulli modal screening","modes":out,"support_axis":support_axis,"limitations":["Uniform equivalent beam","Does not capture joint/contact stiffness or local modes"]}

def thermal_analysis(obj,heat_w=10,ambient_c=22,h_w_m2k=8,resolution=14,fixed_axis=None,fixed_temp_c=None):
    m=core.object_metrics(obj);mat=_mat(obj);area=max(m["area_mm2"]*1e-6,1e-9);h=max(float(h_w_m2k),.01);q=float(heat_w);amb=float(ambient_c);conv_r=1/(h*area); rise=q*conv_r
    if fixed_temp_c is not None:
        # parallel sink approximation to a fixed-temperature interface
        bb=m["bounds_mm"];length=max(min(bb.values())/1000,1e-5);contact_area=max((m["volume_mm3"]/(max(bb.values()) or 1))*1e-6,1e-8);cond_r=length/(max(float(mat["thermal_w_mk"]),1e-6)*contact_area);sink=float(fixed_temp_c);t=(amb/conv_r+sink/cond_r+q)/(1/conv_r+1/cond_r);rise=t-amb
    else:t=amb+rise
    return {"method":"lumped thermal resistance screening","heat_w":q,"ambient_c":amb,"surface_area_m2":area,"convection_h_w_m2k":h,"estimated_max_temperature_c":t,"max_temperature_c":t,"temperature_rise_c":rise,"limitations":["Lumped steady-state model","No radiation, detailed conduction path, airflow field, or interface resistance unless explicitly represented"]}

def manufacturing_review(obj,process="fdm"):
    m=core.object_metrics(obj);b=m["bounds_mm"];issues=[];process=process.lower()
    min_dim=min(b.values())
    if process in {"fdm","fff"}:
        if min_dim<1.2:issues.append({"severity":"warning","message":"A bounding dimension is under 1.2 mm; verify nozzle/wall strategy."})
        issues.append({"severity":"info","message":"Automatic preview cannot infer every overhang from semantic feature intent; inspect support strategy."})
    elif process in {"cnc","mill","machining"}:
        for f in obj.get("features",[]):
            if f.get("type") in {"pocket_rect","rectangular_pocket"} and float(f.get("depth",0))>4*min(float(f.get("width",1)),float(f.get("height",1))):issues.append({"severity":"warning","message":"Deep narrow pocket may require a high-aspect-ratio tool."})
    elif process in {"sla","sls"}:issues.append({"severity":"info","message":"Check trapped powder/resin volumes and post-processing access."})
    return {"process":process,"object_id":obj["id"],"issues":issues,"ok":not any(x["severity"]=="error" for x in issues),"bounds_mm":b}

def optimize_part(obj,variables,objective="mass",force_n=100,axis="x",deflection_max_mm=None,yield_fos_min=None,max_evals=90):
    # deterministic bounded grid / Latin-like sweep, intentionally transparent rather than opaque optimizer magic
    vars_=variables[:5]; levels=max(2,min(7,int(round(max_evals**(1/max(len(vars_),1))))))
    grids=[]
    for v in vars_:
        lo=float(v.get("min"));hi=float(v.get("max"));grids.append([lo+(hi-lo)*i/(levels-1) for i in range(levels)])
    best=None;tested=[]
    for combo in itertools.product(*grids):
        if len(tested)>=max_evals:break
        cand=deepcopy(obj)
        for v,val in zip(vars_,combo):cand.setdefault("params",{})[str(v["name"])]=val
        try:m=core.object_metrics(cand);a=quick_cantilever(cand,force_n,None,axis)
        except Exception:continue
        feasible=(deflection_max_mm is None or a["max_deflection_mm"]<=deflection_max_mm) and (yield_fos_min is None or a["yield_fos"]>=yield_fos_min)
        score=m["mass_kg"] if objective=="mass" else a.get(objective,m["mass_kg"]);row={"values":dict(zip([str(v["name"]) for v in vars_],combo)),"mass_kg":m["mass_kg"],"max_deflection_mm":a["max_deflection_mm"],"yield_fos":a["yield_fos"],"feasible":feasible,"score":score};tested.append(row)
        if feasible and (best is None or score<best["score"]):best=row
    if best is None:best=min(tested,key=lambda x:x["score"]) if tested else {"values":{},"score":float("inf"),"mass_kg":float("inf"),"feasible":False}
    return {"best":best,"evaluations":len(tested),"candidates":tested[:100],"objective":objective}

def fatigue_life(alternating_stress_mpa,sn_curve,mean_stress_mpa=0,ultimate_strength_mpa=None,surface_factor=1,reliability_factor=1):
    sa=float(alternating_stress_mpa)/(max(float(surface_factor)*float(reliability_factor),1e-9));
    if ultimate_strength_mpa and mean_stress_mpa:sa=sa/max(1-float(mean_stress_mpa)/float(ultimate_strength_mpa),.05)
    pts=sorted((float(x["stress_mpa"]),float(x["cycles"])) for x in sn_curve)
    life=None
    for (s1,n1),(s2,n2) in zip(pts,pts[1:]):
        if min(s1,s2)<=sa<=max(s1,s2):
            t=(math.log(sa)-math.log(s1))/(math.log(s2)-math.log(s1));life=math.exp(math.log(n1)+t*(math.log(n2)-math.log(n1)));break
    if life is None:life=pts[0][1] if sa>=pts[0][0] else pts[-1][1]
    return {"corrected_alternating_stress_mpa":sa,"estimated_cycles":life,"method":"log-log S-N interpolation with optional Goodman correction","screening":True}
def bolted_joint_screen(preload_n,external_separating_load_n,bolt_stiffness_n_mm,joint_stiffness_n_mm,friction_coefficient=None,shear_load_n=0):
    kb=float(bolt_stiffness_n_mm);kj=float(joint_stiffness_n_mm);C=kb/max(kb+kj,1e-9);p=float(preload_n);F=float(external_separating_load_n);bolt=p+C*F;clamp=p-(1-C)*F;slip=None
    if friction_coefficient is not None:slip=float(friction_coefficient)*max(clamp,0)-float(shear_load_n)
    return {"joint_constant":C,"bolt_load_n":bolt,"remaining_clamp_n":clamp,"separation_predicted":clamp<=0,"slip_margin_n":slip,"screening":True}
def system_capabilities():
    exes={x:shutil.which(x) for x in ["gmsh","ccx","openfoam","FreeCADCmd","code_aster"]}
    return {"platform":platform.platform(),"machine":platform.machine(),"cpu_threads":os.cpu_count(),"built_in":["exact CadQuery B-rep","reduced-order structural preview","modal screening","thermal screening","parameter optimization","manufacturing screening"],"external":exes,"trust":"Built-in analyses are design-iteration screening tools, not certification solvers."}
