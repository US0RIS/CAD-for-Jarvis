from __future__ import annotations

"""Canonical electrical graph and schematic screening for ForgeCAD 2.0.

ForgeCAD already stores typed component interfaces and point-to-point connections. This
module turns that authoritative connection graph into a deterministic electrical
schematic/net model instead of asking the model to reason from loose prose.

It is intentionally a topology/power/signal screening layer, not SPICE or a PCB field
solver. Unknown electrical values stay unknown; conflicting source rails and modeled
overloads fail closed.
"""

from collections import defaultdict
from copy import deepcopy
import math
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from ..v110 import core, physical_components, system_validation


_INSTALLED = False
_ORIGINAL_EXECUTE: Callable[..., dict[str, Any]] | None = None

_POWER_OUTPUT = set(system_validation.POWER_OUTPUT_KINDS) | {"mains_source"}
_POWER_INPUT = set(system_validation.POWER_INPUT_KINDS) | {"mains_power_input"}
_SIGNAL = set(system_validation.SIGNAL_KINDS)
_ELECTRICAL = _POWER_OUTPUT | _POWER_INPUT | _SIGNAL | {
    "ground",
    "power_ground",
    "electrical_ground",
    "analog_input",
    "analog_output",
    "analog_io",
    "can",
    "usb",
}
_NET_CLASSES = {"power", "ground", "signal", "data", "mixed", "unknown"}


class NetLabelRequest(BaseModel):
    name: str
    net_class: str | None = None
    nominal_voltage_v: float | None = None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number(mapping: dict[str, Any] | None, *keys: str) -> float | None:
    source = mapping or {}
    for key in keys:
        if source.get(key) is not None:
            value = _finite(source.get(key))
            if value is not None:
                return value
    return None


def _objects(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(obj.get("id")): obj
        for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id")
    }


def _interface(obj: dict[str, Any], interface_id: str) -> dict[str, Any] | None:
    try:
        return physical_components.object_interface(obj, interface_id)
    except Exception:
        return None


def _interface_kind(interface: dict[str, Any] | None) -> str:
    return str((interface or {}).get("kind") or "").strip().lower()


def _is_electrical_interface(interface: dict[str, Any] | None) -> bool:
    kind = _interface_kind(interface)
    return kind in _ELECTRICAL or any(
        token in kind
        for token in ("electrical", "power", "digital", "analog", "pwm", "uart", "spi", "i2c", "usb", "can", "ground")
    )


def _endpoint_key(object_id: str, interface_id: str) -> str:
    return f"{object_id}::{interface_id}"


def _connection_records(project: dict[str, Any]) -> list[dict[str, Any]]:
    objects = _objects(project)
    records: list[dict[str, Any]] = []
    for connection in project.get("connections") or []:
        if not isinstance(connection, dict):
            continue
        a = connection.get("a") or {}
        b = connection.get("b") or {}
        a_obj = objects.get(str(a.get("object_id") or ""))
        b_obj = objects.get(str(b.get("object_id") or ""))
        a_if = _interface(a_obj, str(a.get("interface_id") or "")) if a_obj else None
        b_if = _interface(b_obj, str(b.get("interface_id") or "")) if b_obj else None
        connection_kind = str(connection.get("kind") or "").lower()
        electrical = (
            connection_kind in {"electrical", "power", "signal", "data"}
            or _is_electrical_interface(a_if)
            or _is_electrical_interface(b_if)
        )
        if electrical:
            records.append({
                "connection": connection,
                "a_obj": a_obj,
                "b_obj": b_obj,
                "a_if": a_if,
                "b_if": b_if,
            })
    return records


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, value: str) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: str) -> str:
        self.add(value)
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _component_specs(obj: dict[str, Any]) -> dict[str, Any]:
    definition = physical_components.component_definition(obj) or {}
    specs = definition.get("specs") or {}
    return specs if isinstance(specs, dict) else {}


def _endpoint_record(obj: dict[str, Any], interface: dict[str, Any]) -> dict[str, Any]:
    metadata = interface.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "object_id": str(obj.get("id") or ""),
        "object_name": str(obj.get("name") or obj.get("id") or "Component"),
        "component_ref": obj.get("component_ref"),
        "interface_id": str(interface.get("id") or ""),
        "kind": _interface_kind(interface),
        "direction": str(interface.get("gender") or "neutral").lower(),
        "required": bool(interface.get("required")),
        "metadata": deepcopy(metadata),
    }


def _source_voltage(endpoint: dict[str, Any], obj: dict[str, Any]) -> float | None:
    meta = endpoint.get("metadata") if isinstance(endpoint.get("metadata"), dict) else {}
    value = _number(meta, "voltage_v", "nominal_voltage_v", "output_v", "logic_voltage_v")
    if value is not None:
        return value
    specs = _component_specs(obj)
    return _number(specs, "output_v", "voltage_v", "nominal_voltage_v")


def _source_current_limit(endpoint: dict[str, Any], obj: dict[str, Any]) -> float | None:
    meta = endpoint.get("metadata") if isinstance(endpoint.get("metadata"), dict) else {}
    value = _number(meta, "max_current_a", "continuous_current_a", "rated_current_a", "peak_current_a")
    if value is not None:
        return value
    specs = _component_specs(obj)
    return _number(specs, "max_current_a", "continuous_current_a", "rated_current_a")


def _load_current(endpoint: dict[str, Any], obj: dict[str, Any], nominal_voltage_v: float | None) -> float | None:
    meta = endpoint.get("metadata") if isinstance(endpoint.get("metadata"), dict) else {}
    value = _number(meta, "current_a", "rated_current_a", "recommended_current_a", "typical_current_a")
    if value is not None:
        return value
    power = _number(meta, "typical_power_w", "input_power_w", "power_w")
    specs = _component_specs(obj)
    if value is None:
        value = _number(specs, "current_a", "rated_current_a", "recommended_current_a", "typical_current_a")
    if value is not None:
        return value
    if power is None:
        power = _number(specs, "input_power_w", "typical_power_w", "power_w")
    if power is not None and nominal_voltage_v not in (None, 0.0):
        return power / float(nominal_voltage_v)
    return None


def _is_source(endpoint: dict[str, Any]) -> bool:
    return endpoint.get("kind") in _POWER_OUTPUT or endpoint.get("direction") == "output"


def _is_sink(endpoint: dict[str, Any]) -> bool:
    return endpoint.get("kind") in _POWER_INPUT or endpoint.get("direction") == "input"


def _net_class(endpoints: list[dict[str, Any]], explicit: list[str]) -> str:
    explicit_values = [str(value).lower() for value in explicit if str(value).lower() in _NET_CLASSES]
    if explicit_values:
        return explicit_values[0] if len(set(explicit_values)) == 1 else "mixed"
    kinds = {str(row.get("kind") or "") for row in endpoints}
    if any("ground" in kind for kind in kinds):
        return "ground"
    if kinds & (_POWER_OUTPUT | _POWER_INPUT):
        return "power"
    if kinds & _SIGNAL:
        return "signal"
    return "unknown"


def compile_schematic(project: dict[str, Any]) -> dict[str, Any]:
    records = _connection_records(project)
    uf = _UnionFind()
    endpoint_objects: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    labelled_groups: dict[str, list[str]] = defaultdict(list)

    for record in records:
        connection = record["connection"]
        if not record["a_obj"] or not record["b_obj"] or not record["a_if"] or not record["b_if"]:
            continue
        a_key = _endpoint_key(str(record["a_obj"]["id"]), str(record["a_if"]["id"]))
        b_key = _endpoint_key(str(record["b_obj"]["id"]), str(record["b_if"]["id"]))
        endpoint_objects[a_key] = (record["a_obj"], record["a_if"])
        endpoint_objects[b_key] = (record["b_obj"], record["b_if"])
        uf.union(a_key, b_key)
        label = str(connection.get("net_name") or "").strip()
        if label:
            labelled_groups[label].extend([a_key, b_key])

    # Identically named nets are electrically identical even when the connection graph
    # contains several fan-out edges that do not share a literal endpoint.
    for keys in labelled_groups.values():
        if not keys:
            continue
        anchor = keys[0]
        for key in keys[1:]:
            uf.union(anchor, key)

    groups: dict[str, set[str]] = defaultdict(set)
    for key in endpoint_objects:
        groups[uf.find(key)].add(key)

    endpoint_to_connections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        connection = record["connection"]
        for side in ("a", "b"):
            data = connection.get(side) or {}
            key = _endpoint_key(str(data.get("object_id") or ""), str(data.get("interface_id") or ""))
            endpoint_to_connections[key].append(connection)

    objects = _objects(project)
    nets: list[dict[str, Any]] = []
    for index, keys in enumerate(sorted(groups.values(), key=lambda group: sorted(group)), start=1):
        endpoints = [_endpoint_record(*endpoint_objects[key]) for key in sorted(keys)]
        connections: dict[str, dict[str, Any]] = {}
        explicit_names: list[str] = []
        explicit_classes: list[str] = []
        explicit_voltages: list[float] = []
        for key in keys:
            for connection in endpoint_to_connections.get(key, []):
                cid = str(connection.get("id") or "")
                if cid:
                    connections[cid] = connection
                name = str(connection.get("net_name") or "").strip()
                if name:
                    explicit_names.append(name)
                net_class = str(connection.get("net_class") or "").strip()
                if net_class:
                    explicit_classes.append(net_class)
                voltage = _finite(connection.get("nominal_voltage_v"))
                if voltage is not None:
                    explicit_voltages.append(voltage)

        unique_names = sorted(set(explicit_names))
        name = unique_names[0] if len(unique_names) == 1 else f"NET-{index:03d}"
        classification = _net_class(endpoints, explicit_classes)

        source_voltages: list[float] = []
        source_limits: list[float] = []
        sources: list[dict[str, Any]] = []
        sinks: list[dict[str, Any]] = []
        for endpoint in endpoints:
            obj = objects.get(str(endpoint["object_id"]))
            if obj is None:
                continue
            if _is_source(endpoint):
                sources.append(endpoint)
                voltage = _source_voltage(endpoint, obj)
                if voltage is not None:
                    source_voltages.append(voltage)
                limit = _source_current_limit(endpoint, obj)
                if limit is not None:
                    source_limits.append(limit)
            if _is_sink(endpoint):
                sinks.append(endpoint)

        nominal_voltage = (
            explicit_voltages[0]
            if explicit_voltages and max(explicit_voltages) - min(explicit_voltages) <= 1e-9
            else (source_voltages[0] if source_voltages else None)
        )
        known_loads: list[float] = []
        unknown_load_count = 0
        for endpoint in sinks:
            obj = objects.get(str(endpoint["object_id"]))
            current = _load_current(endpoint, obj or {}, nominal_voltage)
            if current is None:
                unknown_load_count += 1
            else:
                known_loads.append(current)

        nets.append({
            "id": f"net-{index:03d}",
            "name": name,
            "explicit_names": unique_names,
            "class": classification,
            "nominal_voltage_v": nominal_voltage,
            "source_voltage_candidates_v": sorted(set(round(value, 9) for value in source_voltages + explicit_voltages)),
            "known_load_current_a": sum(known_loads) if known_loads else 0.0,
            "unknown_load_count": unknown_load_count,
            "source_current_limits_a": source_limits,
            "sources": deepcopy(sources),
            "sinks": deepcopy(sinks),
            "members": endpoints,
            "connection_ids": sorted(connections),
        })

    connected_endpoints = {
        _endpoint_key(str(member["object_id"]), str(member["interface_id"]))
        for net in nets
        for member in net["members"]
    }
    unconnected_required: list[dict[str, Any]] = []
    for obj in project.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        for interface in obj.get("interfaces") or []:
            if not isinstance(interface, dict) or not interface.get("required") or not _is_electrical_interface(interface):
                continue
            key = _endpoint_key(str(obj.get("id") or ""), str(interface.get("id") or ""))
            if key not in connected_endpoints:
                unconnected_required.append(_endpoint_record(obj, interface))

    return {
        "solver": "ForgeCAD ElectricalGraph",
        "solver_version": "2.0.0",
        "authoritative_source": "canonical component interfaces + project connections",
        "net_count": len(nets),
        "nets": nets,
        "unconnected_required": unconnected_required,
    }


def _risk_key(risk: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(risk.get("code") or ""),
        str(risk.get("connection_id") or risk.get("object_id") or risk.get("net_id") or ""),
        str(risk.get("message") or ""),
    )


def analyze_electrical(project: dict[str, Any]) -> dict[str, Any]:
    schematic = compile_schematic(project)
    risks: list[dict[str, Any]] = []

    # Preserve the mature v1.1 deterministic checks but expose them as part of the v2
    # electrical analysis surface rather than hiding them inside whole-system validation.
    electrical_connection_ids = {
        str(record["connection"].get("id") or "")
        for record in _connection_records(project)
    }
    risks.extend(
        risk
        for risk in system_validation.validate_connections(project)
        if str(risk.get("connection_id") or "") in electrical_connection_ids
    )
    risks.extend(system_validation.validate_power(project))
    risks.extend(system_validation.validate_signals(project))

    for endpoint in schematic["unconnected_required"]:
        kind = str(endpoint.get("kind") or "")
        direction = str(endpoint.get("direction") or "")
        external_boundary = kind == "mains_power_input"
        severity = "warning" if external_boundary or direction == "output" else "error"
        risks.append({
            "severity": severity,
            "code": "unconnected_required_electrical_interface",
            "object_id": endpoint["object_id"],
            "interface_id": endpoint["interface_id"],
            "message": (
                f"{endpoint['object_name']} required interface {endpoint['interface_id']} is not connected"
                + ("; model the external mains boundary before release verification." if external_boundary else ".")
            ),
        })

    for net in schematic["nets"]:
        candidates = [float(value) for value in net.get("source_voltage_candidates_v") or []]
        if len(candidates) > 1:
            low, high = min(candidates), max(candidates)
            if high - low > max(0.25, 0.05 * max(abs(high), abs(low), 1.0)):
                risks.append({
                    "severity": "error",
                    "code": "conflicting_power_sources",
                    "net_id": net["id"],
                    "message": f"Net {net['name']} has conflicting modeled source voltages: {', '.join(f'{value:g} V' for value in candidates)}.",
                })

        if net.get("class") == "power":
            power_sources = [
                endpoint
                for endpoint in net.get("sources") or []
                if endpoint.get("kind") in _POWER_OUTPUT
            ]
            if len(power_sources) > 1:
                risks.append({
                    "severity": "error",
                    "code": "parallel_power_sources_unverified",
                    "net_id": net["id"],
                    "message": f"Net {net['name']} has {len(power_sources)} modeled power outputs tied together; parallel-source sharing is not verified.",
                })

            limits = [float(value) for value in net.get("source_current_limits_a") or [] if _finite(value) is not None]
            known_load = float(net.get("known_load_current_a") or 0.0)
            if len(power_sources) == 1 and limits and known_load > limits[0] + 1e-9:
                risks.append({
                    "severity": "error",
                    "code": "net_overcurrent",
                    "net_id": net["id"],
                    "message": f"Net {net['name']} has at least {known_load:g} A modeled load against a {limits[0]:g} A source rating.",
                })

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for risk in risks:
        if isinstance(risk, dict):
            deduped[_risk_key(risk)] = risk
    ordered = sorted(
        deduped.values(),
        key=lambda risk: (
            {"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3),
            str(risk.get("code") or ""),
            str(risk.get("message") or ""),
        ),
    )
    counts = {
        level: sum(1 for risk in ordered if str(risk.get("severity") or "") == level)
        for level in ("error", "warning", "info")
    }
    return {
        **schematic,
        "ok": counts["error"] == 0,
        "counts": counts,
        "risks": ordered,
        "coverage": {
            "nets_with_known_voltage": sum(1 for net in schematic["nets"] if net.get("nominal_voltage_v") is not None),
            "power_nets": sum(1 for net in schematic["nets"] if net.get("class") == "power"),
            "signal_nets": sum(1 for net in schematic["nets"] if net.get("class") in {"signal", "data"}),
            "unknown_loads": sum(int(net.get("unknown_load_count") or 0) for net in schematic["nets"]),
        },
        "limitations": [
            "No SPICE analog/transient/AC/noise simulation.",
            "No PCB trace impedance, signal-integrity, EMI/EMC, creepage/clearance, or thermal-current-density solver.",
            "Parallel power supplies are treated as unverified and fail closed.",
            "Current budget uses frozen component/interface metadata only; unknown loads remain unknown.",
            "This is engineering-iteration evidence, not certification.",
        ],
        "physical_verification": False,
    }


def _find_net_connections(project: dict[str, Any], connection_id: str) -> list[dict[str, Any]]:
    schematic = compile_schematic(project)
    target = next(
        (net for net in schematic["nets"] if connection_id in (net.get("connection_ids") or [])),
        None,
    )
    if target is None:
        raise KeyError(connection_id)
    ids = set(str(value) for value in target.get("connection_ids") or [])
    return [
        connection
        for connection in project.get("connections") or []
        if isinstance(connection, dict) and str(connection.get("id") or "") in ids
    ]


def label_net(
    project: dict[str, Any],
    connection_id: str,
    name: str,
    *,
    net_class: str | None = None,
    nominal_voltage_v: float | None = None,
) -> dict[str, Any]:
    label = str(name or "").strip()
    if not label:
        raise ValueError("Electrical net name cannot be empty")
    classification = str(net_class or "").strip().lower() or None
    if classification is not None and classification not in _NET_CLASSES:
        raise ValueError("net_class must be power, ground, signal, data, mixed, or unknown")
    voltage = _finite(nominal_voltage_v) if nominal_voltage_v is not None else None
    if nominal_voltage_v is not None and voltage is None:
        raise ValueError("nominal_voltage_v must be finite")

    connections = _find_net_connections(project, connection_id)
    for connection in connections:
        connection["net_name"] = label
        if classification is not None:
            connection["net_class"] = classification
        if voltage is not None:
            connection["nominal_voltage_v"] = voltage
    return {
        "name": label,
        "net_class": classification,
        "nominal_voltage_v": voltage,
        "connection_ids": [str(connection.get("id") or "") for connection in connections],
    }


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    assert _ORIGINAL_EXECUTE is not None
    payload = deepcopy(args or {})

    if op == "label_electrical_net":
        connection_id = str(payload.get("connection_id") or "")
        if not connection_id:
            raise ValueError("label_electrical_net requires connection_id")
        with core.LOCK:
            core.ensure_mutable(actor, reason or "label electrical net")
            result = label_net(
                core.PROJECT,
                connection_id,
                str(payload.get("name") or ""),
                net_class=payload.get("net_class"),
                nominal_voltage_v=payload.get("nominal_voltage_v"),
            )
            core.mark_simulations_stale(None)
            core.push_history("label_electrical_net", actor, reason or f"Label electrical net {result['name']}")
            core.persist()
        return {
            "ok": True,
            "op": op,
            "electrical_net": result,
            "project": core.PROJECT,
            "active_design": core.ACTIVE_DESIGN,
        }

    if op == "connect_interfaces":
        metadata_requested = any(
            key in payload for key in ("net_name", "net_class", "nominal_voltage_v")
        )
        classification = str(payload.get("net_class") or "").strip().lower()
        if classification and classification not in _NET_CLASSES:
            raise ValueError("net_class must be power, ground, signal, data, mixed, or unknown")
        voltage = None
        if payload.get("nominal_voltage_v") is not None:
            voltage = _finite(payload.get("nominal_voltage_v"))
            if voltage is None:
                raise ValueError("nominal_voltage_v must be finite")

        before_ids = {
            str(connection.get("id") or "")
            for connection in core.PROJECT.get("connections") or []
            if isinstance(connection, dict)
        }
        result = _ORIGINAL_EXECUTE(op, payload, actor=actor, reason=reason)
        if metadata_requested:
            created = [
                connection
                for connection in core.PROJECT.get("connections") or []
                if isinstance(connection, dict) and str(connection.get("id") or "") not in before_ids
            ]
            if len(created) != 1:
                raise RuntimeError("connect_interfaces did not create exactly one electrical connection")
            connection = created[0]
            label = str(payload.get("net_name") or "").strip()
            if label:
                connection["net_name"] = label
            if classification:
                connection["net_class"] = classification
            if voltage is not None:
                connection["nominal_voltage_v"] = voltage
            core.persist()
        return result

    return _ORIGINAL_EXECUTE(op, payload, actor=actor, reason=reason)


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_EXECUTE
    if _INSTALLED:
        return

    _ORIGINAL_EXECUTE = core.execute
    core.execute = _execute
    app = legacy.app

    @app.get("/v2/electrical/schematic", dependencies=[Depends(legacy.require_session)])
    async def electrical_schematic() -> dict[str, Any]:
        return compile_schematic(core.PROJECT)

    @app.get("/v2/analysis/electrical", dependencies=[Depends(legacy.require_session)])
    async def electrical_analysis() -> dict[str, Any]:
        return analyze_electrical(core.PROJECT)

    @app.post("/v2/electrical/net/{connection_id}/label", dependencies=[Depends(legacy.require_session)])
    async def electrical_net_label(connection_id: str, request: NetLabelRequest) -> dict[str, Any]:
        try:
            result = core.execute(
                "label_electrical_net",
                {
                    "connection_id": connection_id,
                    "name": request.name,
                    "net_class": request.net_class,
                    "nominal_voltage_v": request.nominal_voltage_v,
                },
                actor="human",
                reason=f"Label electrical net {request.name}",
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "operation": result,
            "schematic": compile_schematic(core.PROJECT),
            "analysis": analyze_electrical(core.PROJECT),
        }

    _INSTALLED = True
