from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .v110 import acceptance_design
from .v110 import analysis
from .v110 import assembly_validation
from .v110 import component_importers
from .v110 import component_registry as registry
from .v110 import core
from .v110 import project_bundle
from .v110 import software
from .v110 import system_validation


_STATUS_MAP = {
    "working": "working",
    "working_in_real_life": "working",
    "not_working": "not_working",
    "failed": "not_working",
    "untested": "unverified",
    "unknown": "unverified",
    "unverified": "unverified",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_status(value: Any) -> str:
    return _STATUS_MAP.get(str(value or "unverified").lower(), "unverified")


def _component_key_specs(component: dict[str, Any]) -> list[dict[str, str]]:
    specs = component.get("specs") or {}
    candidates = [
        ("Voltage", specs.get("voltage_v") or specs.get("output_v")),
        ("Current", specs.get("max_current_a") or specs.get("rated_current_a")),
        ("Force", specs.get("force_n")),
        ("Torque", specs.get("torque_nm") or specs.get("holding_torque_nm")),
        ("Airflow", specs.get("airflow_cfm")),
        ("Bore", specs.get("bore_mm")),
        ("Mass", component.get("mass_g")),
    ]
    units = {"Voltage": " V", "Current": " A", "Force": " N", "Torque": " N·m", "Airflow": " CFM", "Bore": " mm", "Mass": " g"}
    rows = [{"label": label, "value": f"{value:g}{units[label]}" if isinstance(value, (int, float)) else f"{value}{units[label]}"} for label, value in candidates if value is not None]
    if not rows:
        dims = component.get("dimensions_mm") or []
        if len(dims) == 3:
            rows.append({"label": "Envelope", "value": " × ".join(f"{float(v):g}" for v in dims) + " mm"})
    return rows[:3]


def _ui_component(component: dict[str, Any], *, added_refs: set[str] | None = None) -> dict[str, Any]:
    procurement = component.get("procurement") or {}
    cost = procurement.get("unit_cost_usd")
    trust = int(component.get("trust_score") or 0)
    feasible = bool(component.get("feasible", True))
    fidelity = str((component.get("geometry") or {}).get("fidelity") or "unknown")
    return {
        "id": str(component["id"]),
        "manufacturer": str(component.get("manufacturer") or "Unknown"),
        "model": str(component.get("model") or component.get("name") or component["id"]),
        "category": str(component.get("category") or "custom"),
        "key_specs": _component_key_specs(component),
        "price": ({"amount": float(cost), "currency": "USD", "supplier": str(procurement.get("supplier") or component.get("manufacturer") or "Supplier")} if cost is not None else None),
        "fit_score": max(0, min(100, int((100 if feasible else 45) - float(component.get("constraint_penalty") or 0) * 10 + trust * 0.03))),
        "fit_reason": "Meets stated constraints with frozen engineering metadata." if feasible else "; ".join(component.get("constraint_failures") or ["One or more constraints are not satisfied."]),
        "unknown_required_fields": list(component.get("constraint_failures") or []),
        "geometry_fidelity": fidelity,
        "trust_score": trust,
        "added": str(component["id"]) in (added_refs or set()),
    }


class EngineeringProject:
    """Adapter exposing the validated v1.1 engineering model through the v2 desktop API.

    `v110.core` is authoritative.  The React/Three.js desktop is a client of this state;
    all human, AI and Jarvis mutations go through the same typed `core.execute` path.
    """

    def __init__(self) -> None:
        self._seed_acceptance_workspace_if_new()

    def _seed_acceptance_workspace_if_new(self) -> None:
        if core.STATE_PATH.exists():
            return
        project = core.upgrade_project(acceptance_design.build_project())
        with core.LOCK:
            core.PROJECT.clear()
            core.PROJECT.update(project)
            core.BRANCHES.clear()
            core.DESIGNS.clear()
            core.HISTORY.clear()
            core.REDO.clear()
            core.ACTIVE_DESIGN = "baseline"
            core.BRANCHES["baseline"] = deepcopy(core.PROJECT)
            core.DESIGNS["baseline"] = {
                "name": "baseline", "parent": None, "status": "working", "note": "Deterministic v1.1 acceptance assembly",
                "physical_verified": True, "created_at": _now(), "updated_at": _now(),
            }
            # Preserve the multi-design workflow immediately on first launch.  These are full
            # canonical snapshots, not UI-only labels.
            core.BRANCHES["solenoid-swap"] = deepcopy(core.PROJECT)
            core.DESIGNS["solenoid-swap"] = {
                "name": "solenoid-swap", "parent": "baseline", "status": "not_working", "note": "Example failed actuator experiment",
                "physical_verified": False, "created_at": _now(), "updated_at": _now(),
            }
            core.BRANCHES["pi-control-v2"] = deepcopy(core.PROJECT)
            core.DESIGNS["pi-control-v2"] = {
                "name": "pi-control-v2", "parent": "baseline", "status": "unverified", "note": "Example controller/code experiment",
                "physical_verified": False, "created_at": _now(), "updated_at": _now(),
            }
            core.HISTORY.append(deepcopy(core.PROJECT))
            core.PROJECT.setdefault("ledger", []).append({"at": _now(), "actor": "forgecad", "action": "seed_acceptance", "reason": "Full v1.1 engineering acceptance workspace", "design": "baseline"})
            core.persist()

    @property
    def active_branch(self) -> str:
        return core.ACTIVE_DESIGN

    def _object_mass_g(self, obj: dict[str, Any]) -> float:
        snap = obj.get("component_snapshot") or {}
        if snap.get("mass_g") is not None:
            return float(snap["mass_g"])
        try:
            return float(core.object_metrics(obj)["mass_kg"]) * 1000.0
        except Exception:
            return 0.0

    def snapshot(self) -> dict[str, Any]:
        branches = []
        for name, meta in core.DESIGNS.items():
            branch_state = core.PROJECT if name == core.ACTIVE_DESIGN else core.BRANCHES.get(name, {})
            commit_count = sum(1 for row in branch_state.get("ledger", []) if row.get("design") == name)
            status = _safe_status(meta.get("status"))
            physical = bool(meta.get("physical_verified"))
            branches.append({
                "name": name,
                "head_commit": f"design-{abs(hash((name, branch_state.get('updated_at', '')))) & 0xFFFFFFF:07x}",
                "parent_branch": meta.get("parent"),
                "status": status,
                "physical_verified": physical,
                "protected": physical or status == "working",
                "commit_count": max(1, commit_count),
                "active": name == core.ACTIVE_DESIGN,
            })
        parts = []
        for obj in core.PROJECT.get("objects", []):
            snap = obj.get("component_snapshot") or {}
            material_id = obj.get("material")
            material = core.MATERIALS.get(material_id, {}).get("name") or snap.get("material") or str(material_id or "—")
            parts.append({
                "id": str(obj["id"]),
                "name": str(obj.get("name") or obj["id"]),
                "role": str((obj.get("semantic") or {}).get("role") or snap.get("category") or obj.get("kind") or "part"),
                "mass_g": round(self._object_mass_g(obj), 2),
                "material": str(material),
                "programmable_workspace_id": str(obj["id"]) if isinstance(obj.get("code"), dict) else None,
                "component_ref": obj.get("component_ref"),
                "geometry_fidelity": (snap.get("geometry") or {}).get("fidelity") or (obj.get("semantic") or {}).get("geometry_fidelity") or "exact_brep",
            })
        history = []
        for row in core.PROJECT.get("ledger", [])[-80:]:
            history.append({
                "time": str(row.get("at") or _now()),
                "actor": str(row.get("actor") or "human"),
                "message": str(row.get("reason") or row.get("action") or "engineering change"),
                "branch": str(row.get("design") or core.ACTIVE_DESIGN),
            })
        return {
            "name": str(core.PROJECT.get("name") or "ForgeCAD Project"),
            "revision": str(len(core.PROJECT.get("ledger", [])) + 1),
            "active_branch": core.ACTIVE_DESIGN,
            "branches": branches,
            "parts": parts,
            "history": history,
            "selected_part_id": next((p["id"] for p in parts if p.get("programmable_workspace_id")), parts[0]["id"] if parts else None),
            "bom": deepcopy(core.PROJECT.get("bom", [])),
            "connections": deepcopy(core.PROJECT.get("connections", [])),
            "requirements": deepcopy(core.PROJECT.get("requirements", [])),
            "metrics": core.project_metrics(),
        }

    def scene_manifest(self) -> dict[str, Any]:
        meshes = []
        for obj in core.PROJECT.get("objects", []):
            if not obj.get("visible", True):
                continue
            try:
                mesh = core.tessellate(obj, tolerance=0.65)
            except Exception as exc:
                mesh = {"id": obj["id"], "positions": [], "triangles": [], "color": "#8aa0b6", "error": str(exc)}
            pos = (obj.get("transform") or {}).get("position", [0, 0, 0])
            length = max(sum(float(v) ** 2 for v in pos) ** 0.5, 1.0)
            explode = [float(v) / length for v in pos]
            geometry_status = physical_components.component_geometry_status(obj) if obj.get("kind") == "component" else {"geometry_source": "forgecad_brep", "geometry_fidelity": "exact_brep", "fallback": False}
            meshes.append({
                "id": str(obj["id"]), "name": str(obj.get("name") or obj["id"]),
                "semantic_role": str((obj.get("semantic") or {}).get("role") or obj.get("kind") or "part"),
                "mesh": mesh,
                "explode_vector": explode,
                "base_transform": deepcopy(obj.get("transform") or {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}),
                "programmable_workspace_id": str(obj["id"]) if isinstance(obj.get("code"), dict) else None,
                "geometry_source": geometry_status.get("geometry_source"),
                "geometry_fidelity": geometry_status.get("geometry_fidelity"),
                "geometry_fallback": bool(geometry_status.get("fallback")),
            })
        return {"revision": str(len(core.PROJECT.get("ledger", [])) + 1), "branch": core.ACTIVE_DESIGN, "parts": meshes, "authoritative": True}

    def search_components(self, query: str = "", *, category: str | None = None, constraints: dict[str, Any] | None = None, limit: int = 30) -> list[dict[str, Any]]:
        result = registry.search_components(query, category, constraints or {}, limit=limit, include_infeasible=True)
        added_refs = {str(o.get("component_ref")) for o in core.PROJECT.get("objects", []) if o.get("component_ref")}
        return [_ui_component(row, added_refs=added_refs) for row in result["results"]]

    def component(self, component_id: str) -> dict[str, Any]:
        added_refs = {str(o.get("component_ref")) for o in core.PROJECT.get("objects", []) if o.get("component_ref")}
        return _ui_component(registry.component_by_id(component_id), added_refs=added_refs)

    def registry_stats(self) -> dict[str, Any]:
        return registry.registry_stats()

    def add_component(self, component_id: str) -> dict[str, Any]:
        core.execute("add_component", {"component_id": component_id}, actor="human", reason=f"Add real component {component_id}")
        return self.component(component_id)

    def activate_branch(self, branch_name: str) -> dict[str, Any]:
        core.switch_branch(branch_name)
        return self.snapshot()

    def create_branch(self, name: str, reason: str = "") -> dict[str, Any]:
        core.create_branch(name, reason=reason)
        return self.snapshot()

    def compare_branch(self, name: str) -> dict[str, Any]:
        return core.compare_branch(name)

    def set_branch_status(self, name: str, status: str, note: str = "", physical_verified: bool = False) -> dict[str, Any]:
        return core.set_design_status(name, status, note, physical_verified)

    def undo(self) -> bool:
        return core.undo()

    def redo(self) -> bool:
        return core.redo()

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        obj = core.object_by_id(workspace_id)
        ws = software.workspace_for_object(core.PROJECT, workspace_id)
        if not ws:
            raise KeyError(workspace_id)
        summary = software.summarize_workspace(ws, include_contents=False)
        return {
            "id": workspace_id,
            "device_part_id": workspace_id,
            "target": str(obj.get("name") or workspace_id),
            "runtime": str(ws.get("platform") or "embedded"),
            "files": [item["path"] for item in summary["files"]],
        }

    def read_file(self, workspace_id: str, file_path: str) -> dict[str, str]:
        return software.read_file(core.PROJECT, workspace_id, file_path)

    def write_file(self, workspace_id: str, file_path: str, content: str) -> dict[str, str]:
        core.execute("code_write", {"id": workspace_id, "path": file_path, "content": content}, actor="human", reason=f"Edit embedded code {file_path}")
        return software.read_file(core.PROJECT, workspace_id, file_path)

    def execute(self, op: str, args: dict[str, Any] | None = None, *, actor: str = "human", reason: str = "") -> dict[str, Any]:
        result = core.execute(op, args or {}, actor=actor, reason=reason or op)
        return {"operation": result, "project": self.snapshot()}

    def validation(self) -> dict[str, Any]:
        system = system_validation.validate_system(core.PROJECT)
        try:
            assembly = assembly_validation.validate_assembly(core.PROJECT, core.build_shape, min_clearance_mm=1.0)
        except Exception as exc:
            assembly = {"ok": False, "counts": {"error": 0, "warning": 1, "info": 0}, "risks": [{"severity": "warning", "code": "assembly_check_unavailable", "message": str(exc)}]}
        risks = list(system.get("risks", [])) + list(assembly.get("risks", []))
        counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
        result = {**system, "ok": counts["error"] == 0, "counts": counts, "risks": risks, "assembly": assembly}
        result["requirements"] = core.requirement_checks()
        result["metrics"] = core.project_metrics()
        return result

    def run_simulation(self, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        obj = None
        if selected_object_id:
            try:
                obj = core.object_by_id(selected_object_id)
            except KeyError:
                pass
        if obj is None:
            obj = next((o for o in core.PROJECT.get("objects", []) if o.get("kind") != "component"), core.PROJECT["objects"][0])
        force = float(payload.get("force_n", 100.0))
        thermal_w = float(payload.get("heat_w", 10.0))
        result = {
            "object_id": obj["id"],
            "structural": analysis.linear_fea(obj, force_n=force),
            "modal": analysis.modal_analysis(obj),
            "thermal": analysis.thermal_analysis(obj, heat_w=thermal_w),
            "manufacturing": analysis.manufacturing_review(obj, str(payload.get("process", "cnc"))),
            "system": self.validation(),
        }
        core.record_simulation("engineering_screen", str(obj["id"]), payload, result)
        return result

    def run_campaign(self, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        obj = None
        if selected_object_id:
            try:
                candidate = core.object_by_id(selected_object_id)
                if candidate.get("kind") != "component":
                    obj = candidate
            except KeyError:
                pass
        if obj is None:
            obj = next(o for o in core.PROJECT.get("objects", []) if o.get("kind") != "component")
        params = obj.get("params") or {}
        variable = "z" if "z" in params else "thickness" if "thickness" in params else next(iter(params))
        start = float(params[variable])
        result = analysis.optimize_part(
            obj,
            [{"name": variable, "min": max(0.5, start * 0.65), "max": start * 1.45}],
            objective="mass",
            force_n=float(payload.get("force_n", 100.0)),
            deflection_max_mm=float(payload.get("deflection_max_mm", 1.0)),
            yield_fos_min=float(payload.get("yield_fos_min", 1.5)),
            max_evals=int(payload.get("max_evals", 20)),
        )
        best = result.get("best") or {}
        if best.get("values"):
            core.create_branch("optimized-variant", reason="Autonomous engineering campaign")
            updated = deepcopy(obj.get("params") or {})
            updated.update(best["values"])
            core.execute("update", {"id": obj["id"], "params": updated}, actor="forge-agent", reason="Apply best feasible optimization candidate")
        return {"optimization": result, "validation": self.validation(), "project": self.snapshot()}

    def deploy_workspace(self, workspace_id: str) -> dict[str, Any]:
        check = software.validate_workspace(core.PROJECT, workspace_id)
        obj = core.object_by_id(workspace_id)
        ws = software.workspace_for_object(core.PROJECT, workspace_id) or {}
        return {
            "ok": bool(check.get("ok")), "validation": check, "target": obj.get("name"),
            "platform": ws.get("platform"), "entrypoint": ws.get("entrypoint"),
            "note": "Workspace validated and packaged with the design. Hardware flashing remains an explicit user-authorized action.",
        }

    def export_bundle(self) -> bytes:
        return project_bundle.export_bundle_bytes(core.PROJECT)

    def import_bundle(self, data: bytes) -> dict[str, Any]:
        restored = project_bundle.import_bundle_bytes(data)
        project = core.upgrade_project(restored["project"])
        with core.LOCK:
            core.PROJECT.clear()
            core.PROJECT.update(project)
            core.BRANCHES[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
            core.HISTORY.clear()
            core.HISTORY.append(deepcopy(core.PROJECT))
            core.REDO.clear()
            core.persist()
        return {**restored, "project": self.snapshot()}

    def import_step_part(self, filename: str, data: bytes) -> dict[str, Any]:
        with core.LOCK:
            core.ensure_mutable("human", f"Import STEP {filename}")
            obj = core.import_step_bytes(filename, data)
        return {"object": obj, "project": self.snapshot()}

    def import_step_component(self, filename: str, data: bytes, *, manufacturer: str, model: str, category: str = "custom") -> dict[str, Any]:
        return component_importers.import_step_component(filename, data, manufacturer=manufacturer, model=model, category=category)

    def apply_demo_change(self, text: str) -> dict[str, Any]:
        core.create_branch("solenoid-swap", reason=text)
        core.execute("add_note", {"text": text}, actor="forge-agent", reason="Safe deterministic demo edit on child branch")
        return {"branch": core.ACTIVE_DESIGN, "project": self.snapshot()}

    def apply_agent_plan(self, plan: dict[str, Any], text: str) -> dict[str, Any]:
        # A working/physically-verified branch auto-forks on the first mutation through
        # core.execute.  Every subsequent command therefore lands on the same child branch.
        applied = []
        for command in plan.get("commands", []):
            op = str(command.get("op") or "")
            args = command.get("args") or {}
            result = core.execute(op, args, actor="forge-agent", reason=text)
            applied.append({"op": op, "ok": bool(result.get("ok"))})
        return {"branch": core.ACTIVE_DESIGN, "applied": applied, "project": self.snapshot()}


PROJECT = EngineeringProject()
