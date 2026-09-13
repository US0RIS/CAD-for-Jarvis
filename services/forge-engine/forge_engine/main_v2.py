from __future__ import annotations

"""ForgeCAD 2.0 application entrypoint.

The v1.1 FastAPI surface and deterministic CAD execution engine remain intact. This
module replaces the one-shot agent planner with a two-stage design-intelligence loop:

1. decompose the user goal into requirements and functional capabilities;
2. resolve each capability against existing assets, real catalog candidates, software,
   or custom-part synthesis before asking the model for typed CAD operations.

That separation is the core ForgeCAD 2.0 architectural change. The model chooses what
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
from .v200 import design_intelligence, parametric_expressions


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
        "Think across mechanical structure, mechanism travel/kinematics, sensing, actuation, power, compute, connectivity, software, electrical interfaces and signal levels, thermal management, fluid/hydraulic systems, cable/tube routing, manufacturing tolerance, packaging, and safety/failure modes where relevant. "
        "A missing part in the current design is not a blocker; describe the required capability. External services are software capabilities, not physical catalog parts. "
        "Infer ordinary implementation details when safe. Ask a question only when a genuinely blocking requirement cannot be safely inferred."
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
        return design_intelligence.bootstrap_architecture(text, project)


def _planner_system() -> str:
    return (
        "You are ForgeCAD 2.0's engineering planner. Return JSON only with keys summary, commands, checks. "
        "You are given a resolved functional architecture. Treat the current assembly as a starting point, never as the component universe. "
        "For each required function: reuse existing_assets when suitable; otherwise select candidate_components by exact ID; "
        "if the function is software, write or update code in an existing programmable workspace; synthesize custom fabricated geometry when no catalog part should exist. "
        "Do not invent object UUIDs or component IDs. Do not invent a physical component for an external software service. "
        "Each command is {op,args} and creation commands may also include a top-level symbolic handle using {as:'name'}. "
        "Later command arguments may reference a created object as '$name'; Forge Engine resolves it to the actual UUID after creation. "
        "Use this whenever a new part must subsequently be moved, mated, wired, machined, plumbed, routed, or programmed in the same plan. "
        "Allowed operations: add, add_component, replace_component, sync_component, update, transform, mate_components, add_joint, delete_joint, connect_interfaces, label_electrical_net, disconnect, delete, "
        "add_route, update_route, delete_route, add_failure_mode, update_failure_mode, delete_failure_mode, add_feature, delete_feature, split_for_manufacturing, set_design_parameter, delete_design_parameter, add_load, add_constraint, set_requirement, add_bom_item, add_note, code_write, code_delete, code_rename, project_name, settings. "
        "For purchased hardware use add_component with an exact candidate ID; purchased components may not be scaled, split, or have authoritative geometry rewritten. "
        "For simple custom fabricated parts use add with kind box, cylinder, sphere, sketch_extrude, or revolve. "
        "When several dimensions encode the same design intent, define named project parameters before creating geometry. set_design_parameter args are "
        "{name,value,unit?,description?} for a literal or {name,expression,unit?,description?} for a derived value. Derived expressions may use other parameter names, basic arithmetic, "
        "pi/e/tau, and the safe math functions abs,min,max,sqrt,sin,cos,tan,asin,acos,atan,radians,degrees,floor,ceil. "
        "Reference a named parameter inside custom-part params or feature dimensions with {expr:'parameter_name'} or {expr:'body_width + 2 * clearance'}. "
        "Keep placement transforms literal; expression references are for authoritative custom geometry dimensions/features. Prefer named expressions when changing one engineering variable should regenerate several related dimensions. "
        "When a custom part is governed by mechanical dimensions or geometric relationships, prefer kind constrained_sketch_extrude so the design remains dimension-driven instead of freezing arbitrary vertex coordinates. "
        "constrained_sketch_extrude params are {height,sketch:{points:[[x,y],...],constraints:[...],require_fully_constrained:true}}. Its numeric point coordinates and constraint values may themselves be expression nodes when they derive from named parameters. "
        "Supported sketch constraints are fixed {point,x,y}, fixed_x {point,x}, fixed_y {point,y}, horizontal {a,b}, vertical {a,b}, coincident {a,b}, distance {a,b,value}, "
        "x_distance {a,b,value}, y_distance {a,b,value}, equal_length {a,b,c,d}, parallel {a,b,c,d}, perpendicular {a,b,c,d}, angle {a,b,c,d,angle_deg}, and midpoint {point,a,b}. "
        "Use enough independent constraints to remove every sketch degree of freedom. Start from sensible approximate points; constraints define the authoritative solved geometry. "
        "box params: {x,y,z}; cylinder: {radius,height}; sphere: {radius}; sketch_extrude: {height,sketch:{type:'rectangle'|'circle'|'polygon',width?,height?,radius?,points?}}; "
        "revolve: {points:[[radius,z],...],angle_deg}. Supply material, transform, and semantic role/tags when useful. "
        "After creating custom geometry, add_feature can add holes {type:'hole',diameter,axis,x,y,z}, circular/rectangular pockets, fillets, or chamfers. "
        "Electrical connections are canonical engineering data, not prose. For power or signal wiring use connect_interfaces with exact interface IDs and include net_name when the rail/bus identity is known. "
        "connect_interfaces electrical args may include {a_id:'$source',a_interface:'vout',b_id:'$load',b_interface:'power',kind:'electrical',net_name:'+5V',net_class:'power',nominal_voltage_v:5.0}. "
        "Use the same explicit net_name for electrically identical fan-out connections. Valid net_class values are power, ground, signal, data, mixed, unknown. Use nominal_voltage_v only when supported by frozen component data or an explicit requirement; never invent a rail voltage or missing current rating. "
        "Connect required modeled power/signal inputs when the architecture needs them. ForgeCAD compiles canonical nets and checks voltage/current/logic compatibility, required-interface coverage, conflicting sources, and known current budgets. It does not perform SPICE, PCB signal-integrity, or EMI/EMC analysis. "
        "label_electrical_net is only for an existing known connection_id; prefer setting net metadata directly on connect_interfaces when creating new wiring in the same plan. "
        "Thermal behavior is canonical engineering data when it matters to the design. Add heat generation with add_load {object_id:'$electronics',type:'heat',heat_w:12}. "
        "Represent an explicit conductive path with add_constraint {type:'thermal_link',a_id:'$electronics',b_id:'$sink',conductance_w_k:2.5}; alternatively provide area_mm2, length_mm and thermal_w_mk for an explicit k*A/L link. "
        "Represent environmental rejection with add_constraint {object_id:'$enclosure',type:'convection',ambient_c:25,h_w_m2k:8,exposed_fraction:0.8}, or a known sink with {object_id:'$cold_plate',type:'fixed_temperature',temperature_c:35}. "
        "Encode a thermal requirement with {object_id:'$electronics',type:'temperature_limit',max_temperature_c:85}. Never infer contact conductance from bodies touching in CAD, and never invent convection coefficients, ambient conditions, heat dissipation or temperature limits. "
        "ForgeCAD's ThermalNetwork is a steady-state lumped-body conductance model; it does not replace transient thermal analysis, radiation, CFD/airflow, or certification testing. "
        "Fluid/hydraulic topology is also canonical project data. Use add_constraint {object_id:'$reservoir',type:'fluid_pressure',pressure_kpa:250} for a known pressure boundary and add_load {object_id:'$actuator',type:'fluid_demand',flow_l_min:0.5} for a known positive outflow demand. "
        "Create every solved path explicitly with add_constraint {type:'fluid_link',a_id:'$pump',b_id:'$actuator',resistance_pa_s_m3:2e9}, or use {type:'tube',a_id:'$pump',b_id:'$actuator',inner_diameter_mm:4,dynamic_viscosity_pa_s:0.001,density_kg_m3:998} and bind it to a canonical routed tube for authoritative physical length. "
        "Use add_constraint {object_id:'$actuator',type:'fluid_pressure_limit',min_pressure_kpa:150,max_pressure_kpa:300} when a pressure requirement is known. Never infer a hose, pipe, valve, seal, fluid path, pump pressure, viscosity, diameter, demand, leakage, or pressure limit from CAD proximity. "
        "ForgeCAD FluidNetwork is steady-state incompressible single-phase screening. It fails closed when a tube's explicit Reynolds data leave the laminar regime and does not model compressible pneumatics, turbulent/minor losses, nonlinear pump/valve curves, cavitation, water hammer, two-phase flow or CFD. "
        "When cable/tube/hose routing matters, create canonical route geometry with add_route. Example: {name:'5 V harness',kind:'cable',points_mm:[[0,0,0],[40,0,0],[40,30,0]],outer_diameter_mm:4,min_bend_radius_mm:12,clearance_mm:2,max_length_mm:150,connection_id:'known-connection-id',a_object_id:'$controller',b_object_id:'$load'}. "
        "For a physical fluid path, use kind:'tube' or 'hose' with fluid_link_id:'known-fluid-link-id'. A fluid-bound tube route automatically supplies authoritative centerline length to Hagen-Poiseuille tube resistance when the fluid link does not duplicate an explicit resistance. "
        "Route waypoints, diameter, bend radius, clearance, service length and endpoint binding are engineering inputs; never invent unknown routing constraints. ForgeCAD checks exact polyline length, circular tangent-bend feasibility, electrical/fluid bindings, and conservative expanded-AABB obstacle proxies. Obstacle proxies require inspection; they are not exact flexible-body collision. "
        "Mechanism motion is canonical engineering state. For a revolute mechanism use add_joint {name:'arm hinge',type:'revolute',parent_id:'$base',child_id:'$arm',origin_mm:[0,0,0],axis:[0,0,1],lower_deg:-30,upper_deg:90,home_deg:0,validate_sweep:true}. For a linear slide use type:'prismatic' with lower_mm, upper_mm and home_mm. "
        "ForgeCAD MechanismKinematics computes deterministic rigid child poses, sampled full-limit sweeps, swept bounds and exact B-rep intersection against modeled obstacles. The current revolute solver requires a world-principal axis and zero child base rotation, and each moving child may belong to only one analyzed joint. Do not claim joint-chain, closed-loop, compliant, backlash, actuator-force or dynamic motion support. A sampled collision is a hard project-validation failure. "
        "Safety/failure modes are canonical engineering state when the design can cause meaningful harm or equipment damage. Add them with add_failure_mode, for example {name:'Unexpected actuator motion',category:'control',cause:'stale command or sensor fault',effect:'pinch/collision hazard',object_ids:['$actuator'],severity:9,occurrence:3,detection:4,controls:['hardware enable interlock','travel limit switch'],verification_method:'fault injection and emergency-stop test'}. "
        "Severity is required on the 1–10 FMEA scale. occurrence and detection are optional 1–10 rankings and MUST remain omitted/unknown when unsupported; ForgeCAD computes RPN only when all three are explicit. Propose concrete controls and a verification method, but never invent test results, probabilities, standards compliance, or a reduced severity after mitigation without evidence. "
        "The agent may add/update/delete failure modes but cannot mark them physically verified. Severity 8–10 modes remain a hard release/validation blocker until controls exist and a separate human/evidence verification endpoint records a current-design passed result. Do not try to evade that gate by deleting a credible hazard or lowering its severity without an engineering basis. "
        "When fit, clearance, preload, or assembled length depends on manufacturing variation, encode a canonical 1D tolerance stack with add_constraint rather than only mentioning tolerance in prose. "
        "A contributor uses {type:'dimension_tolerance',stack:'stack_name',name:'dimension',object_id:'$part',parameter:'x',coefficient:1,minus_mm:0.05,plus_mm:0.10,sigma_mm?:0.02}. "
        "Instead of object_id+parameter it may use design_parameter:'name' or a literal nominal_mm. Use negative coefficient for subtractive dimensions. Add one stack spec as "
        "{type:'tolerance_spec',stack:'stack_name',lower_spec_mm:...,upper_spec_mm:...}. Only provide sigma_mm when it is known process standard deviation; never infer sigma from drawing tolerance. "
        "ForgeCAD computes worst-case, RSS and contributor sensitivity from these records, and statistical yield/Cp/Cpk only when every active contributor has explicit sigma. Tolerance records are nonstructural and do not replace FEA boundary conditions. "
        "When a fabricated body exceeds an available manufacturing resource, do not merely report that it is too large. For a Bambu Lab P2S use split_for_manufacturing with "
        "{id:'$part',resource_id:'bambu-lab-p2s',margin_mm:8,max_pieces:24,alignment_diameter_mm:3.2,alignment_depth_mm:8}. "
        "That operation creates a protected sibling manufacturing branch, preserves the unsplit source, generates actual clipped printable solids and optional alignment sockets, and leaves joint strength unverified. "
        "After splitting, re-run manufacturing, structural/joint, assembly, tolerance, electrical, thermal, fluid, routing, kinematics, safety, and requirement validation as applicable; never treat alignment sockets as proof that the seam is mechanically adequate. "
        "Prefer editable parametric geometry over a visually plausible but dimensionally arbitrary shape. Never use scaling to hide incorrect dimensions. "
        "Use object_id from existing_assets for existing transforms, connections, routes, joints, failure modes, and code_write. When credentials or deployment-specific values are unknown, "
        "generate configurable placeholders and identify them in checks rather than refusing the design. "
        "Keep physically verified baselines protected; Forge Engine will fork them automatically. "
        "The plan should make concrete progress whenever the architecture has a resolved existing asset, catalog candidate, software host, custom-part path, or manufacturing adaptation path."
    )


def _planner_context(text: str, architecture: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    context = design_intelligence.build_planner_context(text, architecture, project)
    try:
        context["design_parameters"] = parametric_expressions.parameter_report()
    except ValueError as exc:
        context["design_parameters"] = {"count": 0, "parameters": [], "values": {}, "error": str(exc)}
    return context


async def qwen_plan(text: str) -> dict[str, Any]:
    project = legacy.PROJECT.snapshot()
    architecture = await qwen_architecture(text)
    context = _planner_context(text, architecture, project)
    payload = {"request": text, "design_context": context}
    plan = await _model_json(_planner_system(), payload, num_predict=2800, temperature=0.05)
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
        plan = await _model_json(_planner_system(), repaired_payload, num_predict=3000, temperature=0.04)
        if not isinstance(plan.get("commands", []), list):
            raise ValueError("Replanned engineering commands must be a list")
        repair_again, reason_again = design_intelligence.needs_plan_repair(plan, context, text)
        if repair_again:
            raise ValueError(f"ForgeCAD 2.0 planner did not produce an actionable design plan: {reason_again}")

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
    context = _planner_context(text, architecture, legacy.PROJECT.snapshot())
    system = (
        "You are ForgeCAD 2.0's engineering copilot. Reason from the supplied requirements and functional architecture, not only the parts currently in the scene. "
        "The deterministic Forge Engine is authoritative. Distinguish catalog facts from estimates, identify verification gaps, and never claim screening analysis certifies a safety-critical design. "
        "When a current part is missing, explain whether ForgeCAD should reuse an asset, select a catalog candidate, synthesize a custom part, or implement the function in software. "
        "When the supplied design_parameters show a named relationship, preserve that relationship instead of replacing it with duplicated literal dimensions. "
        "Treat the compiled electrical graph as canonical topology/power evidence when present: distinguish known rail/current/logic incompatibilities from unknown ratings, and do not imply it replaces SPICE, PCB signal-integrity, EMI/EMC, or certification analysis. "
        "Treat the thermal network as canonical steady-state thermal evidence when present: keep explicit heat, conductance, convection and sink assumptions visible, and do not imply the lumped network replaces transient thermal analysis, radiation, CFD or physical verification. "
        "Treat the fluid network as canonical steady-state incompressible hydraulic evidence when present: preserve explicit pressure, resistance, tube-property and flow-demand assumptions, and do not imply it covers compressible pneumatics, turbulent/minor losses, nonlinear pump/valve curves or CFD. "
        "Treat routed cable/tube geometry as canonical physical path evidence when present: exact length and bend feasibility are deterministic, while obstacle checks are conservative bounding-box proxies and not exact flexible-body installation proof. "
        "Treat mechanism kinematics as canonical rigid-motion evidence when present: sampled exact B-rep collisions and joint-limit poses are deterministic for the supported single-joint scope, but do not imply continuous collision, joint-chain, compliance or dynamics support. "
        "Treat the safety register as canonical release evidence: do not claim a severity 8–10 mode is cleared without current-design passed verification, and do not turn unknown occurrence/detection into invented RPN inputs. "
        "Treat tolerance stacks as canonical engineering evidence: separate worst-case/RSS results from statistical yield, and never infer sigma from a drawing tolerance."
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


# Existing v1.1 job execution resolves these names from forge_engine.main at runtime.
# v200 installs the bounded agent loop and these replacements upgrade its reasoning calls.
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
    return _planner_context(request.text, architecture, project)
