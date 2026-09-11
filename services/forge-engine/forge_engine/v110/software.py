from __future__ import annotations
import ast, json
from pathlib import Path
from typing import Any


def _obj(project: dict[str,Any], oid: str) -> dict[str,Any]:
    for o in project.get("objects",[]):
        if o.get("id")==oid:return o
    raise KeyError(oid)

def _path(path:str)->str:
    p=Path(path)
    if p.is_absolute() or ".." in p.parts or not path.strip():raise ValueError("Unsafe workspace path")
    return p.as_posix()
def workspace_for_object(project: dict[str,Any], oid: str): return _obj(project,oid).get("code")
def summarize_workspace(ws: dict[str,Any], include_contents: bool=True):
    files=ws.get("files",{}); out={"platform":ws.get("platform"),"entrypoint":ws.get("entrypoint"),"files":[]}
    for p,c in sorted(files.items()):out["files"].append({"path":p,"bytes":len(c.encode()),**({"content":c} if include_contents else {})})
    return out
def read_file(project,oid,path):
    ws=workspace_for_object(project,oid)
    if not ws:raise KeyError("Selected component has no code workspace")
    p=_path(path)
    if p not in ws.get("files",{}):raise KeyError(p)
    return {"path":p,"content":ws["files"][p]}
def validate_workspace(project,oid):
    ws=workspace_for_object(project,oid)
    if not ws:raise KeyError("Selected component has no code workspace")
    results=[];ok=True
    for p,c in ws.get("files",{}).items():
        err=None
        try:
            if p.endswith(".py"):ast.parse(c,filename=p)
            elif p.endswith(".json"):json.loads(c)
        except Exception as e:err=str(e);ok=False
        results.append({"path":p,"ok":err is None,"error":err})
    return {"ok":ok,"files":results}
