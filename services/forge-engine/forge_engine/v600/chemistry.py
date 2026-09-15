from __future__ import annotations

"""Canonical chemistry studies backed by the real Cantera solver.

ForgeCAD owns chemistry model identity, operating inputs, physical-object scope and
solver provenance. Cantera owns thermochemistry/kinetics calculations. Solver outputs
are analysis evidence; they never rewrite CAD/material truth or become physical test
results. Unsupported mechanisms, modes or unavailable solvers fail closed.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200.physical_evidence import design_fingerprint
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore
from .external_solvers import require_solver


_MECHANISM_NAME = re.compile(r"^[A-Za-z0-9_.-]+\.ya?ml$")


class ChemistryStudyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    object_id: str = Field(min_length=1, max_length=256)
    solver_id: Literal["cantera"] = "cantera"
    mechanism: str = Field(default="gri30.yaml", min_length=1, max_length=128)
    phase: str | None = Field(default=None, max_length=128)
    mode: Literal["equilibrium", "batch_constant_volume"] = "equilibrium"
    temperature_k: float = Field(gt=0.0, le=10000.0)
    pressure_pa: float = Field(gt=0.0, le=1.0e9)
    composition: dict[str, float] = Field(min_length=1, max_length=256)
    equilibrium_basis: Literal["TP", "HP", "UV", "SV"] = "HP"
    duration_s: float | None = Field(default=None, gt=0.0, le=1.0e7)
    volume_m3: float = Field(default=0.001, gt=0.0, le=1.0e6)
    energy_enabled: bool = True
    assumptions: list[str] = Field(default_factory=list, max_length=32)
    note: str = Field(default="", max_length=4000)


def _sha(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _study(study_id: str) -> dict[str, Any]:
    row = next((item for item in core.PROJECT.get("chemistry_studies") or [] if str(item.get("id")) == study_id), None)
    if row is None:
        raise KeyError(study_id)
    return row


def _validate_composition(composition: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_name, raw_value in composition.items():
        name = str(raw_name).strip()
        value = float(raw_value)
        if not name:
            raise ValueError("Chemistry composition contains an empty species name")
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"Chemistry composition for {name!r} must be finite and non-negative")
        if value > 0.0:
            normalized[name] = value
    if not normalized:
        raise ValueError("Chemistry composition must contain at least one positive species amount")
    return normalized


def _mechanism_provenance(ct: Any, mechanism: str) -> dict[str, Any]:
    if not _MECHANISM_NAME.fullmatch(mechanism):
        raise ValueError(
            "ForgeCAD 6.0 chemistry accepts packaged Cantera YAML mechanism names only; import of arbitrary mechanism paths is not yet release-validated"
        )
    matches: list[Path] = []
    for raw_root in ct.get_data_directories():
        try:
            candidate = (Path(str(raw_root)) / mechanism).resolve()
            root = Path(str(raw_root)).resolve()
            if root not in candidate.parents and candidate != root:
                continue
            if candidate.is_file():
                matches.append(candidate)
        except Exception:
            continue
    if not matches:
        # Let Cantera produce its detailed lookup error, but do not invent a source hash.
        return {
            "mechanism": mechanism,
            "source_kind": "cantera_search_path_unresolved",
            "sha256": None,
            "bytes": None,
        }
    data = matches[0].read_bytes()
    return {
        "mechanism": mechanism,
        "source_kind": "packaged_cantera_data",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "filename": matches[0].name,
    }


def _solution(ct: Any, study: dict[str, Any]) -> Any:
    mechanism = str(study["mechanism"])
    phase = study.get("phase")
    provenance = _mechanism_provenance(ct, mechanism)
    try:
        gas = ct.Solution(mechanism, str(phase)) if phase else ct.Solution(mechanism)
    except Exception as exc:
        raise ValueError(f"Cantera could not load chemistry mechanism {mechanism!r}: {exc}") from exc
    composition = _validate_composition(deepcopy(study["composition"]))
    try:
        gas.TPX = float(study["temperature_k"]), float(study["pressure_pa"]), composition
    except Exception as exc:
        raise ValueError(f"Cantera rejected the requested chemistry state/composition: {exc}") from exc
    return gas, provenance


def _state(gas: Any) -> dict[str, Any]:
    mole = {
        str(name): float(value)
        for name, value in zip(gas.species_names, gas.X)
        if float(value) > 1.0e-12
    }
    mass = {
        str(name): float(value)
        for name, value in zip(gas.species_names, gas.Y)
        if float(value) > 1.0e-12
    }
    return {
        "temperature_k": float(gas.T),
        "pressure_pa": float(gas.P),
        "density_kg_m3": float(gas.density),
        "enthalpy_mass_j_kg": float(gas.enthalpy_mass),
        "internal_energy_mass_j_kg": float(gas.int_energy_mass),
        "mole_fractions": mole,
        "mass_fractions": mass,
    }


def _largest_species_changes(initial: dict[str, Any], final: dict[str, Any], limit: int = 16) -> list[dict[str, Any]]:
    before = initial.get("mole_fractions") or {}
    after = final.get("mole_fractions") or {}
    species = set(before) | set(after)
    rows = [
        {
            "species": name,
            "initial_mole_fraction": float(before.get(name, 0.0)),
            "final_mole_fraction": float(after.get(name, 0.0)),
            "delta_mole_fraction": float(after.get(name, 0.0)) - float(before.get(name, 0.0)),
        }
        for name in species
    ]
    rows.sort(key=lambda row: abs(float(row["delta_mole_fraction"])), reverse=True)
    return rows[:limit]


def create_chemistry_study(request: ChemistryStudyRequest) -> dict[str, Any]:
    require_solver(request.solver_id)
    core.object_by_id(request.object_id)
    composition = _validate_composition(request.composition)
    if request.mode == "batch_constant_volume" and request.duration_s is None:
        raise ValueError("batch_constant_volume chemistry requires duration_s")
    if request.mode == "equilibrium" and request.duration_s is not None:
        raise ValueError("equilibrium chemistry does not use duration_s")
    # Validate mechanism availability now so the canonical contract cannot claim a
    # mechanism that this runtime cannot actually resolve.
    import cantera as ct

    provenance = _mechanism_provenance(ct, request.mechanism)
    try:
        ct.Solution(request.mechanism, request.phase) if request.phase else ct.Solution(request.mechanism)
    except Exception as exc:
        raise ValueError(f"Cantera could not load chemistry mechanism {request.mechanism!r}: {exc}") from exc

    with core.LOCK:
        core.ensure_mutable("human", "6.0 chemistry study contract")
        row = {
            "id": core.uid(),
            "kind": "chemistry_study",
            "name": request.name.strip(),
            "object_id": request.object_id,
            "branch": core.ACTIVE_DESIGN,
            "design_fingerprint": design_fingerprint(),
            "solver_id": request.solver_id,
            "solver_version": str(ct.__version__),
            "mechanism": request.mechanism,
            "mechanism_provenance": provenance,
            "phase": request.phase,
            "mode": request.mode,
            "temperature_k": float(request.temperature_k),
            "pressure_pa": float(request.pressure_pa),
            "composition": composition,
            "equilibrium_basis": request.equilibrium_basis,
            "duration_s": request.duration_s,
            "volume_m3": float(request.volume_m3),
            "energy_enabled": bool(request.energy_enabled),
            "assumptions": list(request.assumptions),
            "note": request.note,
            "physical_validation": False,
        }
        row["definition_sha256"] = _sha({
            key: value
            for key, value in row.items()
            if key not in {"id", "branch", "design_fingerprint", "physical_validation"}
        })
        core.PROJECT.setdefault("chemistry_studies", []).append(deepcopy(row))
        core.push_history("v6 chemistry study", "human", f"created Cantera chemistry study {row['id']}")
        core.persist()
    return deepcopy(row)


def run_chemistry_study(study_id: str, graph: EngineeringGraphStore) -> dict[str, Any]:
    study = deepcopy(_study(study_id))
    if core.ACTIVE_DESIGN != str(study.get("branch")):
        raise ValueError("Chemistry study must run on the branch where its canonical contract was created")
    current_fingerprint = design_fingerprint()
    if current_fingerprint != str(study.get("design_fingerprint") or ""):
        raise ValueError("Chemistry study contract is stale because the physical design fingerprint changed")
    solver = require_solver(str(study["solver_id"]))
    graph.node(f"cad:{study['object_id']}")

    import cantera as ct

    gas, provenance = _solution(ct, study)
    initial = _state(gas)
    mode = str(study["mode"])
    if mode == "equilibrium":
        basis = str(study["equilibrium_basis"])
        try:
            gas.equilibrate(basis)
        except Exception as exc:
            raise ValueError(f"Cantera equilibrium solve failed: {exc}") from exc
        final_gas = gas
        solver_method = f"Cantera equilibrium({basis})"
    elif mode == "batch_constant_volume":
        duration_s = float(study["duration_s"])
        energy = "on" if bool(study.get("energy_enabled", True)) else "off"
        try:
            reactor = ct.IdealGasReactor(gas, energy=energy, volume=float(study["volume_m3"]))
            network = ct.ReactorNet([reactor])
            network.advance(duration_s)
            final_gas = getattr(reactor, "phase", None) or reactor.thermo
        except Exception as exc:
            raise ValueError(f"Cantera batch reactor solve failed: {exc}") from exc
        solver_method = "Cantera IdealGasReactor/ReactorNet"
    else:
        raise ValueError(f"Unsupported chemistry mode: {mode}")

    final = _state(final_gas)
    result = {
        "id": core.uid(),
        "kind": "chemistry_run",
        "study_id": study_id,
        "object_id": study["object_id"],
        "branch": core.ACTIVE_DESIGN,
        "design_fingerprint": current_fingerprint,
        "study_definition_sha256": study["definition_sha256"],
        "solver": {
            "id": "cantera",
            "name": solver["name"],
            "version": str(ct.__version__),
            "method": solver_method,
            "solver_grade": "external_engineering_analysis",
        },
        "mechanism_provenance": provenance,
        "mode": mode,
        "initial_state": initial,
        "final_state": final,
        "largest_species_changes": _largest_species_changes(initial, final),
        "temperature_change_k": float(final["temperature_k"]) - float(initial["temperature_k"]),
        "pressure_change_pa": float(final["pressure_pa"]) - float(initial["pressure_pa"]),
        "physical_validation": False,
        "limitations": [
            "Result validity is conditional on the chosen chemical mechanism and thermodynamic/kinetic model.",
            "A zero-dimensional/equilibrium model does not resolve spatial mixing, turbulence, transport limits, wall heat transfer, multiphase behavior or structural response.",
            "A chemistry solve is prediction evidence and is not proof of safe real-world reaction behavior.",
        ],
    }
    evidence = EngineeringEvidence(
        id=f"chemistry:{result['id']}",
        kind="chemistry_analysis",
        subject_node_ids=[f"cad:{study['object_id']}"],
        value={
            "final_temperature_k": final["temperature_k"],
            "final_pressure_pa": final["pressure_pa"],
            "largest_species_changes": result["largest_species_changes"],
        },
        status="predicted_external_solver",
        method=solver_method,
        source_ids=[str(result["id"]), str(study_id), str(provenance.get("sha256") or "")],
        assumptions=[*list(study.get("assumptions") or []), *result["limitations"]],
        confidence=0.85,
        metadata={
            "study_definition_sha256": study["definition_sha256"],
            "design_fingerprint": current_fingerprint,
            "solver_version": str(ct.__version__),
            "mechanism_provenance": provenance,
            "mode": mode,
        },
    )
    graph_row = graph.add_evidence(evidence).model_dump(mode="json")
    result["graph_evidence_id"] = graph_row["id"]
    with core.LOCK:
        core.PROJECT.setdefault("chemistry_runs", []).append(deepcopy(result))
        core.push_history("v6 chemistry run", "forgecad", f"solved chemistry study {study_id} with Cantera {ct.__version__}")
        core.persist()
    return {"study": study, "run": deepcopy(result), "graph_evidence": graph_row}


def chemistry_studies() -> list[dict[str, Any]]:
    return deepcopy(core.PROJECT.get("chemistry_studies") or [])


def chemistry_runs(study_id: str | None = None) -> list[dict[str, Any]]:
    rows = deepcopy(core.PROJECT.get("chemistry_runs") or [])
    if study_id is not None:
        rows = [row for row in rows if str(row.get("study_id")) == study_id]
    return rows
