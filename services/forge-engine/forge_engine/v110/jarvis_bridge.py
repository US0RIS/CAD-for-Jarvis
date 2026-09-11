from __future__ import annotations
import json, os, secrets, hmac
from pathlib import Path
DATA_DIR=Path(os.environ.get("FORGECAD_DATA_DIR") or (Path.home()/".forgecad"));DATA_DIR.mkdir(parents=True,exist_ok=True)
DISCOVERY=DATA_DIR/"jarvis_bridge.json"

def _token():
    try:
        d=json.loads(DISCOVERY.read_text());t=d.get("token")
        if isinstance(t,str) and len(t)>=32:return t
    except Exception:pass
    return secrets.token_urlsafe(32)
def write_discovery(base_url:str):
    if not base_url.startswith(("http://127.0.0.1:","http://localhost:")):raise ValueError("Jarvis bridge must remain loopback-only")
    d={"base_url":base_url.rstrip("/"),"token":_token(),"build_id":os.environ.get("FORGECAD_BUILD_ID","forgecad-v1"),"ollama_model":os.environ.get("FORGECAD_OLLAMA_MODEL","qwen3:8b")};DISCOVERY.write_text(json.dumps(d,indent=2));return d
def verify_token(value):
    if not value:return False
    try:return hmac.compare_digest(str(value),str(json.loads(DISCOVERY.read_text()).get("token","")))
    except Exception:return False
def clear_discovery():
    try:DISCOVERY.unlink()
    except FileNotFoundError:pass
