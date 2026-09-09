from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect

from . import __version__
from .models import CreateJobRequest, EngineeringJob, JobState, OllamaState, RuntimeState, RuntimeStatus

API_VERSION = "2"
SESSION_TOKEN = os.environ.get("FORGECAD_SESSION_TOKEN", "")
CONFIGURED_MODEL = os.environ.get("FORGECAD_OLLAMA_MODEL", "qwen3:8b")
OLLAMA_BASE_URL = os.environ.get("FORGECAD_OLLAMA_URL", "http://127.0.0.1:11434")

app = FastAPI(title="Forge Engine", version=__version__)
_jobs: dict[str, EngineeringJob] = {}
_event_clients: set[WebSocket] = set()


def require_session(x_forgecad_session: str | None = Header(default=None)) -> None:
    if not SESSION_TOKEN:
        return
    if x_forgecad_session != SESSION_TOKEN:
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
async def health() -> dict:
    return {"ok": True, "api_version": API_VERSION, "engine_version": __version__}


@app.get("/v2/runtime", dependencies=[Depends(require_session)])
async def runtime() -> RuntimeStatus:
    state, resolved = await ollama_status()
    return RuntimeStatus(
        engine=RuntimeState.READY,
        scene=RuntimeState.STARTING,
        ollama=state,
        configured_model=CONFIGURED_MODEL,
        resolved_model=resolved,
        api_version=API_VERSION,
    )


async def broadcast(payload: dict) -> None:
    stale: list[WebSocket] = []
    for socket in _event_clients:
        try:
            await socket.send_json(payload)
        except Exception:
            stale.append(socket)
    for socket in stale:
        _event_clients.discard(socket)


@app.post("/v2/jobs", dependencies=[Depends(require_session)])
async def create_job(request: CreateJobRequest) -> EngineeringJob:
    job = EngineeringJob(
        kind=request.kind,
        branch=request.branch,
        selected_object_id=request.selected_object_id,
        message="Queued",
    )
    _jobs[job.id] = job
    await broadcast({"type": "job.updated", "job": job.model_dump()})
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
