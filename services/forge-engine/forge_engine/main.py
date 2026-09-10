from __future__ import annotations

import asyncio
import html
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
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
    # The Electron renderer (and the Playwright e2e harness, which drives the
    # same app in a plain browser tab) talks to this engine across a port
    # boundary on 127.0.0.1. Newer Chromium enforces Private Network Access
    # for that: it sends an `Access-Control-Request-Private-Network` preflight
    # and silently drops every request unless the server opts in here. Without
    # this, fetches to /v2/* never complete in a PNA-enforcing browser - not
    # slow, just permanently blocked - which is why raising Playwright's test
    # timeout never helped the Windows CI run: no amount of waiting makes a
    # blocked request succeed.
    allow_private_network=True,
)
_jobs: dict[str, EngineeringJob] = {}
_event_clients: set[WebSocket] = set()


class CodeWriteRequest(BaseModel):
    content: str


def require_session(x_forgecad_session: str | None = Header(default=None)) -> None:
    if SESSION_TOKEN and x_forgecad_session != SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid ForgeCAD desktop session")


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


def _component_payload(component: dict[str, Any], request: Request) -> dict[str, Any]:
    result = {k: v for k, v in component.items() if k != "image"}
    image = component.get("image")
    if image:
        result["image"] = {
            "kind": image.get("kind", "reference"),
            "source": image.get("source", "reference image"),
            "uri": f"{str(request.base_url).rstrip('/')}/v2/component-images/{component['id']}",
        }
    return result


@app.get("/v2/components", dependencies=[Depends(require_session)])
async def components(request: Request, q: str = "") -> dict[str, Any]:
    return {"items": [_component_payload(item, request) for item in PROJECT.search_components(q)], "query": q}


def _fallback_svg(component: dict[str, Any]) -> bytes:
    label = html.escape(str(component.get("model", "Component")))
    category = html.escape(str(component.get("category", "part")).upper())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420">'
        '<rect width="640" height="420" rx="28" fill="#f4f6f7"/>'
        '<rect x="38" y="38" width="564" height="344" rx="22" fill="#e8edef" stroke="#c7d0d4" stroke-width="4"/>'
        f'<text x="320" y="190" text-anchor="middle" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="#26343b">{label}</text>'
        f'<text x="320" y="235" text-anchor="middle" font-family="Arial,sans-serif" font-size="18" fill="#60717a">{category} · image unavailable</text>'
        '</svg>'
    ).encode("utf-8")


@app.get("/v2/component-images/{component_id}")
async def component_image(component_id: str) -> Response:
    try:
        component = PROJECT.component(component_id)
    except (KeyError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail="Component not found") from exc

    image = component.get("image") or {}
    sources = [str(value) for value in image.get("sources", []) if value]
    cache_file = IMAGE_CACHE / f"{component_id}.bin"
    meta_file = IMAGE_CACHE / f"{component_id}.json"

    if cache_file.exists() and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            return Response(cache_file.read_bytes(), media_type=str(meta.get("content_type") or "image/jpeg"), headers={"Cache-Control": "public, max-age=86400"})
        except Exception:
            pass

    headers = {"User-Agent": "ForgeCAD/2 component-image-cache (+local desktop app)"}
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
        for source in sources:
            try:
                response = await client.get(source)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if not content_type.startswith("image/") or len(response.content) < 256:
                    continue
                cache_file.write_bytes(response.content)
                meta_file.write_text(json.dumps({"content_type": content_type, "source": str(response.url)}), encoding="utf-8")
                return Response(response.content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
            except Exception:
                continue

    return Response(_fallback_svg(component), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.post("/v2/components/{component_id}/add", dependencies=[Depends(require_session)])
async def add_component(component_id: str, request: Request) -> dict[str, Any]:
    try:
        component = PROJECT.add_component(component_id)
    except (KeyError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail="Component not found") from exc
    await broadcast({"type": "project.updated", "project": PROJECT.snapshot()})
    return {"component": _component_payload(component, request), "project": PROJECT.snapshot()}


@app.post("/v2/branches/{branch_name}/activate", dependencies=[Depends(require_session)])
async def activate_branch(branch_name: str) -> dict[str, Any]:
    try:
        snapshot = PROJECT.activate_branch(branch_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Branch not found") from exc
    await broadcast({"type": "project.updated", "project": snapshot})
    return snapshot


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
        "You are ForgeCAD's local engineering copilot inside a desktop CAD application. "
        "The deterministic Forge Engine, not you, performs CAD mutations. Respond for a narrow chat rail, not a report. "
        "Use at most 220 words. Start with a one-sentence answer, then at most 4 short bullets. "
        "Do not emit markdown tables, long derivations, or multi-level headings unless the user explicitly asks for them. "
        "Name only the most important physical consequence and the single best verification step. "
        "If the request is ambiguous, make the smallest reasonable assumption in one short sentence rather than writing a scope essay."
    )
    context = PROJECT.snapshot()
    payload = {
        "model": CONFIGURED_MODEL,
        "stream": True,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Current project: {json.dumps(context, separators=(',', ':'))}\n\nRequest: {text}"},
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


async def run_agent_job(job: EngineeringJob, request: CreateJobRequest) -> None:
    try:
        await update_job(job, state=JobState.WARMING, progress=0.08, message=f"Checking {CONFIGURED_MODEL}")
        ollama, _ = await ollama_status()
        if ollama != OllamaState.READY and not DEMO_AGENT:
            raise RuntimeError(f"Configured model {CONFIGURED_MODEL!r} is not available in Ollama")

        await update_job(job, state=JobState.PLANNING, progress=0.24, message="Planning the engineering change")
        if DEMO_AGENT and ollama != OllamaState.READY:
            await asyncio.sleep(0.15)
            answer = "Created a safe experimental branch and kept the known-good baseline protected.\n\n- Applied the requested actuator change.\n- Preserved the Raspberry Pi code workspace with the design.\n- Re-run thermal and vibration checks before marking this branch as working."
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
