from __future__ import annotations

"""ForgeCAD 2.0 application entrypoint.

The v1.1 FastAPI surface and deterministic CAD execution engine remain intact.  This
module replaces the one-shot agent planner with a two-stage design-intelligence loop:

1. decompose the user goal into requirements and functional capabilities;
2. resolve each capability against existing assets, real catalog candidates, software,
   or custom-part synthesis before asking the model for typed CAD operations.

That separation is the core ForgeCAD 2.0 architectural change.  The model chooses what
the system must do; Forge Engine still owns geometry, component identity, state, and
validation.
"""

import json
from typing import Any

import httpx
from fastapi import Depends
from pydantic import BaseModel

from . import main as legacy
from .models import EngineeringJob, JobState, OllamaState
from .v200 import DESIGN_INTELLIGENCE_VERSION
from .v200 import design_intelligence


app = legacy.app


class ArchitectureRequest(BaseModel):
    text: str
    use_model: bool = True


def _json_object(raw: str, *, label: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"{label} did not return valid JSON")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must return a JSON object")
    return parsed


async def _model_json(system: str, payload: dict[str, Any], *, num_predict: int, temperature: float) -> dict[str, Any]:
    request = {
        "model": legacy.CONFIGURED_MODEL,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"), default=str)},
        ],
        "options": {"temperature": temperature, "num_ctx": 16384, "num_predict": num_predict},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(210.0, connect=3.0)) as client:
        response = await client.post(f"{legacy.OLLAMA_BASE_URL}/api/chat", json=request)
        response.raise_for_status()
    raw = str((response.json().get("message") or {}).get("content") or "")
    return _json_object(raw, label="ForgeCAD local model")


async def qwen_architecture(text: str) -> dict[str, Any]:
    project = legacy.PROJECT.snapshot()
    system = (
        "You are ForgeCAD 2.0's systems architect. Return JSON only. Do not choose exact parts yet. "
        "Decompose the user's goal into a buildable engineering architecture with keys goal, requirements, functions, assumptions, open_questions. "
        "requirements is an array of {id,statement,priority,verification}. functions is an array of "
        "{id,capability,description,kind,required,search_terms,constraints,depends_on}. "
        "Think across mechanical structure, sensing, actuation, power, compute, connectivity, software, thermal management, interfaces, and safety where relevant. "
        "A missing part in the current design is not a blocker; describe the required capability. External services are software capabilities, not physical catalog parts. "
        "Ask a question only when a genuinely blocking requirement cannot be safely inferred."
    )
    try:
        raw = await _model_json(
            system,
            {"request": text, "current_project": project},
            num_predict=1500,
            temperature=0.06,
        )
        return design_intelligence.normalize_architecture(raw, text, project)
    except Exception:
        # The deterministic bootstrap means architecture discovery still exists when a
        # small model emits malformed JSON or is temporarily unavailable.
        return design_intelligence.bootstrap_architecture(text, project)


def _planner_system() -> str:
    return (
        "You are ForgeCAD 2.0's engineering planner. Return JSON only with keys summary, commands, checks. "
        "You are given a resolved functional architecture. Treat the current assembly as a starting point, never as the component universe. "
        "For each required function: reuse existing_assets when suitable; otherwise select a candidate_component by its exact ID; "
        "if the function is software, write or update code in an existing programmable workspace; only synthesize a custom part when no catalog candidate is suitable. "
        "Do not invent object IDs or component IDs. Do not invent a physical component for an external software service. "
        "Each command is {op,args}. Allowed operations: add, add_component, replace_component, sync_component, update, transform, "
        "mate_components, connect_interfaces, disconnect, delete, add_feature, delete_feature, add_load, add_constraint, "
        "set_requirement, add_bom_item, add_note, code_write, code_delete, code_rename, project_name, settings. "
        "Purchased components must use exact registry IDs and may not be scaled or have their authoritative geometry rewritten. "
        "Use object_id from existing_assets for transforms, connections, and code_write. When credentials or deployment-specific values are unknown, "
        "generate configurable placeholders and identify them in checks rather than refusing the design. "
        "Keep physically verified baselines protected; Forge Engine will fork them automatically. "
        "The plan should make concrete progress whenever the architecture has a resolved existing asset, catalog candidate, software host, or custom-part path."
    )


async def qwen_plan(text: str) -> dict[str, Any]:
    project = legacy.PROJECT.snapshot()
    architecture = await qwen_architecture(text)
    context = design_intelligence.build_planner_context(text, architecture, project)
    payload = {"request": text, "design_context": context}
    plan = await _model_json(_planner_system(), payload, num_predict=2400, temperature=0.05)
    if not isinstance(plan.get("commands", []), list):
        raise ValueError("Engineering planner commands must be a list")

    repair, reason = design_intelligence.needs_plan_repair(plan, context, text)
    if repair:
        repaired_payload = {
            "request": text,
            "design_context": context,
            "previous_plan": plan,
            "critique": design_intelligence.repair_instruction(reason),
        }
        plan = await _model_json(_planner_system(), repaired_payload, num_predict=2600, temperature=0.04)
        if not isinstance(plan.get("commands", []), list):
            raise ValueError("Replanned engineering commands must be a list")
        repair_again, reason_again = design_intelligence.needs_plan_repair(plan, context, text)
        if repair_again:
            raise ValueError(f"ForgeCAD 2.0 planner did not produce an actionable design plan: {reason_again}")

    # Preserve the architecture in the job result so the UI and .focad format can expose
    # the rationale/requirements without trusting hidden model state.
    plan["architecture"] = {
        "goal": context.get("goal"),
        "requirements": context.get("requirements"),
        "functions": context.get("functions"),
        "assumptions": context.get("assumptions"),
        "open_questions": context.get("open_questions"),
        "design_intelligence_version": DESIGN_INTELLIGENCE_VERSION,
    }
    return plan


async def qwen_reply(text: str, job: EngineeringJob) -> str:
    architecture = await qwen_architecture(text)
    context = design_intelligence.build_planner_context(text, architecture, legacy.PROJECT.snapshot())
    system = (
        "You are ForgeCAD 2.0's engineering copilot. Reason from the supplied requirements and functional architecture, not only the parts currently in the scene. "
        "The deterministic Forge Engine is authoritative. Distinguish catalog facts from estimates, identify verification gaps, and never claim screening analysis certifies a safety-critical design. "
        "When a current part is missing, explain whether ForgeCAD should reuse an asset, select a catalog candidate, synthesize a custom part, or implement the function in software."
    )
    request = {
        "model": legacy.CONFIGURED_MODEL,
        "stream": True,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"request": text, "design_context": context}, separators=(",", ":"), default=str)},
        ],
        "options": {"temperature": 0.10, "num_ctx": 16384, "num_predict": 700},
    }
    answer: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(210.0, connect=3.0)) as client:
        async with client.stream("POST", f"{legacy.OLLAMA_BASE_URL}/api/chat", json=request) as response:
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
                    await legacy.broadcast({"type": "job.token", "job_id": job.id, "token": token})
    return "".join(answer).strip()


# Existing v1.1 job execution resolves these names from forge_engine.main at runtime, so
# replacing them here upgrades the agent without duplicating the stable CAD API surface.
legacy.qwen_plan = qwen_plan
legacy.qwen_reply = qwen_reply


@app.post("/v2/design/architecture", dependencies=[Depends(legacy.require_session)])
async def design_architecture(request: ArchitectureRequest) -> dict[str, Any]:
    project = legacy.PROJECT.snapshot()
    if request.use_model:
        state, _ = await legacy.ollama_status()
        architecture = await qwen_architecture(request.text) if state == OllamaState.READY else design_intelligence.bootstrap_architecture(request.text, project)
    else:
        architecture = design_intelligence.bootstrap_architecture(request.text, project)
    return design_intelligence.build_planner_context(request.text, architecture, project)
