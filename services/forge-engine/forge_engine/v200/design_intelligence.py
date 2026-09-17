from __future__ import annotations

"""Functional architecture and capability resolution for ForgeCAD 2.0.

The model first reasons about what a system must do. This deterministic layer then
maps those functions to existing design assets, real catalog candidates, software,
or custom-part synthesis. The CAD engine remains the authority that applies edits.
"""

from copy import deepcopy
import re
from typing import Any, Iterable

from ..v110 import component_registry as registry


CAPABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "physical_state_sensing": {"categories": ["sensor"], "search": ["sensor switch contact reed hall position state"]},
    "distance_sensing": {"categories": ["sensor"], "search": ["distance tof ultrasonic proximity sensor"]},
    "motion_sensing": {"categories": ["sensor"], "search": ["imu accelerometer gyro motion sensor"]},
    "programmable_compute": {"categories": ["compute", "microcontroller"], "search": ["programmable compute microcontroller gpio"]},
    "network_connectivity": {"categories": ["compute", "microcontroller"], "search": ["wifi ethernet network programmable"]},
    "linear_actuation": {"categories": ["solenoid", "linear_motion", "servo"], "search": ["linear actuator solenoid servo push pull"]},
    "rotary_actuation": {"categories": ["stepper_motor", "dc_motor", "gearmotor", "bldc_motor", "servo"], "search": ["motor servo stepper gearmotor rotary actuator"]},
    "power_conversion": {"categories": ["power", "power_converter", "power_supply"], "search": ["power supply regulator converter"]},
    "energy_storage": {"categories": ["battery"], "search": ["battery energy storage power"]},
    "mechanical_support": {"categories": ["extrusion", "fastener", "bearing", "linear_motion", "enclosure"], "search": ["mount frame fastener bearing enclosure support"]},
    "rotation_support": {"categories": ["bearing", "shaft", "coupler"], "search": ["bearing shaft coupler rotary support"]},
    "thermal_management": {"categories": ["fan"], "search": ["fan cooling thermal airflow"]},
    "vision": {"categories": ["camera", "sensor"], "search": ["camera vision image sensor"]},
    "human_input": {"categories": ["switch", "sensor", "microcontroller"], "search": ["button switch knob encoder input"]},
    "visual_output": {"categories": ["display"], "search": ["display oled lcd screen"]},
    "fluid_movement": {"categories": ["pump", "valve"], "search": ["pump valve fluid water"]},
    "software_integration": {"software_only": True, "search": []},
    "remote_notification": {"software_only": True, "search": []},
}


_KEYWORD_CAPABILITIES: list[tuple[tuple[str, ...], str, str]] = [
    (("door", "window", "drawer", "open", "closed", "contact"), "physical_state_sensing", "Detect the requested physical state transition."),
    (("notify", "notification", "message", "webhook", "remote"), "remote_notification", "Produce the requested remote notification in software."),
    (("wifi", "internet", "ethernet", "network", "webhook"), "network_connectivity", "Provide network connectivity for the requested service."),
    (("code", "python", "firmware", "program", "software", "gpio"), "programmable_compute", "Run the sensing, control, or integration software."),
    (("distance", "proximity", "range"), "distance_sensing", "Measure distance or proximity."),
    (("motion", "accelerometer", "gyro", "imu"), "motion_sensing", "Measure motion or orientation."),
    (("push", "pull", "linear actuator", "solenoid"), "linear_actuation", "Produce controlled linear motion."),
    (("rotate", "rotation", "motor", "spin", "wheel"), "rotary_actuation", "Produce controlled rotary motion."),
    (("battery", "portable", "untethered"), "energy_storage", "Store enough energy for operation."),
    (("power", "voltage", "supply", "regulator"), "power_conversion", "Provide compatible power rails."),
    (("cool", "fan", "thermal", "heat"), "thermal_management", "Keep components inside thermal limits."),
    (("camera", "vision", "image", "photo"), "vision", "Capture the requested visual information."),
    (("pump", "water", "fluid", "valve"), "fluid_movement", "Move or control the requested fluid."),
    (("mount", "frame", "bracket", "support", "enclosure", "case"), "mechanical_support", "Physically support and package the system."),
]


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_.+-]+", value.lower()) if token}


def _has_any(text: str, needles: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _function(fid: str, capability: str, description: str, *, kind: str = "hardware", required: bool = True, search_terms: list[str] | None = None, constraints: dict[str, Any] | None = None, depends_on: list[str] | None = None) -> dict[str, Any]:
    return {"id": fid, "capability": capability, "description": description, "kind": kind, "required": bool(required), "search_terms": list(search_terms or []), "constraints": deepcopy(constraints or {}), "depends_on": list(depends_on or [])}


def bootstrap_architecture(text: str, project: dict[str, Any] | None = None) -> dict[str, Any]:
    functions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for needles, capability, description in _KEYWORD_CAPABILITIES:
        if not _has_any(text, needles) or capability in seen:
            continue
        profile = CAPABILITY_PROFILES.get(capability, {})
        kind = "software" if profile.get("software_only") else "hardware"
        functions.append(_function(f"F{len(functions)+1}", capability, description, kind=kind, search_terms=list(profile.get("search") or [])))
        seen.add(capability)
    if "remote_notification" in seen and "software_integration" not in seen:
        functions.append(_function(f"F{len(functions)+1}", "software_integration", "Implement event handling and the external service integration in a programmable workspace.", kind="software"))
        seen.add("software_integration")
    if not functions:
        functions.append(_function("F1", "custom_system_function", f"Satisfy the user goal: {text.strip()}", kind="mixed", search_terms=[text.strip()]))
    requirements = [{"id": "R1", "statement": text.strip() or "Satisfy the requested design goal.", "priority": "must", "verification": "End-to-end functional verification against the requested behavior."}]
    return {"goal": text.strip(), "requirements": requirements, "functions": functions, "assumptions": [], "open_questions": [], "source": "deterministic-bootstrap"}


def normalize_architecture(raw: Any, text: str, project: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = bootstrap_architecture(text, project)
    if not isinstance(raw, dict):
        return fallback
    requirements: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("requirements") or []):
        if isinstance(item, str): item = {"statement": item}
        if not isinstance(item, dict) or not str(item.get("statement") or "").strip(): continue
        requirements.append({"id": str(item.get("id") or f"R{index+1}"), "statement": str(item.get("statement")).strip(), "priority": str(item.get("priority") or "must").lower(), "verification": str(item.get("verification") or "Verify against the finished design.")})
    functions: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("functions") or []):
        if isinstance(item, str): item = {"capability": item, "description": item}
        if not isinstance(item, dict): continue
        capability = str(item.get("capability") or item.get("name") or "").strip().lower().replace(" ", "_")
        if not capability: continue
        profile = CAPABILITY_PROFILES.get(capability, {})
        kind = str(item.get("kind") or ("software" if profile.get("software_only") else "hardware")).lower()
        terms = [str(x).strip() for x in (item.get("search_terms") or []) if str(x).strip()] or list(profile.get("search") or [])
        functions.append(_function(str(item.get("id") or f"F{index+1}"), capability, str(item.get("description") or capability.replace("_", " ")).strip(), kind=kind, required=bool(item.get("required", True)), search_terms=terms, constraints=item.get("constraints") if isinstance(item.get("constraints"), dict) else {}, depends_on=[str(x) for x in (item.get("depends_on") or [])]))
    if not requirements: requirements = fallback["requirements"]
    if not functions: functions = fallback["functions"]
    known = {str(f.get("capability")) for f in functions}
    for seeded in fallback["functions"]:
        if seeded["capability"] not in known:
            copy = deepcopy(seeded); copy["id"] = f"F{len(functions)+1}"; functions.append(copy); known.add(copy["capability"])
    return {"goal": str(raw.get("goal") or text).strip(), "requirements": requirements, "functions": functions, "assumptions": [str(x) for x in (raw.get("assumptions") or [])], "open_questions": [str(x) for x in (raw.get("open_questions") or raw.get("questions") or [])], "source": str(raw.get("source") or "local-model")}


def _component_blob(component: dict[str, Any]) -> str:
    return " ".join([str(component.get("id") or ""), str(component.get("category") or ""), str(component.get("manufacturer") or ""), str(component.get("model") or ""), " ".join(str(x) for x in component.get("tags") or []), " ".join(str(i.get("kind") or "") for i in component.get("interfaces") or [] if isinstance(i, dict))]).lower()


def _summary(component: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(component.get("id") or ""), "manufacturer": str(component.get("manufacturer") or "Unknown"), "model": str(component.get("model") or component.get("name") or component.get("id") or "Component"), "category": str(component.get("category") or "custom"), "specs": deepcopy(component.get("specs") or {}), "interfaces": deepcopy(component.get("interfaces") or []), "geometry_fidelity": str((component.get("geometry") or {}).get("fidelity") or "unknown"), "trust_score": int(component.get("trust_score") or 0), "programmable": bool((component.get("software") or {}).get("programmable")), "platform": (component.get("software") or {}).get("platform")}


def _existing(function: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
    profile = CAPABILITY_PROFILES.get(str(function.get("capability") or ""), {})
    categories = set(str(x) for x in profile.get("categories") or [])
    terms = _tokens(" ".join([str(function.get("capability") or ""), str(function.get("description") or ""), *[str(x) for x in function.get("search_terms") or []]]))
    out: list[dict[str, Any]] = []
    for part in project.get("parts") or []:
        ref = str(part.get("component_ref") or "")
        if not ref: continue
        try: component = registry.component_by_id(ref)
        except KeyError: continue
        blob = _tokens(_component_blob(component))
        category_ok = not categories or str(component.get("category")) in categories
        programmable_ok = str(function.get("capability")) in {"programmable_compute", "network_connectivity", "software_integration", "remote_notification"} and bool((component.get("software") or {}).get("programmable"))
        if category_ok and (bool(terms & blob) or programmable_ok or not terms):
            out.append({"object_id": str(part.get("id")), "name": str(part.get("name") or component.get("name") or ref), "workspace_id": part.get("programmable_workspace_id"), "component": _summary(component)})
    return out


def _candidates(function: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    profile = CAPABILITY_PROFILES.get(str(function.get("capability") or ""), {})
    if profile.get("software_only") or str(function.get("kind")) == "software": return []
    categories = [str(x) for x in profile.get("categories") or []] or [None]
    queries = [str(x) for x in function.get("search_terms") or [] if str(x).strip()] or [f"{function.get('capability','')} {function.get('description','')}".strip()]
    constraints = function.get("constraints") if isinstance(function.get("constraints"), dict) else {}
    out: list[dict[str, Any]] = []; seen: set[str] = set()
    for category in categories:
        for query in queries[:3]:
            try: result = registry.search_components(query, category=category, constraints=constraints, limit=max(limit, 10), include_infeasible=True)
            except Exception: continue
            for component in result.get("results") or []:
                cid = str(component.get("id") or "")
                if not cid or cid in seen: continue
                seen.add(cid); out.append(_summary(component))
                if len(out) >= limit: return out
    return out


def resolve_architecture(architecture: dict[str, Any], project: dict[str, Any], *, candidates_per_function: int = 6) -> dict[str, Any]:
    resolved: list[dict[str, Any]] = []; flat: list[dict[str, Any]] = []; seen: set[str] = set()
    for original in architecture.get("functions") or []:
        function = deepcopy(original); profile = CAPABILITY_PROFILES.get(str(function.get("capability") or ""), {})
        existing = _existing(function, project); candidates = _candidates(function, candidates_per_function)
        software_only = bool(profile.get("software_only")) or str(function.get("kind")) == "software"
        if existing: status, resolution = "existing", "Reuse an existing design asset."
        elif software_only:
            hosts = _existing({"capability": "programmable_compute", "description": "programmable compute", "kind": "hardware", "search_terms": []}, project)
            existing = hosts; status = "software" if hosts else "needs_compute"; resolution = "Implement in an existing programmable workspace." if hosts else "Add or identify a programmable compute target, then implement in software."
        elif candidates: status, resolution = "catalog", "Select a real catalog component that satisfies this capability."
        else: status, resolution = "custom", "Synthesize a custom part or subsystem, or ask only for a genuinely blocking requirement."
        row = {**function, "status": status, "resolution": resolution, "existing_assets": existing, "candidate_components": candidates}; resolved.append(row)
        for candidate in candidates:
            if candidate["id"] not in seen: seen.add(candidate["id"]); flat.append(candidate)
    return {"goal": architecture.get("goal"), "requirements": deepcopy(architecture.get("requirements") or []), "functions": resolved, "assumptions": deepcopy(architecture.get("assumptions") or []), "open_questions": deepcopy(architecture.get("open_questions") or []), "source": architecture.get("source"), "candidate_components": flat, "project": deepcopy(project)}


def build_planner_context(text: str, architecture: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    return resolve_architecture(normalize_architecture(architecture, text, project), project)


def needs_plan_repair(plan: dict[str, Any], context: dict[str, Any], request_text: str) -> tuple[bool, str]:
    commands = plan.get("commands") if isinstance(plan, dict) else None
    if not isinstance(commands, list): return True, "The planner did not return a commands array."
    asks_change = _has_any(request_text, ("create", "make", "build", "add", "change", "modify", "design", "connect", "wire", "implement", "send", "notify"))
    actionable = [f for f in context.get("functions") or [] if bool(f.get("required", True)) and f.get("status") in {"catalog", "custom", "software", "needs_compute"}]
    if asks_change and actionable and not commands:
        return True, "The plan made no design changes even though required capabilities have actionable resolutions."
    summary = str(plan.get("summary") or "").lower()
    if any(marker in summary for marker in ("cannot be fulfilled", "cannot complete", "not possible", "do not include", "no component")):
        if any(f.get("status") in {"catalog", "existing", "software"} for f in context.get("functions") or []):
            return True, "The plan refused the task even though ForgeCAD resolved capabilities to existing assets, software, or catalog candidates."
    return False, ""


def repair_instruction(reason: str) -> str:
    return "REPLAN. " + reason + " Treat the current assembly as a starting point, not the component universe. Use exact candidate component IDs, reuse existing object IDs, implement service integrations in software, and use custom geometry only when no suitable catalog part exists. Return JSON only with summary, commands, checks."
