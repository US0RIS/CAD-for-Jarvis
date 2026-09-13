from __future__ import annotations

"""ForgeCAD 2.0 additive-manufacturing integration.

The first manufacturing resource is the user's Bambu Lab P2S.  ForgeCAD remains the
source of engineering truth; Bambu Studio is the slicer/print-preparation authority.
This module deliberately separates three concerns:

1. deterministic printability/build-volume screening in Forge Engine;
2. standards-based 3MF geometry exchange;
3. optional Bambu Studio CLI slicing when a complete local profile set is configured.

Direct printer control is intentionally not implemented here.  Bambu's LAN developer
interfaces are not a stable public API contract, so future LAN control must be explicit
opt-in and separately permissioned.
"""

from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterable
import xml.etree.ElementTree as ET
import zipfile


P2S_PROFILE: dict[str, Any] = {
    "id": "bambu-lab-p2s",
    "manufacturer": "Bambu Lab",
    "model": "P2S",
    "process": "fff",
    "build_volume_mm": [256.0, 256.0, 256.0],
    "default_nozzle_mm": 0.4,
    "supported_nozzles_mm": [0.2, 0.4, 0.6, 0.8],
    "max_nozzle_temperature_c": 300.0,
    "max_bed_temperature_c": 110.0,
    "source": "https://blog.bambulab.com/the-icon-redefined-meet-the-p2s-a-completely-reengineered-version-of-the-ultra-productive-p1-series/",
}

_POLYMER_HINTS = ("pla", "petg", "abs", "asa", "nylon", "pa", "pc", "tpu", "polymer", "plastic")
_DO_NOT_FABRICATE = {"purchased", "off_the_shelf", "reference", "do_not_fabricate", "assembly_only"}


def _semantic(obj: dict[str, Any]) -> dict[str, Any]:
    value = obj.get("semantic")
    return value if isinstance(value, dict) else {}


def _manufacturing_intent(obj: dict[str, Any]) -> str:
    semantic = _semantic(obj)
    value = semantic.get("manufacturing") or semantic.get("manufacturing_intent") or ""
    if isinstance(value, dict):
        value = value.get("process") or value.get("intent") or ""
    return str(value).strip().lower()


def is_fabricated_object(obj: dict[str, Any]) -> bool:
    """Return whether an object is a candidate fabricated part rather than purchased hardware."""
    if not obj.get("visible", True):
        return False
    if str(obj.get("kind") or "") == "component" or obj.get("component_ref"):
        return False
    intent = _manufacturing_intent(obj)
    if intent in _DO_NOT_FABRICATE:
        return False
    # Custom B-rep primitives, imported STEP and explicitly fabricated parts are all
    # manufacturing candidates.  Reference geometry can opt out through semantic intent.
    return str(obj.get("kind") or "") in {
        "box", "cylinder", "sphere", "sketch_extrude", "revolve", "step", "mounting_plate"
    } or "fabricated" in {str(x).lower() for x in _semantic(obj).get("tags", [])}


def fabricated_objects(project: dict[str, Any], object_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    selected = {str(x) for x in object_ids or []}
    rows = []
    for obj in project.get("objects") or []:
        if selected and str(obj.get("id")) not in selected:
            continue
        if is_fabricated_object(obj):
            rows.append(obj)
    return rows


def _fits_orthogonal(bounds: list[float], volume: list[float]) -> bool:
    """Fast necessary/sufficient check for axis-permutation fit, not arbitrary-angle nesting."""
    return all(a <= b + 1e-6 for a, b in zip(sorted(bounds), sorted(volume)))


def _material_screen(obj: dict[str, Any]) -> dict[str, Any]:
    material = str(obj.get("material") or "unknown").lower()
    printable = any(token in material for token in _POLYMER_HINTS)
    semantic = _semantic(obj)
    requested = semantic.get("print_material") or semantic.get("filament")
    if requested:
        printable = True
    return {
        "design_material": str(obj.get("material") or "unknown"),
        "direct_fdm_material_match": printable,
        "requested_filament": requested,
    }


def analyze_object(obj: dict[str, Any], build_shape: Callable[[dict[str, Any]], Any], *, printer: dict[str, Any] = P2S_PROFILE) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    try:
        shape = build_shape(obj)
        bb = shape.BoundingBox()
        bounds = [float(bb.xlen), float(bb.ylen), float(bb.zlen)]
        volume_mm3 = float(shape.Volume())
    except Exception as exc:
        return {
            "id": str(obj.get("id") or ""),
            "name": str(obj.get("name") or obj.get("id") or "Part"),
            "eligible": False,
            "fits_build_volume": False,
            "bounds_mm": None,
            "volume_mm3": None,
            "warnings": [{"code": "geometry_unavailable", "message": str(exc)}],
        }

    build_volume = [float(v) for v in printer["build_volume_mm"]]
    fits = _fits_orthogonal(bounds, build_volume)
    if not fits:
        warnings.append({
            "code": "exceeds_build_volume",
            "message": f"Part envelope {bounds[0]:.1f} × {bounds[1]:.1f} × {bounds[2]:.1f} mm does not fit the {printer['model']} build volume by axis permutation.",
        })
    if volume_mm3 <= 1e-9:
        warnings.append({"code": "zero_volume", "message": "Part has no printable solid volume."})

    material = _material_screen(obj)
    if not material["direct_fdm_material_match"]:
        warnings.append({
            "code": "material_substitution_required",
            "message": "The engineering material is not directly an FDM filament. Select an explicit print material and re-verify the design against its properties.",
        })

    semantic = _semantic(obj)
    min_wall = semantic.get("minimum_wall_mm") or semantic.get("wall_thickness_mm")
    wall_status = "declared" if isinstance(min_wall, (int, float)) else "unknown"
    if wall_status == "unknown":
        warnings.append({
            "code": "wall_thickness_unverified",
            "message": "Minimum wall thickness is not encoded as a manufacturing constraint; slicer/geometry validation is still required.",
        })

    return {
        "id": str(obj.get("id") or ""),
        "name": str(obj.get("name") or obj.get("id") or "Part"),
        "kind": str(obj.get("kind") or "custom"),
        "eligible": volume_mm3 > 1e-9,
        "fits_build_volume": bool(fits),
        "bounds_mm": [round(v, 4) for v in bounds],
        "volume_mm3": round(volume_mm3, 3),
        "material": material,
        "minimum_wall_mm": float(min_wall) if isinstance(min_wall, (int, float)) else None,
        "wall_thickness_status": wall_status,
        "requires_slicer_validation": True,
        "warnings": warnings,
    }


def discover_bambu_studio() -> str | None:
    override = os.environ.get("FORGECAD_BAMBU_STUDIO", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    for command in ("bambu-studio", "BambuStudio", "BambuStudio.exe"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    candidates.extend([
        Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"),
        Path("/usr/bin/bambu-studio"),
        Path("/usr/local/bin/bambu-studio"),
    ])
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if root:
                candidates.extend([
                    Path(root) / "Bambu Studio" / "bambu-studio.exe",
                    Path(root) / "BambuStudio" / "BambuStudio.exe",
                ])
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def configured_profiles() -> dict[str, Any]:
    machine = os.environ.get("FORGECAD_BAMBU_MACHINE_PROFILE", "").strip() or None
    process = os.environ.get("FORGECAD_BAMBU_PROCESS_PROFILE", "").strip() or None
    filaments = [x.strip() for x in os.environ.get("FORGECAD_BAMBU_FILAMENT_PROFILES", "").split(";") if x.strip()]
    def state(path: str | None) -> dict[str, Any]:
        return {"path": path, "exists": bool(path and Path(path).is_file())}
    return {
        "machine": state(machine),
        "process": state(process),
        "filaments": [state(path) for path in filaments],
        "complete": bool(machine and process and filaments and Path(machine).is_file() and Path(process).is_file() and all(Path(x).is_file() for x in filaments)),
    }


def p2s_status(project: dict[str, Any], build_shape: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    parts = [analyze_object(obj, build_shape) for obj in fabricated_objects(project)]
    executable = discover_bambu_studio()
    profiles = configured_profiles()
    return {
        "resource": deepcopy(P2S_PROFILE),
        "fabricated_part_count": len(parts),
        "parts": parts,
        "all_parts_fit_individually": bool(parts) and all(bool(row.get("fits_build_volume")) for row in parts),
        "packing_status": "requires_bambu_studio_arrange",
        "slicer": {
            "name": "Bambu Studio",
            "cli_available": bool(executable),
            "executable": executable,
            "profiles": profiles,
            "ready_for_headless_slice": bool(executable and profiles["complete"]),
            "command_reference": "https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage",
        },
        "lan_control": {
            "implemented": False,
            "policy": "future-explicit-opt-in",
            "note": "Direct LAN printer control is deferred because Bambu developer-mode MQTT/file-transfer interfaces are not a supported stable public API contract.",
        },
    }


def _safe_filename(value: str, default: str = "forgecad-print") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value.strip()).strip(".-")
    return cleaned or default


def geometry_3mf(project: dict[str, Any], tessellate: Callable[[dict[str, Any], float], dict[str, Any]], *, object_ids: Iterable[str] | None = None, tolerance_mm: float = 0.15) -> bytes:
    """Create a standards-based 3MF containing fabricated ForgeCAD bodies.

    This is deliberately geometry-first. Bambu-specific machine/process/filament
    metadata is added by Bambu Studio during the slicing stage rather than guessed by
    ForgeCAD.
    """
    objects = fabricated_objects(project, object_ids)
    if not objects:
        raise ValueError("No fabricated objects are available for 3MF export")

    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("", ns)
    model = ET.Element(f"{{{ns}}}model", {"unit": "millimeter", "xml:lang": "en-US"})
    ET.SubElement(model, f"{{{ns}}}metadata", {"name": "Application"}).text = "ForgeCAD 2.0.0"
    resources = ET.SubElement(model, f"{{{ns}}}resources")
    build = ET.SubElement(model, f"{{{ns}}}build")

    for index, obj in enumerate(objects, start=1):
        mesh = tessellate(obj, float(tolerance_mm))
        positions = mesh.get("positions") or []
        triangles = mesh.get("triangles") or []
        if not positions or not triangles:
            continue
        object_node = ET.SubElement(resources, f"{{{ns}}}object", {
            "id": str(index),
            "type": "model",
            "name": str(obj.get("name") or f"Part {index}"),
        })
        mesh_node = ET.SubElement(object_node, f"{{{ns}}}mesh")
        vertices = ET.SubElement(mesh_node, f"{{{ns}}}vertices")
        for x, y, z in positions:
            ET.SubElement(vertices, f"{{{ns}}}vertex", {"x": f"{float(x):.7g}", "y": f"{float(y):.7g}", "z": f"{float(z):.7g}"})
        tri_node = ET.SubElement(mesh_node, f"{{{ns}}}triangles")
        for a, b, c in triangles:
            ET.SubElement(tri_node, f"{{{ns}}}triangle", {"v1": str(int(a)), "v2": str(int(b)), "v3": str(int(c))})
        ET.SubElement(build, f"{{{ns}}}item", {"objectid": str(index)})

    if not list(resources):
        raise ValueError("Fabricated objects produced no tessellated geometry")

    model_xml = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    content_types = b'''<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'''
    rels = b'''<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'''
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_xml)
    return output.getvalue()


def build_bambu_cli_command(
    executable: str,
    input_3mf: str | Path,
    output_dir: str | Path,
    *,
    output_name: str = "forgecad-p2s-sliced.3mf",
    machine_profile: str | None = None,
    process_profile: str | None = None,
    filament_profiles: Iterable[str] | None = None,
    orient: bool = True,
    arrange: bool = True,
) -> list[str]:
    command = [str(executable), "--debug", "2", "--outputdir", str(output_dir)]
    if machine_profile or process_profile:
        command += ["--load-settings", f"{machine_profile or ''};{process_profile or ''}"]
    filaments = [str(x) for x in filament_profiles or [] if str(x)]
    if filaments:
        command += ["--load-filaments", ";".join(filaments)]
    if orient:
        command.append("--orient")
    if arrange:
        command += ["--arrange", "1"]
    command += ["--slice", "0", "--export-3mf", _safe_filename(output_name, "forgecad-p2s-sliced.3mf"), str(input_3mf)]
    return command


def slice_3mf_bytes(
    input_bytes: bytes,
    *,
    executable: str | None = None,
    machine_profile: str | None = None,
    process_profile: str | None = None,
    filament_profiles: Iterable[str] | None = None,
    timeout_seconds: int = 300,
) -> tuple[bytes, dict[str, Any]]:
    executable = executable or discover_bambu_studio()
    if not executable:
        raise RuntimeError("Bambu Studio CLI was not found. Install Bambu Studio or set FORGECAD_BAMBU_STUDIO.")

    configured = configured_profiles()
    machine_profile = machine_profile or configured["machine"]["path"]
    process_profile = process_profile or configured["process"]["path"]
    filament_profiles = list(filament_profiles or [row["path"] for row in configured["filaments"] if row.get("path")])
    if not machine_profile or not process_profile or not filament_profiles:
        raise RuntimeError("Headless slicing requires full P2S machine, process, and filament profiles. Configure them explicitly rather than guessing print settings.")
    required = [machine_profile, process_profile, *filament_profiles]
    missing = [path for path in required if not Path(path).is_file()]
    if missing:
        raise RuntimeError("Configured Bambu profile file(s) do not exist: " + ", ".join(missing))

    with tempfile.TemporaryDirectory(prefix="forgecad-p2s-") as tmp:
        root = Path(tmp)
        input_path = root / "forgecad-input.3mf"
        output_name = "forgecad-p2s-sliced.3mf"
        output_path = root / output_name
        input_path.write_bytes(input_bytes)
        command = build_bambu_cli_command(
            executable,
            input_path,
            root,
            output_name=output_name,
            machine_profile=machine_profile,
            process_profile=process_profile,
            filament_profiles=filament_profiles,
        )
        completed = subprocess.run(command, cwd=str(root), text=True, capture_output=True, timeout=max(30, int(timeout_seconds)), check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Bambu Studio slicing failed with exit code {completed.returncode}: {(completed.stderr or completed.stdout)[-2000:]}")
        if not output_path.is_file():
            raise RuntimeError("Bambu Studio returned without producing the requested sliced 3MF")
        data = output_path.read_bytes()
        return data, {
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "output_size_bytes": len(data),
        }
