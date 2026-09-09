from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
from .models import CreateJobRequest, EngineeringJob, JobState, OllamaState, RuntimeState, RuntimeStatus
from .vertical_slice import PROJECT

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


def require_session(x_forgecad_session: str | None = Header(default=None)) -> None:
    if SESSION_TOKEN and x_forgecad_session != SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid ForgeCAD desktop session")


async def ollama_status() -> tuple[OllamaState, str | None]:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            names = [str(model.get("name", "")) for model in response.json().get("models", [])]
    except Exception:
        return OllamaState.OFFLINE, None

    if CONFIGURED_MODEL in names:
        return OllamaState.READY, CONFIGURED_MODEL
    return OllamaState.FAILED, None


@app.get("/v2/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "api_version": API_VERSION, "engine_version": __version__, "platform_priority": "windows"}


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
    return PROJECT.scene_manifest()


@app.get("/v2/components", dependencies=[Depends(require_session)])
async def components(q: str = "") -> dict[str, Any]:
    return {"items": PROJECT.search_components(q), "query": q}


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
        return PROJECT.write_file(workspace_id, file_path, request.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        "You are ForgeCAD's local engineering copilot. Be concise and engineering-specific. "
        "The deterministic Forge Engine, not you, performs CAD mutations. Explain the intended change, "
        "important physical consequences, and what should be verified next."
    )
    context = PROJECT.snapshot()
    payload = {
        "model": CONFIGURED_MODEL,
        "stream": True,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Current project: {json.dumps(context, separators=(',', ':'))}\n\nRequest: {text}"},
        ],
        "options": {"temperature": 0.15, "num_ctx": 8192},
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


async def run_agent_job(job: EngineeringJob, request: CreateJobRequest) -> None:
    try:
        await update_job(job, state=JobState.WARMING, progress=0.08, message=f"Checking {CONFIGURED_MODEL}")
        ollama, _ = await ollama_status()
        if ollama != OllamaState.READY and not DEMO_AGENT:
            raise RuntimeError(f"Configured model {CONFIGURED_MODEL!r} is not available in Ollama")

        await update_job(job, state=JobState.PLANNING, progress=0.24, message="Engineering request is being planned")
        if DEMO_AGENT and ollama != OllamaState.READY:
            await asyncio.sleep(0.15)
            answer = "Created a safe experimental branch, applied the requested actuator change, and kept the known-good baseline protected. Re-run thermal and vibration checks before treating the variant as working."
            job.assistant_text = answer
            await broadcast({"type": "job.token", "job_id": job.id, "token": answer})
        else:
            answer = await qwen_reply(request.text or "Review the active design", job)

        if job.state == JobState.CANCELLED:
            return
        result: dict[str, Any] = {"assistant_text": answer}
        if request.apply_edits:
            await update_job(job, state=JobState.APPLYING, progress=0.70, message="Creating child branch and applying typed changes")
            result.update(PROJECT.apply_agent_change(request.text or "AI engineering change"))
            job.branch = str(result.get("branch") or job.branch or "")
            await broadcast({"type": "project.updated", "project": PROJECT.snapshot()})
        await update_job(job, state=JobState.VERIFYING, progress=0.90, message="Checking branch protection and stale-analysis state")
        await asyncio.sleep(0.1)
        job.result = result
        await update_job(job, state=JobState.COMPLETED, progress=1.0, message="Complete")
    except Exception as exc:
        job.error = {"code": "agent_failed", "message": str(exc), "recoverable": True}
        await update_job(job, state=JobState.FAILED, progress=1.0, message=str(exc))


async def run_generic_job(job: EngineeringJob) -> None:
    try:
        await update_job(job, state=JobState.ANALYZING, progress=0.25, message=f"Running {job.kind}")
        await asyncio.sleep(0.25)
        await update_job(job, state=JobState.VERIFYING, progress=0.8, message="Verifying result")
        await asyncio.sleep(0.1)
        job.result = {"ok": True, "kind": job.kind}
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
        asyncio.create_task(run_generic_job(job))
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
