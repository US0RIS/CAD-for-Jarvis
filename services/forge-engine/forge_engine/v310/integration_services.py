from __future__ import annotations

"""Deterministic 3.1 integration services built on the canonical engineering graph."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field

from ..v110 import component_registry as registry
from ..v110 import core
from .engineering_graph import EngineeringEvidence, EngineeringGraphSnapshot, EngineeringGraphStore, build_engineering_graph


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cmp(value: float, op: str, target: float) -> bool:
    return {
        "<=": value <= target,
        ">=": value >= target,
        "<": value < target,
        ">": value > target,
        "==": math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-9),
        "!=": not math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-9),
    }.get(op, False)


def _raw_object(object_id: str) -> dict[str, Any]:
    return core.object_by_id(object_id)


def _world_payload(world: Any | None) -> dict[str, Any] | None:
    if world is None:
        return None
    snapshot = world.snapshot()
    if hasattr(snapshot, "model_dump"):
        return snapshot.model_dump(mode="json")
    return deepcopy(snapshot)


def synchronize_graph(graph: EngineeringGraphStore, project_snapshot: dict[str, Any], world: Any | None = None) -> dict[str, Any]:
    with core.LOCK:
        raw = deepcopy(core.PROJECT)
    return graph.synchronize(project_snapshot=project_snapshot, raw_project=raw, world_snapshot=_world_payload(world))


class RequirementSpec(BaseModel):
    id: str | None = None
    name: str
    metric: str
    op: Literal["<=", ">=", "<", ">", "==", "!="] = "<="
    target: float
    unit: str | None = None
    criticality: Literal["info", "normal", "important", "safety"] = "normal"
    scope_object_ids: list[str] = Field(default_factory=list)
    source: str = "human"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InspectionRequest(BaseModel):
    object_id: str
    metric: str
    observed: float
    expected: float | None = None
    unit: str | None = None
    tolerance: float | None = None
    source: str = "measurement"
    instrument: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeploymentRequest(BaseModel):
    object_id: str
    software_sha256: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    device_id: str | None = None
    firmware_version: str | None = None
    source: str = "device"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SubstitutionRequest(BaseModel):
    object_id: str
    query: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    allow_envelope_growth_pct: float = Field(default=0.0, ge=0.0, le=500.0)
    min_trust: int = Field(default=45, ge=0, le=100)
    min_geometry_fidelity: str | None = None
    max_candidates: int = Field(default=12, ge=1, le=100)


class SolverJobRequest(BaseModel):
    kind: str
    subject_node_ids: list[str]
    settings: dict[str, Any] = Field(default_factory=dict)
    requested_fidelity: Literal["screening", "engineering", "high_fidelity"] = "engineering"


class ProductProfileRequest(BaseModel):
    mode: Literal["general_engineering", "product_lab"] = "general_engineering"
    name: str | None = None
    envelope_mm: list[float] | None = None
    max_mass_g: float | None = None
    human_contact: bool = False
    wearable: bool = False
    stored_energy_limit_j: float | None = None
    max_surface_temperature_c: float | None = None
    preferred_processes: list[str] = Field(default_factory=list)
    ergonomic_keepouts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def set_product_profile(request: ProductProfileRequest) -> dict[str, Any]:
    profile = request.model_dump(mode="json")
    profile["schema_version"] = 1
    profile["updated_at"] = _now()
    with core.LOCK:
        core.PROJECT.setdefault("settings", {})["product_profile"] = profile
        core.push_history("set product profile", "human", f"workspace profile: {request.mode}")
        core.persist()
    return deepcopy(profile)


def product_profile() -> dict[str, Any]:
    with core.LOCK:
        profile = deepcopy((core.PROJECT.get("settings") or {}).get("product_profile") or {})
    profile.setdefault("schema_version", 1)
    profile.setdefault("mode", "general_engineering")
    return profile


def product_profile_findings() -> dict[str, Any]:
    profile = product_profile()
    metrics = core.project_metrics()
    findings: list[dict[str, Any]] = []
    if profile.get("mode") != "product_lab":
        return {"profile": profile, "findings": [], "ok": True}
    max_mass_g = profile.get("max_mass_g")
    if max_mass_g is not None:
        mass_g = float(metrics.get("mass_kg", 0.0)) * 1000.0
        if mass_g > float(max_mass_g):
            findings.append({"severity": "error", "code": "product_mass_budget", "message": f"Product mass {mass_g:.1f} g exceeds {float(max_mass_g):.1f} g budget", "value": mass_g, "limit": float(max_mass_g)})
    envelope = profile.get("envelope_mm")
    if envelope and len(envelope) >= 3:
        bounds = []
        for obj in core.PROJECT.get("objects", []):
            try:
                m = core.object_metrics(obj)["bounds_mm"]
                bounds.append([float(m["x"]), float(m["y"]), float(m["z"])])
            except Exception:
                continue
        if bounds:
            approx = [max(row[i] for row in bounds) for i in range(3)]
            for axis, actual, limit in zip("XYZ", approx, envelope):
                if actual > float(limit):
                    findings.append({"severity": "warning", "code": "product_envelope_budget", "message": f"Largest {axis} part extent {actual:.1f} mm exceeds product envelope axis budget {float(limit):.1f} mm", "axis": axis, "value": actual, "limit": float(limit)})
    if profile.get("human_contact"):
        safety_requirements = [row for row in core.PROJECT.get("requirements", []) if str(row.get("criticality")) == "safety"]
        if not safety_requirements:
            findings.append({"severity": "warning", "code": "human_contact_without_safety_requirements", "message": "Product Lab profile declares human contact but no safety-critical requirements are defined."})
    return {"profile": profile, "findings": findings, "ok": not any(row["severity"] == "error" for row in findings)}


def upsert_requirement(spec: RequirementSpec) -> dict[str, Any]:
    row = spec.model_dump(mode="json")
    row["id"] = spec.id or _id("req")
    row["updated_at"] = _now()
    with core.LOCK:
        requirements = core.PROJECT.setdefault("requirements", [])
        index = next((i for i, item in enumerate(requirements) if str(item.get("id")) == row["id"]), None)
        if index is None:
            requirements.append(row)
        else:
            requirements[index] = row
        core.push_history("upsert requirement", "human", f"{row['name']}: {row['metric']} {row['op']} {row['target']}")
        core.persist()
    return deepcopy(row)


def _metric_value(metric: str) -> tuple[float | None, str]:
    metrics = core.project_metrics()
    if metric in metrics and isinstance(metrics[metric], (int, float)):
        return float(metrics[metric]), "project_metrics"
    for simulation in reversed(core.PROJECT.get("simulations", [])):
        if simulation.get("stale"):
            continue
        result = simulation.get("result") or {}
        if metric in result and isinstance(result[metric], (int, float)):
            return float(result[metric]), f"analysis:{simulation.get('id') or simulation.get('kind')}"
    return None, "unresolved"


def verify_requirements(graph: EngineeringGraphStore) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    snapshot = graph.snapshot()
    graph_nodes = {row.id: row for row in snapshot.nodes}
    for requirement in core.PROJECT.get("requirements", []):
        req_id = str(requirement.get("id") or "")
        if not req_id:
            continue
        metric = str(requirement.get("metric") or "")
        value, source = _metric_value(metric)
        target = float(requirement.get("target", 0.0))
        op = str(requirement.get("op") or "<=")
        passed = None if value is None else _cmp(value, op, target)
        status = "unknown" if passed is None else ("pass" if passed else "fail")
        scope = [f"cad:{value}" for value in requirement.get("scope_object_ids", []) if f"cad:{value}" in graph_nodes]
        if not scope:
            scope = [f"requirement:{req_id}"] if f"requirement:{req_id}" in graph_nodes else [f"project:{snapshot.active_branch}"]
        evidence = EngineeringEvidence(
            id=f"evidence:req:{req_id}:{_hash([metric, value, target, op, source])[:16]}",
            kind="requirement_verification",
            subject_node_ids=scope,
            requirement_ids=[req_id],
            value=value,
            unit=requirement.get("unit"),
            status=status,
            method=source,
            source_ids=[source],
            assumptions=[] if value is not None else [f"No current canonical metric named {metric!r} was available"],
            confidence=float(requirement.get("confidence", 1.0) or 1.0) if value is not None else 0.0,
            metadata={"metric": metric, "op": op, "target": target, "criticality": requirement.get("criticality", "normal")},
        )
        graph.add_evidence(evidence)
        results.append({"requirement": deepcopy(requirement), "value": value, "status": status, "source": source, "evidence_id": evidence.id})
    counts = {state: sum(row["status"] == state for row in results) for state in ("pass", "fail", "unknown")}
    return {"items": results, "counts": counts, "ok": counts["fail"] == 0 and counts["unknown"] == 0}


def assembly_intelligence() -> dict[str, Any]:
    objects = {str(row.get("id")): row for row in core.PROJECT.get("objects", [])}
    connected: set[tuple[str, str]] = set()
    findings: list[dict[str, Any]] = []
    for connection in core.PROJECT.get("connections", []):
        for endpoint in (connection.get("a") or {}, connection.get("b") or {}):
            oid, iid = str(endpoint.get("object_id") or ""), str(endpoint.get("interface_id") or "")
            if oid and iid:
                connected.add((oid, iid))
    for oid, obj in objects.items():
        for interface in obj.get("interfaces", []):
            if interface.get("required") and (oid, str(interface.get("id"))) not in connected:
                findings.append({"severity": "error", "code": "required_interface_unconnected", "object_id": oid, "interface_id": interface.get("id"), "message": f"Required interface {interface.get('id')} on {obj.get('name') or oid} is not connected."})
    for joint in core.PROJECT.get("joints", []):
        a = str(joint.get("a_id") or joint.get("a") or joint.get("object_a") or "")
        b = str(joint.get("b_id") or joint.get("b") or joint.get("object_b") or "")
        jid = str(joint.get("id") or "joint")
        if a and a not in objects:
            findings.append({"severity": "error", "code": "joint_missing_object", "joint_id": jid, "object_id": a, "message": f"Joint {jid} references missing object {a}."})
        if b and b not in objects:
            findings.append({"severity": "error", "code": "joint_missing_object", "joint_id": jid, "object_id": b, "message": f"Joint {jid} references missing object {b}."})
        lo, hi = joint.get("min"), joint.get("max")
        if lo is not None and hi is not None and float(lo) > float(hi):
            findings.append({"severity": "error", "code": "joint_invalid_limits", "joint_id": jid, "message": f"Joint {jid} minimum exceeds maximum."})
        clearance = joint.get("service_clearance_mm")
        required = joint.get("minimum_service_clearance_mm")
        if clearance is not None and required is not None and float(clearance) < float(required):
            findings.append({"severity": "warning", "code": "service_clearance", "joint_id": jid, "message": f"Joint {jid} service clearance {float(clearance):g} mm is below {float(required):g} mm requirement."})
    return {"ok": not any(row["severity"] == "error" for row in findings), "findings": findings, "counts": {severity: sum(row["severity"] == severity for row in findings) for severity in ("error", "warning", "info")}}


def _interface_mapping(current: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    failures: list[str] = []
    candidate_interfaces = candidate.get("interfaces", [])
    for old in current.get("interfaces", []):
        old_id = str(old.get("id") or "")
        ranked: list[tuple[int, str]] = []
        for new in candidate_interfaces:
            result = registry.interface_compatibility(old, new)
            if result["compatible"]:
                score = 2 if old.get("kind") == new.get("kind") else 1
                if old.get("standard") and old.get("standard") == new.get("standard"):
                    score += 2
                ranked.append((-score, str(new.get("id") or "")))
        ranked.sort()
        if ranked:
            mapping[old_id] = ranked[0][1]
        elif old.get("required"):
            failures.append(f"required interface {old_id} ({old.get('kind')}) has no compatible candidate interface")
    return mapping, failures


def substitution_candidates(request: SubstitutionRequest, graph: EngineeringGraphStore) -> dict[str, Any]:
    obj = _raw_object(request.object_id)
    if obj.get("kind") != "component" or not obj.get("component_ref"):
        raise ValueError("Constraint-driven substitution requires a purchased component instance")
    current = registry.component_by_id(str(obj["component_ref"]))
    category = str(current.get("category") or "")
    result = registry.search_components(
        request.query,
        category=category,
        constraints=request.constraints,
        limit=max(request.max_candidates * 4, 25),
        include_infeasible=True,
        min_trust=request.min_trust,
        min_geometry_fidelity=request.min_geometry_fidelity,
    )
    current_dims = [float(v) for v in current.get("dimensions_mm", [0, 0, 0])[:3]]
    allowance = 1.0 + request.allow_envelope_growth_pct / 100.0
    impact = graph.impact(f"cad:{request.object_id}")
    candidates: list[dict[str, Any]] = []
    for candidate in result["results"]:
        if candidate.get("id") == current.get("id"):
            continue
        dims = [float(v) for v in candidate.get("dimensions_mm", [0, 0, 0])[:3]]
        envelope_ok = len(dims) == 3 and all(dims[i] <= current_dims[i] * allowance + 1e-9 for i in range(3))
        mapping, interface_failures = _interface_mapping(current, candidate)
        failures = [*candidate.get("constraint_failures", []), *interface_failures]
        if not envelope_ok:
            failures.append(f"envelope {dims} exceeds allowed {[(round(v * allowance, 3)) for v in current_dims]}")
        feasible = bool(candidate.get("feasible", True)) and envelope_ok and not interface_failures
        old_mass = current.get("mass_g")
        new_mass = candidate.get("mass_g")
        old_cost = (current.get("procurement") or {}).get("unit_cost_usd")
        new_cost = (candidate.get("procurement") or {}).get("unit_cost_usd")
        score = (1000 if feasible else 0) + int(candidate.get("trust_score", 0))
        if old_mass is not None and new_mass is not None:
            score += max(-100.0, min(100.0, float(old_mass) - float(new_mass)))
        candidates.append({
            "component_id": candidate.get("id"),
            "name": candidate.get("name"),
            "manufacturer": candidate.get("manufacturer"),
            "model": candidate.get("model"),
            "feasible": feasible,
            "score": score,
            "failures": failures,
            "interface_mapping": mapping,
            "dimensions_mm": dims,
            "mass_g": new_mass,
            "unit_cost_usd": new_cost,
            "delta_mass_g": None if old_mass is None or new_mass is None else float(new_mass) - float(old_mass),
            "delta_cost_usd": None if old_cost is None or new_cost is None else float(new_cost) - float(old_cost),
            "trust_score": candidate.get("trust_score", 0),
            "geometry_fidelity": (candidate.get("geometry") or {}).get("fidelity"),
        })
    candidates.sort(key=lambda row: (not row["feasible"], -float(row["score"]), str(row["name"])))
    return {"object_id": request.object_id, "current_component": current, "impact": impact, "items": candidates[: request.max_candidates], "count": min(len(candidates), request.max_candidates)}


def apply_substitution(object_id: str, component_id: str, graph: EngineeringGraphStore, *, actor: str = "jarvis", reason: str = "constraint-driven component substitution") -> dict[str, Any]:
    obj = _raw_object(object_id)
    if obj.get("kind") != "component" or not obj.get("component_ref"):
        raise ValueError("Target is not a purchased component")
    current = registry.component_by_id(str(obj["component_ref"]))
    candidate = registry.component_by_id(component_id)
    if current.get("category") != candidate.get("category"):
        raise ValueError(f"Component category mismatch: {current.get('category')} → {candidate.get('category')}")
    mapping, failures = _interface_mapping(current, candidate)
    if failures:
        raise ValueError("Replacement would break required interfaces: " + "; ".join(failures))
    before_impact = graph.impact(f"cad:{object_id}")
    core.execute("replace_component", {"id": object_id, "component_id": component_id}, actor=actor, reason=reason)
    unresolved: list[str] = []
    with core.LOCK:
        for connection in core.PROJECT.get("connections", []):
            for endpoint_name in ("a", "b"):
                endpoint = connection.get(endpoint_name) or {}
                if str(endpoint.get("object_id")) != object_id:
                    continue
                old_interface = str(endpoint.get("interface_id") or "")
                if old_interface in mapping:
                    endpoint["interface_id"] = mapping[old_interface]
                elif old_interface:
                    unresolved.append(old_interface)
        core.persist()
    graph.mark_dirty([f"cad:{object_id}"], reason=f"component substituted {current.get('id')} → {component_id}")
    return {
        "ok": not unresolved,
        "object_id": object_id,
        "old_component_id": current.get("id"),
        "new_component_id": component_id,
        "interface_mapping": mapping,
        "unresolved_connection_interfaces": sorted(set(unresolved)),
        "pre_change_impact": before_impact,
    }


def manufacturing_screening(object_id: str, process: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    obj = _raw_object(object_id)
    metrics = core.object_metrics(obj)
    bounds = metrics["bounds_mm"]
    features = obj.get("features", [])
    findings: list[dict[str, Any]] = []
    process = process.lower().strip()
    min_feature = float(settings.get("min_feature_mm", 0.8 if process in {"fdm", "sla", "sls"} else 1.0))
    min_extent = min(float(bounds["x"]), float(bounds["y"]), float(bounds["z"]))
    if min_extent < min_feature:
        findings.append({"severity": "error", "code": "minimum_extent", "message": f"Minimum part extent {min_extent:.3g} mm is below {min_feature:g} mm process screening limit."})
    if process in {"cnc", "cnc_3axis", "cnc_mill"}:
        tool_diameter = float(settings.get("tool_diameter_mm", 3.175))
        for feature in features:
            if feature.get("type") in {"hole", "circular_pocket", "pocket_circle"}:
                diameter = float(feature.get("diameter", 0) or 0)
                if diameter and diameter < tool_diameter:
                    findings.append({"severity": "error", "code": "tool_diameter", "feature_id": feature.get("id"), "message": f"Feature diameter {diameter:g} mm is smaller than selected tool {tool_diameter:g} mm."})
            if feature.get("type") in {"rectangular_pocket", "pocket_rect", "circular_pocket", "pocket_circle"}:
                depth = float(feature.get("depth", 0) or 0)
                if depth > tool_diameter * float(settings.get("max_depth_diameter_ratio", 4.0)):
                    findings.append({"severity": "warning", "code": "deep_pocket", "feature_id": feature.get("id"), "message": f"Pocket depth {depth:g} mm exceeds screening tool reach ratio."})
    elif process in {"fdm", "sla", "sls", "additive"}:
        nozzle = float(settings.get("nozzle_mm", 0.4))
        for feature in features:
            wall = feature.get("wall_thickness_mm")
            if wall is not None and float(wall) < max(min_feature, nozzle * 2.0):
                findings.append({"severity": "warning", "code": "thin_wall", "feature_id": feature.get("id"), "message": f"Wall {float(wall):g} mm is below additive screening recommendation."})
    elif process in {"sheet_metal", "sheet-metal"}:
        thickness = float((obj.get("params") or {}).get("thickness", min_extent))
        bend_radius = float(settings.get("bend_radius_mm", thickness))
        if bend_radius < thickness:
            findings.append({"severity": "warning", "code": "bend_radius", "message": f"Bend radius {bend_radius:g} mm is below material-thickness screening value {thickness:g} mm."})
    elif process in {"laser", "waterjet", "laser_cut"}:
        z = float(bounds["z"])
        max_thickness = float(settings.get("max_thickness_mm", 12.0))
        if z > max_thickness:
            findings.append({"severity": "error", "code": "sheet_thickness", "message": f"Part thickness {z:g} mm exceeds configured 2D cutting limit {max_thickness:g} mm."})
    else:
        findings.append({"severity": "warning", "code": "unknown_process", "message": f"No deterministic DFM rules are registered for process {process!r}."})
    return {
        "object_id": object_id,
        "process": process,
        "geometry_fingerprint": _hash({"params": obj.get("params"), "features": obj.get("features"), "material": obj.get("material")}),
        "findings": findings,
        "ok": not any(row["severity"] == "error" for row in findings),
        "limitations": ["Screening rules are not manufacturing certification; supplier/tool-specific limits remain authoritative."],
    }


def fabrication_manifest(graph: EngineeringGraphStore, *, name: str = "Fabrication Package", processes: dict[str, str] | None = None) -> dict[str, Any]:
    processes = processes or {}
    snapshot = graph.snapshot()
    objects = deepcopy(core.PROJECT.get("objects", []))
    object_ids = [str(row.get("id")) for row in objects if row.get("id")]
    dfm = []
    for object_id in object_ids:
        obj = _raw_object(object_id)
        if obj.get("kind") == "component":
            continue
        process = processes.get(object_id) or (obj.get("semantic") or {}).get("manufacturing_process") or "cnc"
        dfm.append(manufacturing_screening(object_id, str(process)))
    software = []
    for obj in objects:
        if isinstance(obj.get("code"), dict):
            software.append({"object_id": obj.get("id"), "entrypoint": obj["code"].get("entrypoint"), "platform": obj["code"].get("platform"), "software_sha256": _hash(obj["code"].get("files") or {})})
    current_simulations = [deepcopy(row) for row in core.PROJECT.get("simulations", []) if not row.get("stale")]
    manifest = {
        "id": _id("fab"),
        "name": name,
        "created_at": _now(),
        "status": "ready" if all(row["ok"] for row in dfm) else "blocked",
        "branch": snapshot.active_branch,
        "project_revision": snapshot.project_revision,
        "engineering_graph_revision": snapshot.graph_revision,
        "object_ids": object_ids,
        "geometry_exports": [{"object_id": oid, "formats": ["STEP", "STL"], "filename_stem": f"{oid}"} for oid in object_ids if _raw_object(oid).get("kind") != "component"],
        "bom": deepcopy(core.PROJECT.get("bom", [])),
        "connections": deepcopy(core.PROJECT.get("connections", [])),
        "software": software,
        "analysis_evidence_ids": [row.id for row in snapshot.evidence if not row.stale],
        "current_simulations": current_simulations,
        "dfm": dfm,
        "requirements": deepcopy(core.PROJECT.get("requirements", [])),
        "profile": product_profile(),
        "reproducibility": {"project_fingerprint": _hash(core.PROJECT), "graph_schema": snapshot.schema_version},
    }
    with core.LOCK:
        core.PROJECT.setdefault("fabrication_packages", []).append(deepcopy(manifest))
        core.push_history("generate fabrication package", "forgecad", name)
        core.persist()
    return manifest


def record_inspection(request: InspectionRequest, graph: EngineeringGraphStore) -> dict[str, Any]:
    obj = _raw_object(request.object_id)
    expected = request.expected
    if expected is None:
        metrics = core.object_metrics(obj)
        aliases = {
            "mass_kg": metrics.get("mass_kg"),
            "volume_mm3": metrics.get("volume_mm3"),
            "x_mm": (metrics.get("bounds_mm") or {}).get("x"),
            "y_mm": (metrics.get("bounds_mm") or {}).get("y"),
            "z_mm": (metrics.get("bounds_mm") or {}).get("z"),
        }
        expected = aliases.get(request.metric)
    deviation = None if expected is None else float(request.observed) - float(expected)
    passed = None
    if deviation is not None and request.tolerance is not None:
        passed = abs(deviation) <= float(request.tolerance)
    status = "unknown" if passed is None else ("pass" if passed else "fail")
    record = {
        "id": _id("inspection"),
        "name": f"{obj.get('name') or request.object_id} {request.metric}",
        "object_id": request.object_id,
        "metric": request.metric,
        "observed": request.observed,
        "expected": expected,
        "deviation": deviation,
        "unit": request.unit,
        "tolerance": request.tolerance,
        "status": status,
        "source": request.source,
        "instrument": request.instrument,
        "confidence": request.confidence,
        "metadata": request.metadata,
        "observed_at": _now(),
    }
    with core.LOCK:
        core.PROJECT.setdefault("inspections", []).append(deepcopy(record))
        core.push_history("record physical inspection", "human", record["name"])
        core.persist()
    evidence = EngineeringEvidence(
        id=f"evidence:{record['id']}",
        kind="physical_inspection",
        subject_node_ids=[f"cad:{request.object_id}"],
        value=request.observed,
        unit=request.unit,
        status=status,
        method=request.source,
        source_ids=[request.instrument] if request.instrument else [],
        confidence=request.confidence,
        metadata=record,
    )
    graph.add_evidence(evidence)
    if status == "fail":
        graph.mark_dirty([f"cad:{request.object_id}"], reason=f"physical inspection deviation: {request.metric}")
    return {"record": record, "evidence": evidence.model_dump(mode="json")}


def design_software_fingerprint(object_id: str) -> str | None:
    obj = _raw_object(object_id)
    code = obj.get("code")
    if not isinstance(code, dict):
        return None
    return _hash(code.get("files") or {})


def record_deployment(request: DeploymentRequest) -> dict[str, Any]:
    obj = _raw_object(request.object_id)
    design_sha = design_software_fingerprint(request.object_id)
    observed_sha = request.software_sha256
    software_match = None if design_sha is None or observed_sha is None else design_sha == observed_sha
    record = {
        "id": _id("deployment"),
        "name": f"{obj.get('name') or request.object_id} deployment",
        "object_id": request.object_id,
        "device_id": request.device_id,
        "firmware_version": request.firmware_version,
        "design_software_sha256": design_sha,
        "software_sha256": observed_sha,
        "software_match": software_match,
        "configuration": deepcopy(request.configuration),
        "telemetry": deepcopy(request.telemetry),
        "source": request.source,
        "confidence": request.confidence,
        "observed_at": _now(),
        "status": "in_sync" if software_match is True else ("drift" if software_match is False else "unknown"),
    }
    with core.LOCK:
        deployments = core.PROJECT.setdefault("deployments", [])
        if request.device_id:
            deployments[:] = [row for row in deployments if not (row.get("device_id") == request.device_id and row.get("object_id") == request.object_id)]
        deployments.append(deepcopy(record))
        core.push_history("record device deployment", "device", record["name"])
        core.persist()
    return record


def hardware_drift(object_id: str | None = None) -> dict[str, Any]:
    deployments = deepcopy(core.PROJECT.get("deployments", []))
    if object_id is not None:
        deployments = [row for row in deployments if str(row.get("object_id")) == object_id]
    findings: list[dict[str, Any]] = []
    for row in deployments:
        oid = str(row.get("object_id") or "")
        try:
            design_sha = design_software_fingerprint(oid)
        except KeyError:
            findings.append({"severity": "error", "code": "deployment_orphan", "deployment_id": row.get("id"), "message": f"Deployment references missing CAD object {oid}."})
            continue
        observed_sha = row.get("software_sha256")
        if design_sha and observed_sha and design_sha != observed_sha:
            findings.append({"severity": "error", "code": "software_drift", "object_id": oid, "device_id": row.get("device_id"), "design_sha256": design_sha, "observed_sha256": observed_sha, "message": "Deployed software does not match the code versioned with this design."})
        expected_config = (_raw_object(oid).get("semantic") or {}).get("deployment_config") if oid else None
        if isinstance(expected_config, dict):
            observed = row.get("configuration") or {}
            for key, expected in expected_config.items():
                if observed.get(key) != expected:
                    findings.append({"severity": "warning", "code": "configuration_drift", "object_id": oid, "key": key, "expected": expected, "observed": observed.get(key), "message": f"Deployed configuration {key!r} differs from design intent."})
    return {"ok": not any(row["severity"] == "error" for row in findings), "findings": findings, "count": len(findings), "deployments": deployments}


BUILTIN_SOLVER_ADAPTERS: dict[str, dict[str, Any]] = {
    "structural": {"id": "forgecad.structural.screening", "fidelity": "engineering", "engine": "CadQuery/SciPy", "domains": ["linear_static", "solid_fea"], "deterministic": True},
    "modal": {"id": "forgecad.modal.screening", "fidelity": "screening", "engine": "ForgeCAD rigid/modal", "domains": ["modal", "rigid_body"], "deterministic": True},
    "thermal": {"id": "forgecad.thermal.lumped", "fidelity": "screening", "engine": "ForgeCAD thermal network", "domains": ["steady_state_thermal"], "deterministic": True},
    "fluid": {"id": "forgecad.fluid.network", "fidelity": "screening", "engine": "ForgeCAD hydraulic network", "domains": ["incompressible_network"], "deterministic": True},
    "kinematics": {"id": "forgecad.kinematics.exact", "fidelity": "engineering", "engine": "OpenCascade", "domains": ["mechanism", "collision"], "deterministic": True},
    "tolerance": {"id": "forgecad.tolerance.stack", "fidelity": "engineering", "engine": "ForgeCAD tolerance stack", "domains": ["worst_case", "rss"], "deterministic": True},
    "external_fea": {"id": "external.fea", "fidelity": "high_fidelity", "engine": "adapter", "domains": ["nonlinear", "contact", "fatigue", "modal"], "deterministic": False, "requires_adapter": True},
    "external_cfd": {"id": "external.cfd", "fidelity": "high_fidelity", "engine": "adapter", "domains": ["cfd", "conjugate_heat_transfer"], "deterministic": False, "requires_adapter": True},
    "external_dynamics": {"id": "external.dynamics", "fidelity": "high_fidelity", "engine": "adapter", "domains": ["multibody_dynamics", "motor_load_curve"], "deterministic": False, "requires_adapter": True},
}


def solver_adapters() -> dict[str, Any]:
    return {"items": deepcopy(list(BUILTIN_SOLVER_ADAPTERS.values())), "count": len(BUILTIN_SOLVER_ADAPTERS)}


def solver_job_contract(request: SolverJobRequest, graph: EngineeringGraphStore) -> dict[str, Any]:
    snapshot = graph.snapshot()
    node_map = {row.id: row for row in snapshot.nodes}
    missing = [node_id for node_id in request.subject_node_ids if node_id not in node_map]
    if missing:
        raise KeyError(", ".join(missing))
    adapter = BUILTIN_SOLVER_ADAPTERS.get(request.kind)
    if adapter is None:
        raise ValueError(f"Unknown solver kind: {request.kind}")
    return {
        "schema": "forgecad-solver-job/1",
        "job_id": _id("solver-job"),
        "kind": request.kind,
        "adapter": deepcopy(adapter),
        "requested_fidelity": request.requested_fidelity,
        "engineering_graph_revision": snapshot.graph_revision,
        "project_revision": snapshot.project_revision,
        "subjects": [{"node_id": node_id, "fingerprint": node_map[node_id].fingerprint} for node_id in request.subject_node_ids],
        "settings": deepcopy(request.settings),
        "required_result_fields": ["status", "method", "solver_version", "input_fingerprints", "assumptions", "validity_limits", "metrics", "artifacts"],
        "provenance_required": True,
    }


def failure_diagnosis(graph: EngineeringGraphStore, requirement_id: str) -> dict[str, Any]:
    requirement_node = f"requirement:{requirement_id}"
    requirement = next((row for row in core.PROJECT.get("requirements", []) if str(row.get("id")) == requirement_id), None)
    if requirement is None:
        raise KeyError(requirement_id)
    value, source = _metric_value(str(requirement.get("metric") or ""))
    target = float(requirement.get("target", 0.0))
    op = str(requirement.get("op") or "<=")
    status = "unknown" if value is None else ("pass" if _cmp(value, op, target) else "fail")
    if status == "pass":
        return {"requirement_id": requirement_id, "status": "pass", "causes": [], "repairs": [], "message": "Requirement currently passes; no failure diagnosis is needed."}
    traces = graph.trace_to(requirement_node, {"cad_object", "catalog_component", "analysis", "interface", "software_workspace", "deployment", "inspection"})
    causes = []
    for hit in traces:
        node = hit["node"]
        depth = len(hit["path"])
        score = 100.0 / max(1, depth)
        if node.get("dirty"):
            score += 30.0
        if node.get("kind") in {"analysis", "inspection", "deployment"}:
            score += 10.0
        causes.append({"node_id": node["id"], "name": node["name"], "kind": node["kind"], "domain": node["domain"], "score": round(score, 3), "path": hit["path"], "dirty": node.get("dirty", False)})
    causes.sort(key=lambda row: (-row["score"], row["node_id"]))
    repairs = []
    for cause in causes[:8]:
        kind = cause["kind"]
        if kind == "catalog_component":
            repairs.append({"action": "component_substitution", "node_id": cause["node_id"], "reason": "Evaluate higher-margin compatible component candidates."})
        elif kind == "cad_object":
            repairs.append({"action": "branch_and_modify_geometry", "node_id": cause["node_id"], "reason": "Create a repair branch and change the implicated geometry/parameter."})
        elif kind == "analysis":
            repairs.append({"action": "rerun_analysis", "node_id": cause["node_id"], "reason": "Recompute analysis with current fingerprints and inspect margins."})
        elif kind == "software_workspace":
            repairs.append({"action": "inspect_control_software", "node_id": cause["node_id"], "reason": "Check software/configuration contribution and deployed-state drift."})
        elif kind in {"inspection", "deployment"}:
            repairs.append({"action": "reconcile_physical_state", "node_id": cause["node_id"], "reason": "Physical evidence differs from design assumptions; reconcile before redesign."})
    return {
        "requirement_id": requirement_id,
        "status": status,
        "metric": requirement.get("metric"),
        "value": value,
        "target": target,
        "op": op,
        "metric_source": source,
        "causes": causes[:20],
        "repairs": repairs,
        "limitations": ["Causal ranking follows explicit engineering-graph dependencies; it does not invent unrecorded physical causality."],
    }


def _branch_project(branch: str) -> dict[str, Any]:
    if branch == core.ACTIVE_DESIGN:
        return deepcopy(core.PROJECT)
    if branch not in core.BRANCHES:
        raise KeyError(branch)
    return deepcopy(core.BRANCHES[branch])


def semantic_branch_diff(source: str, target: str) -> dict[str, Any]:
    source_project = _branch_project(source)
    target_project = _branch_project(target)
    source_graph = build_engineering_graph(project_snapshot={"active_branch": source, "revision": f"{source}:{source_project.get('updated_at', '')}", "name": source_project.get("name"), "metrics": {}}, raw_project=source_project)
    target_graph = build_engineering_graph(project_snapshot={"active_branch": target, "revision": f"{target}:{target_project.get('updated_at', '')}", "name": target_project.get("name"), "metrics": {}}, raw_project=target_project)
    source_nodes = {row.id: row for row in source_graph.nodes}
    target_nodes = {row.id: row for row in target_graph.nodes}
    changes = []
    for node_id in sorted(set(source_nodes) | set(target_nodes)):
        if node_id not in source_nodes:
            changes.append({"node_id": node_id, "change": "added_in_target", "target": target_nodes[node_id].model_dump(mode="json")})
        elif node_id not in target_nodes:
            changes.append({"node_id": node_id, "change": "removed_in_target", "source": source_nodes[node_id].model_dump(mode="json")})
        elif source_nodes[node_id].fingerprint != target_nodes[node_id].fingerprint:
            changes.append({"node_id": node_id, "change": "modified", "source": source_nodes[node_id].model_dump(mode="json"), "target": target_nodes[node_id].model_dump(mode="json")})
    return {"source": source, "target": target, "source_revision": source_graph.graph_revision, "target_revision": target_graph.graph_revision, "changes": changes, "count": len(changes)}
