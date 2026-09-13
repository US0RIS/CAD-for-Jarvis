from __future__ import annotations

"""Bounded autonomous design/validate/repair loop for ForgeCAD 2.0.

ForgeCAD 1.x stopped after applying one model plan. 2.0 treats deterministic validation
as feedback: hard failures are summarized, the planner gets a bounded opportunity to
repair them, and validation is repeated. Warnings and unknown qualitative requirements
do not cause an infinite redesign loop.
"""

import asyncio
import json
from copy import deepcopy
from typing import Any

from ..models import EngineeringJob, JobState, OllamaState

MAX_REPAIR_ITERATIONS = 2


def validation_failures(validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(validation, dict):
        return []
    failures: list[dict[str, Any]] = []
    for risk in validation.get("risks") or []:
        if not isinstance(risk, dict) or str(risk.get("severity") or "").lower() != "error":
            continue
        failures.append({
            "kind": "validation_error",
            "code": str(risk.get("code") or "validation_error"),
            "message": str(risk.get("message") or "Deterministic validation error"),
        })
    for requirement in validation.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        status = str(requirement.get("status") or "").lower()
        failed = requirement.get("ok") is False or requirement.get("passed") is False or requirement.get("satisfied") is False or status in {"failed", "fail", "violation", "unsatisfied"}
        if not failed:
            continue
        failures.append({
            "kind": "requirement_failure",
            "code": str(requirement.get("id") or requirement.get("metric") or "requirement"),
            "message": str(requirement.get("message") or requirement.get("statement") or requirement.get("description") or "Requirement not satisfied"),
            "actual": requirement.get("actual", requirement.get("value")),
            "target": requirement.get("target"),
            "metric": requirement.get("metric"),
        })
    return failures


def should_repair(validation: dict[str, Any] | None, *, iteration: int, max_iterations: int = MAX_REPAIR_ITERATIONS) -> bool:
    if iteration >= max_iterations:
        return False
    return bool(validation_failures(validation))


def validation_fingerprint(validation: dict[str, Any] | None) -> str:
    compact = [
        {"kind": f.get("kind"), "code": f.get("code"), "message": f.get("message"), "actual": f.get("actual"), "target": f.get("target")}
        for f in validation_failures(validation)
    ]
    return json.dumps(compact, sort_keys=True, separators=(",", ":"), default=str)


def repair_request(original_request: str, validation: dict[str, Any], iteration: int) -> str:
    failures = validation_failures(validation)
    return (
        f"Continue the same design task and repair deterministic validation failures. Original request: {original_request}\n"
        f"Repair iteration: {iteration + 1}/{MAX_REPAIR_ITERATIONS}.\n"
        "Do not restart the design and do not remove working functionality merely to silence validation. "
        "Reuse current objects and exact catalog IDs when possible. Make the smallest engineering changes that resolve the failures. "
        "If a failure cannot be resolved without a genuinely missing user requirement, preserve the design and state that blocker in checks.\n"
        f"Validation failures: {json.dumps(failures, separators=(',', ':'), default=str)}"
    )


async def run_agent_job_v2(legacy: Any, job: EngineeringJob, request: Any) -> None:
    try:
        await legacy.update_job(job, state=JobState.WARMING, progress=0.06, message=f"Starting design intelligence · {legacy.CONFIGURED_MODEL}")
        ollama, _ = await legacy.ollama_status()
        if ollama != OllamaState.READY and not legacy.DEMO_AGENT:
            raise RuntimeError(f"Configured model {legacy.CONFIGURED_MODEL!r} is not available in Ollama")

        await legacy.update_job(job, state=JobState.PLANNING, progress=0.16, message="Decomposing goal into requirements and system functions")
        result: dict[str, Any]
        original_text = request.text or "Review and improve the design"
        original_architecture: dict[str, Any] | None = None

        if legacy.DEMO_AGENT and ollama != OllamaState.READY:
            answer = "Created a safe experimental branch and kept the known-good baseline protected.\n\n- Applied the request through Forge Engine's typed operation layer.\n- Preserved the embedded device workspace with the design branch.\n- Ran deterministic validation before completing the task."
            job.assistant_text = answer
            await legacy.broadcast({"type": "job.token", "job_id": job.id, "token": answer})
            result = {"assistant_text": answer, "design_loop": {"mode": "demo", "repair_iterations": 0}}
            if request.apply_edits:
                await legacy.update_job(job, state=JobState.APPLYING, progress=0.55, message="Applying typed engineering operations")
                result.update(legacy.PROJECT.apply_demo_change(original_text))
        elif request.apply_edits:
            await legacy.update_job(job, state=JobState.PLANNING, progress=0.24, message="Resolving functions to existing assets, catalog parts, software, and custom design")
            plan = await legacy.qwen_plan(original_text)
            if isinstance(plan.get("architecture"), dict):
                original_architecture = deepcopy(plan["architecture"])
            answer = str(plan.get("summary") or "Applied the planned engineering change through Forge Engine typed operations.")
            job.assistant_text = answer
            await legacy.broadcast({"type": "job.token", "job_id": job.id, "token": answer})
            await legacy.update_job(job, state=JobState.APPLYING, progress=0.46, message="Building the first design candidate")
            result = {"assistant_text": answer, "plan": plan, "plans": [plan]}
            result.update(legacy.PROJECT.apply_agent_plan(plan, original_text))
        else:
            answer = await legacy.qwen_reply(original_text, job)
            result = {"assistant_text": answer, "design_loop": {"mode": "analysis_only", "repair_iterations": 0}}

        if job.state == JobState.CANCELLED:
            return

        validations: list[dict[str, Any]] = []
        await legacy.update_job(job, state=JobState.VERIFYING, progress=0.68, message="Testing the design against deterministic reality checks")
        validation = await asyncio.to_thread(legacy.PROJECT.validation)
        validations.append(validation)

        repair_iteration = 0
        previous_fingerprint = validation_fingerprint(validation)
        while request.apply_edits and not legacy.DEMO_AGENT and should_repair(validation, iteration=repair_iteration):
            if job.state == JobState.CANCELLED:
                return
            failures = validation_failures(validation)
            await legacy.update_job(
                job,
                state=JobState.PLANNING,
                progress=min(0.72 + repair_iteration * 0.10, 0.88),
                message=f"Repairing design · pass {repair_iteration + 1}/{MAX_REPAIR_ITERATIONS} · {len(failures)} hard failure{'s' if len(failures) != 1 else ''}",
            )
            repair_plan = await legacy.qwen_plan(repair_request(original_text, validation, repair_iteration))
            if original_architecture is not None:
                # Repair is another pass over the same system architecture, not a new
                # user goal. This also prevents duplicate architecture notes/requirements.
                repair_plan["architecture"] = deepcopy(original_architecture)
            if not repair_plan.get("commands"):
                break
            result.setdefault("plans", []).append(repair_plan)
            await legacy.update_job(job, state=JobState.APPLYING, progress=min(0.78 + repair_iteration * 0.10, 0.92), message=f"Applying repair pass {repair_iteration + 1}")
            result.update(legacy.PROJECT.apply_agent_plan(repair_plan, f"Repair validation failures for: {original_text}"))
            if job.state == JobState.CANCELLED:
                return
            await legacy.update_job(job, state=JobState.VERIFYING, progress=min(0.84 + repair_iteration * 0.07, 0.95), message=f"Re-testing repaired design · pass {repair_iteration + 1}")
            next_validation = await asyncio.to_thread(legacy.PROJECT.validation)
            validations.append(next_validation)
            repair_iteration += 1
            fingerprint = validation_fingerprint(next_validation)
            validation = next_validation
            if fingerprint and fingerprint == previous_fingerprint:
                break
            previous_fingerprint = fingerprint

        result["validation"] = validation
        result["validation_history"] = validations
        result["design_loop"] = {
            "mode": "design_validate_repair" if request.apply_edits else "analysis_only",
            "repair_iterations": repair_iteration,
            "max_repair_iterations": MAX_REPAIR_ITERATIONS,
            "remaining_hard_failures": validation_failures(validation),
            "converged": not bool(validation_failures(validation)),
        }
        result["project"] = legacy.PROJECT.snapshot()
        job.branch = legacy.PROJECT.active_branch
        job.result = result
        await legacy.broadcast({"type": "project.updated", "project": result["project"]})
        final_failures = len(validation_failures(validation))
        final_message = "Design complete · deterministic checks passed" if final_failures == 0 else f"Design complete with {final_failures} unresolved hard failure{'s' if final_failures != 1 else ''}"
        await legacy.update_job(job, state=JobState.COMPLETED, progress=1.0, message=final_message)
    except Exception as exc:
        job.error = {"code": "agent_failed", "message": str(exc), "recoverable": True}
        await legacy.update_job(job, state=JobState.FAILED, progress=1.0, message=str(exc))


def install(legacy: Any) -> None:
    legacy.run_agent_job = lambda job, request: run_agent_job_v2(legacy, job, request)
