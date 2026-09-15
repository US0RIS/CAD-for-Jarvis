from __future__ import annotations

"""ForgeCAD 6.0.1 runtime hardening.

6.0.0 remains frozen. This layer tightens the mutable desktop runtime without changing
legacy route names:
- every job is pinned to the exact active branch + project revision it was queued from;
- stale agent plans fail before they can mutate canonical state;
- stateful engineering jobs hold the canonical project lock for their complete
  read/solve/record transaction;
- non-interruptible worker phases cannot be reported as cancelled while they continue;
- design-status labels cannot grant or erase physical-verification evidence;
- branch activation waits for canonical work in a worker thread instead of blocking the
  asyncio event loop while the project lock is held.
"""

import asyncio
from copy import deepcopy
from typing import Any, Callable

from fastapi import HTTPException

from .models import CreateJobRequest, EngineeringJob, JobState, OllamaState
from .v110 import core


TERMINAL = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


def _snapshot_locked(legacy: Any) -> dict[str, Any]:
    with core.LOCK:
        return deepcopy(legacy.PROJECT.snapshot())


def assert_job_source(legacy: Any, job: EngineeringJob) -> dict[str, Any]:
    """Fail closed if a queued job no longer describes the canonical active revision."""
    snapshot = _snapshot_locked(legacy)
    if snapshot.get("active_branch") != job.branch:
        raise RuntimeError(
            f"Job is stale: it was queued on branch {job.branch!r}, but the active branch is "
            f"{snapshot.get('active_branch')!r}. Re-run the job on the active design."
        )
    if snapshot.get("revision") != job.revision:
        raise RuntimeError(
            "Job is stale: the source design changed after this job was queued. "
            "Re-run it against the current revision before applying or recording results."
        )
    return snapshot


def set_design_label_preserving_evidence(name: str, status: str, note: str = "") -> dict[str, Any]:
    """Change a human design label without changing evidence-owned physical verification."""
    with core.LOCK:
        if name not in core.DESIGNS:
            raise KeyError(name)
        physical_verified = bool(core.DESIGNS[name].get("physical_verified"))
        return core.set_design_status(name, status, note, physical_verified)


def _final_project_matches(legacy: Any, project: dict[str, Any]) -> bool:
    current = _snapshot_locked(legacy)
    return (
        current.get("active_branch") == project.get("active_branch")
        and current.get("revision") == project.get("revision")
    )


def _apply_agent_transaction(
    legacy: Any,
    job: EngineeringJob,
    apply: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    with core.LOCK:
        # Check again under the same lock that protects the entire apply + validation
        # transaction. No branch switch or human mutation can interleave here.
        source = legacy.PROJECT.snapshot()
        if source.get("active_branch") != job.branch or source.get("revision") != job.revision:
            raise RuntimeError(
                "Job is stale: the source branch/revision changed before the planned edit could be applied."
            )
        result = dict(apply())
        result["validation"] = legacy.PROJECT.validation()
        result["project"] = legacy.PROJECT.snapshot()
        result["source_branch"] = job.branch
        result["source_revision"] = job.revision
        result["result_branch"] = result["project"].get("active_branch")
        result["result_revision"] = result["project"].get("revision")
        return result


def _validate_read_only_agent(legacy: Any, job: EngineeringJob, result: dict[str, Any]) -> dict[str, Any]:
    with core.LOCK:
        source = legacy.PROJECT.snapshot()
        if source.get("active_branch") != job.branch or source.get("revision") != job.revision:
            raise RuntimeError(
                "Job is stale: the design changed while the Copilot response was being generated. Re-run the request."
            )
        result["validation"] = legacy.PROJECT.validation()
        result["project"] = source
        result["source_branch"] = job.branch
        result["source_revision"] = job.revision
        result["result_branch"] = job.branch
        result["result_revision"] = job.revision
        return result


def _run_engineering_transaction(legacy: Any, job: EngineeringJob, request: CreateJobRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    with core.LOCK:
        source = legacy.PROJECT.snapshot()
        if source.get("active_branch") != job.branch or source.get("revision") != job.revision:
            raise RuntimeError(
                "Job is stale: the source branch/revision changed before engineering analysis began. Re-run the job."
            )
        if job.kind == "simulation":
            result = legacy.PROJECT.run_simulation(request.selected_object_id, request.payload)
        elif job.kind == "campaign":
            result = legacy.PROJECT.run_campaign(request.selected_object_id, request.payload)
        elif job.kind == "component-search":
            result = {
                "items": legacy.PROJECT.search_components(
                    request.text or "",
                    constraints=request.payload.get("constraints") if request.payload else None,
                )
            }
        elif job.kind == "deploy":
            workspace_id = str((request.payload or {}).get("workspace_id") or request.selected_object_id or "")
            if not workspace_id:
                raise ValueError("deploy requires a programmable component/workspace")
            result = legacy.PROJECT.deploy_workspace(workspace_id)
        else:
            raise ValueError(f"Unsupported engineering job: {job.kind}")

        project = legacy.PROJECT.snapshot()
        result = dict(result)
        result["source_branch"] = job.branch
        result["source_revision"] = job.revision
        result["result_branch"] = project.get("active_branch")
        result["result_revision"] = project.get("revision")
        return result, project


def _replace_route(app: Any, path: str, method: str, endpoint: Callable[..., Any]) -> None:
    method = method.upper()
    for route in app.router.routes:
        if getattr(route, "path", None) != path or method not in (getattr(route, "methods", None) or set()):
            continue
        route.endpoint = endpoint
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependant.call = endpoint
        return
    raise RuntimeError(f"ForgeCAD 6.0.1 could not locate route {method} {path}")


def install(app: Any, legacy: Any) -> None:
    if getattr(app.state, "forgecad_v601_runtime_installed", False):
        return

    async def create_job(request: CreateJobRequest) -> EngineeringJob:
        source = _snapshot_locked(legacy)
        requested_branch = request.branch or str(source.get("active_branch") or "")
        if requested_branch != source.get("active_branch"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Job requested branch {requested_branch!r}, but Forge Engine is currently on "
                    f"{source.get('active_branch')!r}. Activate the branch first so the job has one canonical state."
                ),
            )
        job = EngineeringJob(
            kind=request.kind,
            branch=requested_branch,
            revision=str(source.get("revision") or ""),
            cancellable=True,
            selected_object_id=request.selected_object_id,
            message="Queued",
        )
        legacy._jobs[job.id] = job
        await legacy.broadcast({"type": "job.updated", "job": job.model_dump()})
        if request.kind == "agent":
            asyncio.create_task(run_agent_job(job, request))
        else:
            asyncio.create_task(run_engineering_job(job, request))
        return job

    async def run_agent_job(job: EngineeringJob, request: CreateJobRequest) -> None:
        try:
            job.cancellable = True
            await legacy.update_job(job, state=JobState.WARMING, progress=0.08, message=f"Checking {legacy.CONFIGURED_MODEL}")
            ollama, _ = await legacy.ollama_status()
            if job.state == JobState.CANCELLED:
                return
            if ollama != OllamaState.READY and not legacy.DEMO_AGENT:
                raise RuntimeError(f"Configured model {legacy.CONFIGURED_MODEL!r} is not available in Ollama")

            # This check happens immediately before the model/planner captures its own
            # project context. Any edit during model latency is checked again before apply.
            assert_job_source(legacy, job)
            await legacy.update_job(job, state=JobState.PLANNING, progress=0.24, message="Planning against pinned canonical engineering state")
            result: dict[str, Any]

            if legacy.DEMO_AGENT and ollama != OllamaState.READY:
                answer = (
                    "Created a safe experimental branch and kept the known-good baseline protected.\n\n"
                    "- Applied the request through the same typed operation layer used by the UI.\n"
                    "- Preserved the embedded device workspace with the design branch.\n"
                    "- Re-run system validation and physical tests before marking this branch as working."
                )
                job.assistant_text = answer
                await legacy.broadcast({"type": "job.token", "job_id": job.id, "token": answer})
                result = {"assistant_text": answer}
                if request.apply_edits:
                    if job.state == JobState.CANCELLED:
                        return
                    assert_job_source(legacy, job)
                    job.cancellable = False
                    await legacy.update_job(job, state=JobState.APPLYING, progress=0.62, message="Applying typed engineering operation")
                    result.update(
                        await asyncio.to_thread(
                            _apply_agent_transaction,
                            legacy,
                            job,
                            lambda: legacy.PROJECT.apply_demo_change(request.text or "AI engineering change"),
                        )
                    )
                else:
                    result = await asyncio.to_thread(_validate_read_only_agent, legacy, job, result)
            elif request.apply_edits:
                plan = await legacy.qwen_plan(request.text or "Review and improve the design")
                if job.state == JobState.CANCELLED:
                    return
                assert_job_source(legacy, job)
                answer = str(plan.get("summary") or "Applied the planned engineering change through Forge Engine typed operations.")
                job.assistant_text = answer
                await legacy.broadcast({"type": "job.token", "job_id": job.id, "token": answer})
                job.cancellable = False
                await legacy.update_job(job, state=JobState.APPLYING, progress=0.62, message="Applying typed engineering operations")
                result = {"assistant_text": answer, "plan": plan}
                result.update(
                    await asyncio.to_thread(
                        _apply_agent_transaction,
                        legacy,
                        job,
                        lambda: legacy.PROJECT.apply_agent_plan(plan, request.text or "AI engineering change"),
                    )
                )
            else:
                answer = await legacy.qwen_reply(request.text or "Review the active design", job)
                if job.state == JobState.CANCELLED:
                    return
                result = await asyncio.to_thread(
                    _validate_read_only_agent,
                    legacy,
                    job,
                    {"assistant_text": answer},
                )

            if job.state == JobState.CANCELLED:
                return
            job.cancellable = False
            await legacy.update_job(job, state=JobState.VERIFYING, progress=0.88, message="Recording revision-bound verification result")
            job.result = result
            project = result.get("project") if isinstance(result.get("project"), dict) else None
            if project and _final_project_matches(legacy, project):
                await legacy.broadcast({"type": "project.updated", "project": project})
            await legacy.update_job(job, state=JobState.COMPLETED, progress=1.0, message="Complete")
        except Exception as exc:
            if job.state == JobState.CANCELLED:
                return
            job.cancellable = False
            job.error = {"code": "agent_stale" if "stale" in str(exc).lower() else "agent_failed", "message": str(exc), "recoverable": True}
            await legacy.update_job(job, state=JobState.FAILED, progress=1.0, message=str(exc))

    async def run_engineering_job(job: EngineeringJob, request: CreateJobRequest) -> None:
        try:
            if job.state == JobState.CANCELLED:
                return
            # Once a stateful worker begins, Python's thread cannot be interrupted
            # safely. Expose that truth instead of accepting a fake cancellation.
            job.cancellable = False
            await legacy.update_job(job, state=JobState.ANALYZING, progress=0.18, message=f"Running {job.kind} on pinned revision")
            result, project = await asyncio.to_thread(_run_engineering_transaction, legacy, job, request)
            await legacy.update_job(job, state=JobState.VERIFYING, progress=0.85, message="Recording revision-bound result")
            job.result = result
            if job.kind in {"campaign", "simulation"} and _final_project_matches(legacy, project):
                await legacy.broadcast({"type": "project.updated", "project": project})
            await legacy.update_job(job, state=JobState.COMPLETED, progress=1.0, message="Complete")
        except Exception as exc:
            if job.state == JobState.CANCELLED:
                return
            job.cancellable = False
            job.error = {"code": "job_stale" if "stale" in str(exc).lower() else "job_failed", "message": str(exc), "recoverable": True}
            await legacy.update_job(job, state=JobState.FAILED, progress=1.0, message=str(exc))

    async def cancel_job(job_id: str) -> EngineeringJob:
        job = legacy._jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.state in TERMINAL:
            return job
        if not job.cancellable:
            raise HTTPException(
                status_code=409,
                detail="This job is already in a non-interruptible canonical engineering phase; its result cannot be truthfully cancelled mid-transaction.",
            )
        job.state = JobState.CANCELLED
        job.cancellable = False
        job.message = "Cancelled before canonical apply/analysis"
        await legacy.broadcast({"type": "job.updated", "job": job.model_dump()})
        return job

    async def branch_status(branch_name: str, request: Any) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                set_design_label_preserving_evidence,
                branch_name,
                str(request.status),
                str(request.note or ""),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Branch not found") from exc
        snapshot = _snapshot_locked(legacy)
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"branch": result, "project": snapshot}

    async def activate_branch(branch_name: str) -> dict[str, Any]:
        try:
            snapshot = await asyncio.to_thread(legacy.PROJECT.activate_branch, branch_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Branch not found") from exc
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return snapshot

    async def create_branch(request: Any) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(legacy.PROJECT.create_branch, str(request.name), str(request.reason or ""))
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return snapshot

    _replace_route(app, "/v2/jobs", "POST", create_job)
    _replace_route(app, "/v2/jobs/{job_id}/cancel", "POST", cancel_job)
    _replace_route(app, "/v2/branches/{branch_name}/status", "PUT", branch_status)
    _replace_route(app, "/v2/branches/{branch_name}/activate", "POST", activate_branch)
    _replace_route(app, "/v2/branches", "POST", create_branch)

    # Retain module-level names for direct regression checks and debugging.
    legacy.run_agent_job = run_agent_job
    legacy.run_engineering_job = run_engineering_job
    app.state.forgecad_v601_runtime_installed = True
