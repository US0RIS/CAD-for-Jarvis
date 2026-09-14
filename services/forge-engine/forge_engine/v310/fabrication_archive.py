from __future__ import annotations

"""Reproducible fabrication archives for ForgeCAD 3.1."""

from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
from typing import Any
import zipfile

import cadquery as cq

from ..v110 import core, project_bundle
from .engineering_graph import EngineeringGraphStore
from .integration_services import fabrication_manifest


MIME_TYPE = "application/vnd.forgecad.fabrication+zip"
FORMAT_ID = "forgecad-fabrication"
FORMAT_VERSION = 1


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe(value: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(value or "part"))
    return text.strip("-.") or "part"


def _bom_csv(rows: list[dict[str, Any]]) -> bytes:
    out = io.StringIO()
    fields = ["component_ref", "manufacturer", "model", "mpn", "description", "qty", "unit_cost_usd", "supplier", "supplier_sku", "procurement_url", "source_trust"]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def _assembly_readme(manifest: dict[str, Any]) -> str:
    lines = [
        f"# {manifest.get('name') or 'ForgeCAD Fabrication Package'}",
        "",
        f"Branch: `{manifest.get('branch')}`",
        f"Project revision: `{manifest.get('project_revision')}`",
        f"Engineering graph: `{manifest.get('engineering_graph_revision')}`",
        "",
        "This package is reproducible engineering output from ForgeCAD. Manufacturing and analysis results are screening/engineering evidence, not third-party certification.",
        "",
        "## Contents",
        "- `manifest.json` — exact package/revision identity and file hashes",
        "- `design.focad` — portable ForgeCAD source design/workspace",
        "- `bom.csv` — purchased-component bill of materials",
        "- `connections.json` — canonical interface/wiring/mechanical connection records",
        "- `requirements.json` — release/engineering requirements",
        "- `analysis/` — current simulation/evidence records",
        "- `parts/` — STEP and STL exports for fabricated parts",
        "- `software/` — code workspaces versioned with programmable components",
        "- `dfm.json` — deterministic manufacturing-screening findings",
        "",
        "## Build gate",
    ]
    blocked = [row for row in manifest.get("dfm", []) if not row.get("ok", False)]
    if blocked:
        lines.append(f"BLOCKED: {len(blocked)} part(s) have deterministic DFM errors. Resolve them before fabrication.")
    else:
        lines.append("No deterministic DFM errors were found by the configured screening rules.")
    return "\n".join(lines) + "\n"


def create_fabrication_archive(
    graph: EngineeringGraphStore,
    *,
    name: str = "Fabrication Package",
    processes: dict[str, str] | None = None,
    include_stl: bool = True,
    include_step: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    manifest = fabrication_manifest(graph, name=name, processes=processes)
    workspace = {
        "active": core.ACTIVE_DESIGN,
        "branches": deepcopy(core.BRANCHES),
        "designs": deepcopy(core.DESIGNS),
    }
    design_bytes = project_bundle.export_bundle_bytes(deepcopy(core.PROJECT), workspace)
    files: dict[str, bytes] = {
        "design.focad": design_bytes,
        "bom.csv": _bom_csv(deepcopy(core.PROJECT.get("bom", []))),
        "connections.json": json.dumps(core.PROJECT.get("connections", []), indent=2, sort_keys=True, default=str).encode("utf-8"),
        "requirements.json": json.dumps(core.PROJECT.get("requirements", []), indent=2, sort_keys=True, default=str).encode("utf-8"),
        "dfm.json": json.dumps(manifest.get("dfm", []), indent=2, sort_keys=True, default=str).encode("utf-8"),
        "analysis/simulations.json": json.dumps(manifest.get("current_simulations", []), indent=2, sort_keys=True, default=str).encode("utf-8"),
        "analysis/evidence.json": json.dumps([row.model_dump(mode="json") for row in graph.evidence(include_stale=False)], indent=2, sort_keys=True, default=str).encode("utf-8"),
        "README.md": _assembly_readme(manifest).encode("utf-8"),
    }

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for obj in deepcopy(core.PROJECT.get("objects", [])):
            if obj.get("kind") == "component" or not obj.get("id"):
                continue
            object_id = str(obj["id"])
            stem = f"{_safe(obj.get('name') or object_id)}--{_safe(object_id)}"
            try:
                shape = core.build_shape(obj)
            except Exception as exc:
                manifest.setdefault("export_errors", []).append({"object_id": object_id, "stage": "build_shape", "error": str(exc)})
                continue
            if include_step:
                path = root / f"{stem}.step"
                try:
                    cq.exporters.export(shape, str(path), exportType="STEP")
                    files[f"parts/{stem}.step"] = path.read_bytes()
                except Exception as exc:
                    manifest.setdefault("export_errors", []).append({"object_id": object_id, "stage": "STEP", "error": str(exc)})
            if include_stl:
                path = root / f"{stem}.stl"
                try:
                    cq.exporters.export(shape, str(path), exportType="STL", tolerance=0.05, angularTolerance=0.1)
                    files[f"parts/{stem}.stl"] = path.read_bytes()
                except Exception as exc:
                    manifest.setdefault("export_errors", []).append({"object_id": object_id, "stage": "STL", "error": str(exc)})

    for obj in deepcopy(core.PROJECT.get("objects", [])):
        code = obj.get("code")
        if not isinstance(code, dict):
            continue
        object_id = _safe(obj.get("id"))
        for relative, content in (code.get("files") or {}).items():
            safe_parts = [part for part in Path(str(relative)).parts if part not in {"..", "."}]
            if not safe_parts:
                continue
            files[f"software/{object_id}/" + "/".join(safe_parts)] = str(content).encode("utf-8")

    file_table = {
        path: {"sha256": _sha(data), "bytes": len(data)}
        for path, data in sorted(files.items())
    }
    final_manifest = {
        "format": FORMAT_ID,
        "format_version": FORMAT_VERSION,
        **manifest,
        "files": file_table,
        "archive_integrity": "Each member except manifest.json is SHA-256 listed in manifest.json",
    }
    files["manifest.json"] = json.dumps(final_manifest, indent=2, sort_keys=True, default=str).encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(path, data)
    archive_bytes = out.getvalue()
    return archive_bytes, {
        "manifest": final_manifest,
        "archive_sha256": _sha(archive_bytes),
        "bytes": len(archive_bytes),
        "filename": f"{_safe(name)}-{_safe(core.ACTIVE_DESIGN)}.forgefab.zip",
    }
