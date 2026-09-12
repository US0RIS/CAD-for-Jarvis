from __future__ import annotations

import asyncio
import html
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .engineering_state import PROJECT
from .models import CreateJobRequest, EngineeringJob, JobState, OllamaState, RuntimeState, RuntimeStatus
from .v110 import jarvis_bridge

API_VERSION = "2"
SESSION_TOKEN = os.environ.get("FORGECAD_SESSION_TOKEN", "")
CONFIGURED_MODEL = os.environ.get("FORGECAD_OLLAMA_MODEL", "qwen3:8b")
OLLAMA_BASE_URL = os.environ.get("FORGECAD_OLLAMA_URL", "http://127.0.0.1:11434")
DEMO_AGENT = os.environ.get("FORGECAD_DEMO_AGENT", "0").strip().lower() in {"1", "true", "yes"}

app = FastAPI(title="Forge Engine", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
_jobs: dict[str, EngineeringJob] = {}
_event_clients: set[WebSocket] = set()


class CodeWriteRequest(BaseModel):
    content: str


class OperationRequest(BaseModel):
    op: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class BranchCreateRequest(BaseModel):
    name: str
    reason: str = ""


class BranchStatusRequest(BaseModel):
    status: str
    note: str = ""
    physical_verified: bool = False


def require_session(
    x_forgecad_session: str | None = Header(default=None),
    x_jarvis_token: str | None = Header(default=None),
) -> None:
    if SESSION_TOKEN and x_forgecad_session == SESSION_TOKEN:
        return
    if x_jarvis_token and jarvis_bridge.verify_token(x_jarvis_token):
        return
    if not SESSION_TOKEN and not x_jarvis_token:
        return
    raise HTTPException(status_code=401, detail="Invalid ForgeCAD/Jarvis session")


def _cache_root() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ForgeCAD" / "cache"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "ForgeCAD"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "forgecad"
    root.mkdir(parents=True, exist_ok=True)
    return root


IMAGE_CACHE = _cache_root() / "component-images"
IMAGE_CACHE.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
async def publish_jarvis_bridge() -> None:
    port = int(os.environ.get("FORGECAD_PORT", "8765"))
    try:
        jarvis_bridge.write_discovery(f"http://127.0.0.1:{port}")
    except Exception:
        pass


@app.on_event("startup")
async def prewarm_scene_cache() -> None:
    # BREP tessellation is the most expensive thing this process does (multiple seconds per
    # part for real component geometry) and PROJECT.scene_manifest() caches by content, so
    # doing this once here means the first real GET /v2/scene from a freshly-loaded viewport
    # is served from a warm cache instead of paying that cost on the user-facing request path.
    # Fire-and-forget: does not block startup or the /v2/health readiness check.
    asyncio.create_task(asyncio.to_thread(PROJECT.scene_manifest))


@app.on_event("shutdown")
async def clear_jarvis_bridge() -> None:
    jarvis_bridge.clear_discovery()


async def ollama_status() -> tuple[OllamaState, str | None]:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            names = [str(model.get("name", "")) for model in response.json().get("models", [])]
    except Exception:
        return OllamaState.OFFLINE, None
    if CONFIGURED_MODEL in names or any(name.split(":", 1)[0] == CONFIGURED_MODEL.split(":", 1)[0] for name in names):
        return OllamaState.READY, CONFIGURED_MODEL
    return OllamaState.FAILED, None


@app.get("/v2/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "api_version": API_VERSION,
        "engine_version": __version__,
        "engineering_layer": "v1.1-full-scope",
        "platform_priority": "windows",
    }


@app.get("/v2/runtime", dependencies=[Depends(require_session)])
async def runtime() -> RuntimeStatus:
    state, resolved = await ollama_status()
    return RuntimeStatus(
        engine=RuntimeState.READY,
        scene=RuntimeState.READY,
        ollama=state,
        configured_model=CONFIGURED_MODEL,
        resolved_model=resolved,
        api_version=API_VERSION,
    )


@app.get("/v2/project", dependencies=[Depends(require_session)])
async def project() -> dict[str, Any]:
    return PROJECT.snapshot()


@app.get("/v2/scene", dependencies=[Depends(require_session)])
async def scene() -> dict[str, Any]:
    return await asyncio.to_thread(PROJECT.scene_manifest)


@app.get("/v2/component-registry/stats", dependencies=[Depends(require_session)])
async def component_registry_stats() -> dict[str, Any]:
    return PROJECT.registry_stats()


@app.get("/v2/components", dependencies=[Depends(require_session)])
async def components(q: str = "", category: str | None = None, voltage_v: float | None = None) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    if voltage_v is not None:
        constraints["voltage_v"] = voltage_v
    items = PROJECT.search_components(q, category=category, constraints=constraints, limit=30)
    return {"items": items, "query": q, "stats": PROJECT.registry_stats()}


def _fallback_svg(component: dict[str, Any]) -> bytes:
    label = html.escape(str(component.get("model", "Component")))
    manufacturer = html.escape(str(component.get("manufacturer", "")))
    category = html.escape(str(component.get("category", "part")).upper())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420">'
        '<rect width="640" height="420" rx="28" fill="#f4f6f7"/>'
        '<rect x="38" y="38" width="564" height="344" rx="22" fill="#e8edef" stroke="#c7d0d4" stroke-width="4"/>'
        f'<text x="320" y="178" text-anchor="middle" font-family="Arial,sans-serif" font-size="27" font-weight="700" fill="#26343b">{label}</text>'
        f'<text x="320" y="218" text-anchor="middle" font-family="Arial,sans-serif" font-size="18" fill="#60717a">{manufacturer}</text>'
        f'<text x="320" y="258" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" fill="#60717a">{category} · ENGINEERING CATALOG</text>'
        '</svg>'
    ).encode("utf-8")


@app.get("/v2/component-images/{component_id}")
async def component_image(component_id: str) -> Response:
    try:
        component = PROJECT.component(component_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Component not found") from exc
    # The registry is intentionally offline-first.  The fallback is generated from the
    # authoritative component identity rather than hotlinking arbitrary supplier media.
    return Response(_fallback_svg(component), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/v2/components/{component_id}/add", dependencies=[Depends(require_session)])
async def add_component(component_id: str) -> dict[str, Any]:
    # core.execute()/persist() do synchronous disk I/O while holding the project lock; on a
    # slow or antivirus-scanned filesystem (observed on Windows CI: a single call here has
    # taken minutes) that would otherwise freeze the whole async event loop - every other
    # in-flight request, not just this one - for as long as the write takes. Running it in a
    # worker thread keeps the event loop free to keep serving concurrent requests meanwhile.
    try:
        component = await asyncio.to_thread(PROJECT.add_component, component_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Component not found") from exc
    snapshot = PROJECT.snapshot()
    await broadcast({"type": "project.updated", "project": snapshot})
    return {"component": component, "project": snapshot}


@app.post("/v2/branches/{branch_name}/activate", dependencies=[Depends(require_session)])
async def activate_branch(branch_name: str) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(PROJECT.activate_branch, branch_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Branch not found") from exc
    await broadcast({"type": "project.updated", "project": snapshot})
    return snapshot


@app.post("/v2/branches", dependencies=[Depends(require_session)])
async def create_branch(request: BranchCreateRequest) -> dict[str, Any]:
    snapshot = await asyncio.to_thread(PROJECT.create_branch, request.name, request.reason)
    await broadcast({"type": "project.updated", "project": snapshot})
    return snapshot


@app.get("/v2/branches/{branch_name}/compare", dependencies=[Depends(require_session)])
async def compare_branch(branch_name: str) -> dict[str, Any]:
    try:
        return PROJECT.compare_branch(branch_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Branch not found") from exc


@app.put("/v2/branches/{branch_name}/status", dependencies=[Depends(require_session)])
async def branch_status(branch_name: str, request: BranchStatusRequest) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(PROJECT.set_branch_status, branch_name, request.status, request.note, request.physical_verified)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Branch not found") from exc
    snapshot = PROJECT.snapshot()
    await broadcast({"type": "project.updated", "project": snapshot})
    return {"branch": result, "project": snapshot}


@app.post("/v2/history/undo", dependencies=[Depends(require_session)])
async def undo() -> dict[str, Any]:
    ok = await asyncio.to_thread(PROJECT.undo)
    snapshot = PROJECT.snapshot()
    await broadcast({"type": "project.updated", "project": snapshot})
    return {"ok": ok, "project": snapshot}


@app.post("/v2/history/redo", dependencies=[Depends(require_session)])
async def redo() -> dict[str, Any]:
    ok = await asyncio.to_thread(PROJECT.redo)
    snapshot = PROJECT.snapshot()
    await broadcast({"type": "project.updated", "project": snapshot})
    return {"ok": ok, "project": snapshot}


@app.get("/v2/code/workspaces/{workspace_id}", dependencies=[Depends(require_session)])
async def workspace(workspace_id: str) -> dict[str, Any]:
    try:
        return PROJECT.workspace(workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc


@app.get("/v2/code/workspaces/{workspace_id}/files/{file_path:path}", dependencies=[Depends(require_session)])
async def read_file(workspace_id: str, file_path: str) -> dict[str, str]:
    try:
        return PROJECT.read_file(workspace_id, file_path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc


@app.put("/v2/code/workspaces/{workspace_id}/files/{file_path:path}", dependencies=[Depends(require_session)])
async def write_file(workspace_id: str, file_path: str, request: CodeWriteRequest) -> dict[str, str]:
    try:
        result = await asyncio.to_thread(PROJECT.write_file, workspace_id, file_path, request.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await broadcast({"type": "project.updated", "project": PROJECT.snapshot()})
    return result


@app.post("/v2/operations", dependencies=[Depends(require_session)])
async def execute_operation(request: OperationRequest) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(PROJECT.execute, request.op, request.args, actor="human", reason=request.reason)
    except (KeyError, ValueError, StopIteration) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await broadcast({"type": "project.updated", "project": result["project"]})
    return result


@app.get("/v2/validation", dependencies=[Depends(require_session)])
async def validation() -> dict[str, Any]:
    return await asyncio.to_thread(PROJECT.validation)


@app.get("/v2/project/export", dependencies=[Depends(require_session)])
async def export_project() -> Response:
    data = await asyncio.to_thread(PROJECT.export_bundle)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="ForgeCAD-Project.forgecad.zip"'})


@app.post("/v2/project/import", dependencies=[Depends(require_session)])
async def import_project(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    try:
        result = await asyncio.to_thread(PROJECT.import_bundle, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await broadcast({"type": "project.updated", "project": result["project"]})
    return result


@app.post("/v2/import/step", dependencies=[Depends(require_session)])
async def import_step(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if not file.filename:
        raise HTTPException(status_code=400, detail="STEP filename is required")
    try:
        result = await asyncio.to_thread(PROJECT.import_step_part, file.filename, data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await broadcast({"type": "project.updated", "project": result["project"]})
    return result


@app.post("/v2/component-registry/import-step", dependencies=[Depends(require_session)])
async def import_vendor_step(
    file: UploadFile = File(...),
    manufacturer: str = Form(...),
    model: str = Form(...),
    category: str = Form("custom"),
) -> dict[str, Any]:
    data = await file.read()
    if not file.filename:
        raise HTTPException(status_code=400, detail="STEP filename is required")
    try:
        return await asyncio.to_thread(PROJECT.import_step_component, file.filename, data, manufacturer=manufacturer, model=model, category=category)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v2/jarvis/context", dependencies=[Depends(require_session)])
async def jarvis_context() -> dict[str, Any]:
    return {
        "project": PROJECT.snapshot(),
        "validation": await asyncio.to_thread(PROJECT.validation),
        "registry": PROJECT.registry_stats(),
        "operation_contract": [
            "add", "add_component", "replace_component", "sync_component", "update", "transform",
            "mate_components", "connect_interfaces", "disconnect", "delete", "add_feature", "delete_feature",
            "add_load", "add_constraint", "set_requirement", "add_bom_item", "add_note",
            "code_write", "code_delete", "code_rename", "project_name", "settings",
        ],
    }


@app.post("/v2/jarvis/execute", dependencies=[Depends(require_session)])
async def jarvis_execute(request: OperationRequest) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(PROJECT.execute, request.op, request.args, actor="jarvis", reason=request.reason or "Jarvis engineering operation")
    except (KeyError, ValueError, StopIteration) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await broadcast({"type": "project.updated", "project": result["project"]})
    return result


async def broadcast(payload: dict[str, Any]) -> None:
    stale: list[WebSocket] = []
    for socket in list(_event_clients):
        try:
            await socket.send_json(payload)
        except Exception:
            stale.append(socket)
    for socket in stale:
        _event_clients.discard(socket)


async def update_job(job: EngineeringJob, *, state: JobState | None = None, progress: float | None = None, message: str | None = None) -> None:
    if state is not None:
        job.state = state
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.message = message
    await broadcast({"type": "job.updated", "job": job.model_dump()})


async def qwen_reply(text: str, job: EngineeringJob) -> str:
    system = (
        "You are ForgeCAD's local engineering copilot. The deterministic Forge Engine is authoritative. "
        "Be concise, distinguish measured/catalog facts from screening estimates, and name verification gaps. "
        "Never claim a screening analysis certifies a safety-critical design."
    )
    payload = {
        "model": CONFIGURED_MODEL,
        "stream": True,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Current project: {json.dumps(PROJECT.snapshot(), separators=(',', ':'))}\n\nRequest: {text}"},
        ],
        "options": {"temperature": 0.12, "num_ctx": 8192, "num_predict": 420},
    }
    answer: list[str] = []
    timeout = httpx.Timeout(180.0, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if job.state == JobState.CANCELLED:
                    break
                if not line:
                    continue
                data = json.loads(line)
                token = str((data.get("message") or {}).get("content") or "")
                if token:
                    answer.append(token)
                    job.assistant_text += token
                    await broadcast({"type": "job.token", "job_id": job.id, "token": token})
    return "".join(answer).strip()


async def qwen_plan(text: str) -> dict[str, Any]:
    context = PROJECT.snapshot()
    candidates = PROJECT.search_components(text, limit=10)
    system = (
        "You are ForgeCAD's local engineering planner. Return JSON only with keys summary, commands, checks. "
        "Each command is {op,args}. Allowed operations: add, add_component, replace_component, sync_component, update, transform, "
        "mate_components, connect_interfaces, disconnect, delete, add_feature, delete_feature, add_load, add_constraint, "
        "set_requirement, add_bom_item, add_note, code_write, code_delete, code_rename, project_name, settings. "
        "Never invent object IDs or component IDs. Purchased components must use exact registry IDs. "
        "Do not scale or rewrite authoritative purchased-component geometry. Keep physically verified baselines protected; the engine will fork them."
    )
    payload = {
        "model": CONFIGURED_MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"project": context, "candidate_components": candidates, "request": text})},
        ],
        "options": {"temperature": 0.08, "num_ctx": 12288, "num_predict": 1400},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=3.0)) as client:
        response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        response.raise_for_status()
    raw = str((response.json().get("message") or {}).get("content") or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Engineering planner did not return valid JSON")
    plan = json.loads(raw[start:end + 1])
    if not isinstance(plan.get("commands", []), list):
        raise ValueError("Engineering planner commands must be a list")
    return plan


async def run_agent_job(job: EngineeringJob, request: CreateJobRequest) -> None:
    try:
        await update_job(job, state=JobState.WARMING, progress=0.08, message=f"Checking {CONFIGURED_MODEL}")
        ollama, _ = await ollama_status()
        if ollama != OllamaState.READY and not DEMO_AGENT:
            raise RuntimeError(f"Configured model {CONFIGURED_MODEL!r} is not available in Ollama")

        await update_job(job, state=JobState.PLANNING, progress=0.24, message="Planning against canonical engineering state")
        result: dict[str, Any]
        if DEMO_AGENT and ollama != OllamaState.READY:
            answer = "Created a safe experimental branch and kept the known-good baseline protected.\n\n- Applied the request through the same typed operation layer used by the UI.\n- Preserved the embedded device workspace with the design branch.\n- Re-run system validation and physical tests before marking this branch as working."
            job.assistant_text = answer
            await broadcast({"type": "job.token", "job_id": job.id, "token": answer})
            result = {"assistant_text": answer}
            if request.apply_edits:
                await update_job(job, state=JobState.APPLYING, progress=0.62, message="Forking protected baseline and applying typed operation")
                result.update(await asyncio.to_thread(PROJECT.apply_demo_change, request.text or "AI engineering change"))
        elif request.apply_edits:
            plan = await qwen_plan(request.text or "Review and improve the design")
            answer = str(plan.get("summary") or "Applied the planned engineering change through Forge Engine typed operations.")
            job.assistant_text = answer
            await broadcast({"type": "job.token", "job_id": job.id, "token": answer})
            await update_job(job, state=JobState.APPLYING, progress=0.62, message="Applying typed engineering operations")
            result = {"assistant_text": answer, "plan": plan}
            result.update(await asyncio.to_thread(PROJECT.apply_agent_plan, plan, request.text or "AI engineering change"))
        else:
            answer = await qwen_reply(request.text or "Review the active design", job)
            result = {"assistant_text": answer}

        if job.state == JobState.CANCELLED:
            return
        await update_job(job, state=JobState.VERIFYING, progress=0.88, message="Running deterministic reality checks")
        result["validation"] = await asyncio.to_thread(PROJECT.validation)
        result["project"] = PROJECT.snapshot()
        job.branch = PROJECT.active_branch
        job.result = result
        await broadcast({"type": "project.updated", "project": result["project"]})
        await update_job(job, state=JobState.COMPLETED, progress=1.0, message="Complete")
    except Exception as exc:
        job.error = {"code": "agent_failed", "message": str(exc), "recoverable": True}
        await update_job(job, state=JobState.FAILED, progress=1.0, message=str(exc))


async def run_engineering_job(job: EngineeringJob, request: CreateJobRequest) -> None:
    try:
        await update_job(job, state=JobState.ANALYZING, progress=0.18, message=f"Running {job.kind}")
        if job.kind == "simulation":
            result = await asyncio.to_thread(PROJECT.run_simulation, request.selected_object_id, request.payload)
        elif job.kind == "campaign":
            result = await asyncio.to_thread(PROJECT.run_campaign, request.selected_object_id, request.payload)
        elif job.kind == "component-search":
            result = {"items": PROJECT.search_components(request.text or "", constraints=request.payload.get("constraints") if request.payload else None)}
        elif job.kind == "deploy":
            workspace_id = str((request.payload or {}).get("workspace_id") or request.selected_object_id or "")
            if not workspace_id:
                raise ValueError("deploy requires a programmable component/workspace")
            result = await asyncio.to_thread(PROJECT.deploy_workspace, workspace_id)
        else:
            raise ValueError(f"Unsupported engineering job: {job.kind}")
        await update_job(job, state=JobState.VERIFYING, progress=0.85, message="Verifying result against current design")
        job.result = result
        if job.kind in {"campaign", "simulation"}:
            await broadcast({"type": "project.updated", "project": PROJECT.snapshot()})
        await update_job(job, state=JobState.COMPLETED, progress=1.0, message="Complete")
    except Exception as exc:
        job.error = {"code": "job_failed", "message": str(exc), "recoverable": True}
        await update_job(job, state=JobState.FAILED, progress=1.0, message=str(exc))


@app.post("/v2/jobs", dependencies=[Depends(require_session)])
async def create_job(request: CreateJobRequest) -> EngineeringJob:
    job = EngineeringJob(
        kind=request.kind,
        branch=request.branch or PROJECT.active_branch,
        selected_object_id=request.selected_object_id,
        message="Queued",
    )
    _jobs[job.id] = job
    await broadcast({"type": "job.updated", "job": job.model_dump()})
    if request.kind == "agent":
        asyncio.create_task(run_agent_job(job, request))
    else:
        asyncio.create_task(run_engineering_job(job, request))
    return job


@app.get("/v2/jobs/{job_id}", dependencies=[Depends(require_session)])
async def get_job(job_id: str) -> EngineeringJob:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/v2/jobs/{job_id}/cancel", dependencies=[Depends(require_session)])
async def cancel_job(job_id: str) -> EngineeringJob:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.state not in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
        job.state = JobState.CANCELLED
        job.message = "Cancelled"
        await broadcast({"type": "job.updated", "job": job.model_dump()})
    return job


@app.websocket("/v2/events")
async def events(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    if SESSION_TOKEN and token != SESSION_TOKEN:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    _event_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _event_clients.discard(websocket)
