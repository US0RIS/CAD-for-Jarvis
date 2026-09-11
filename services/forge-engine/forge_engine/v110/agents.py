from __future__ import annotations
import json, os, re, urllib.request
from typing import Any

DEFAULT_MODEL=os.environ.get("FORGECAD_OLLAMA_MODEL","qwen3:8b")
OPS=["add","add_component","replace_component","sync_component","update","transform","mate_components","connect_interfaces","disconnect","delete","add_feature","delete_feature","add_load","add_constraint","set_requirement","add_bom_item","add_note","code_write","code_delete","code_rename","project_name","settings"]

def _request(path:str,payload:dict[str,Any]|None=None,timeout=90):
    url="http://127.0.0.1:11434"+path; data=None if payload is None else json.dumps(payload).encode(); req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())
def status():
    try:
        d=_request("/api/tags",None,2);models=[x.get("name") or x.get("model") for x in d.get("models",[])];return {"available":True,"models":models,"configured":DEFAULT_MODEL,"configured_present":any(str(x).split(":")[0]==DEFAULT_MODEL.split(":")[0] for x in models)}
    except Exception as e:return {"available":False,"models":[],"configured":DEFAULT_MODEL,"error":str(e)}
def _json_from(text:str):
    text=text.strip();
    try:return json.loads(text)
    except Exception:pass
    m=re.search(r"```(?:json)?\s*(\{.*?\})\s*```",text,re.S)
    if m:
        try:return json.loads(m.group(1))
        except Exception:pass
    a=text.find("{");b=text.rfind("}")
    if a>=0 and b>a:return json.loads(text[a:b+1])
    raise ValueError("Agent did not return valid JSON")
def plan_commands(text:str,model:str|None=None,project:dict[str,Any]|None=None):
    import core
    m=model or DEFAULT_MODEL; p=project or core.PROJECT
    import component_registry
    summary={"name":p.get("name"),"objects":[{"id":o.get("id"),"name":o.get("name"),"kind":o.get("kind"),"params":o.get("params"),"material":o.get("material"),"component_ref":o.get("component_ref"),"interfaces":[i.get("id") for i in o.get("interfaces",[])]} for o in p.get("objects",[])],"requirements":p.get("requirements",[])[:20],"connections":p.get("connections",[])[:30]}
    candidates=[];low=text.lower();category_map={"stepper":"stepper_motor","motor":"stepper_motor","servo":"servo","solenoid":"solenoid","bearing":"bearing","fan":"fan","raspberry pi":"compute","arduino":"microcontroller","microcontroller":"microcontroller","sensor":"sensor","battery":"battery","fastener":"fastener","screw":"fastener","linear rail":"linear_motion","buck":"power"}
    seen=set()
    for token,cat in category_map.items():
        if token in low:
            for c in component_registry.search_components("",cat,limit=8,include_infeasible=True)["results"]:
                if c["id"] not in seen:candidates.append({"id":c["id"],"name":c["name"],"category":c["category"],"specs":c.get("specs",{}),"interfaces":[i.get("id") for i in c.get("interfaces",[])],"geometry_fidelity":c.get("geometry",{}).get("fidelity"),"trust_score":c.get("trust_score")});seen.add(c["id"])
    candidates=candidates[:24]
    system=f"""You are ForgeCAD's local mechanical/electromechanical design planner. Return JSON only: {{\"summary\":\"...\",\"commands\":[{{\"op\":\"...\",\"args\":{{...}}}}],\"checks\":[\"...\"]}}. Allowed operations: {OPS}. Never invent object IDs or component IDs. For commercially purchasable hardware, strongly prefer add_component with an exact component_id from COMPONENT CANDIDATES instead of drawing a generic box. Use mate_components only with exact object IDs and interface IDs supplied in project state. Use connect_interfaces for electrical/logical connections. Preserve vendor geometry and component snapshots; do not edit a purchased component's dimensions as if it were fabricated material. Prefer explicit dimensions in mm for custom parts. If no supplied component candidate is adequate, return no purchase command and say what catalog data is missing. Treat low-trust or low-fidelity data as a verification requirement. Do not claim a screening analysis proves a safety-critical design."""
    summary["component_candidates"]=candidates
    resp=_request("/api/chat",{"model":m,"stream":False,"messages":[{"role":"system","content":system},{"role":"user","content":f"PROJECT:\n{json.dumps(summary)}\n\nREQUEST:\n{text}"}],"options":{"temperature":0.15}},120)
    out=_json_from(resp.get("message",{}).get("content",resp.get("response","")));out.setdefault("commands",[])
    for c in out["commands"]:
        if c.get("op") not in OPS:raise ValueError(f"Agent proposed unsupported operation: {c.get('op')}")
    return out
def review(text:str,model:str|None=None,role:str="verifier"):
    import core
    m=model or DEFAULT_MODEL; system=f"You are ForgeCAD's independent {role}. Review engineering assumptions, loads, constraints, materials, manufacturability and validation gaps. Be concise and distinguish known facts from screening estimates."
    resp=_request("/api/chat",{"model":m,"stream":False,"messages":[{"role":"system","content":system},{"role":"user","content":text+"\n\nProject metrics: "+json.dumps(core.project_metrics())}]},120)
    return {"role":role,"model":m,"text":resp.get("message",{}).get("content",resp.get("response",""))}
def chat(text:str,model:str|None=None):
    import core
    m=model or DEFAULT_MODEL; system="You are ForgeCAD, an engineering copilot. Answer about the current design. When the user requests a change, describe the intended operation and recommend using Apply if execution is desired. Never overstate screening solver fidelity."
    resp=_request("/api/chat",{"model":m,"stream":False,"messages":[{"role":"system","content":system},{"role":"user","content":text+"\n\nCurrent design: "+json.dumps({"name":core.PROJECT.get('name'),"metrics":core.project_metrics(),"objects":[o.get('name') for o in core.PROJECT.get('objects',[])]})}]},120)
    return {"model":m,"text":resp.get("message",{}).get("content",resp.get("response",""))}
