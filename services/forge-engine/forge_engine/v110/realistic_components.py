from __future__ import annotations

"""High-fidelity purchased-component geometry for ForgeCAD.

ForgeCAD may use manufacturer STEP geometry when a primary/authorized source
publishes it.  The exact files are cached locally on first use; detailed,
part-specific parametric geometry is the deterministic offline fallback.  This
module never labels a generic bounding box as a realistic purchased part.
"""

import argparse
import threading
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import cadquery as cq

from . import component_registry as registry


PACKAGE_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "manufacturer"
CACHE_ASSET_DIR = registry.ASSET_DIR / "manufacturer"
_DOWNLOAD_LOCK = threading.RLock()
_DOWNLOAD_FAILURES: set[str] = set()

# Manufacturer/authorized-distributor engineering files.  These URLs are also
# recorded in component provenance.  Release builds prefetch them so the normal
# installed experience does not depend on a network request.
CAD_ASSETS: dict[str, dict[str, Any]] = {
    "compute.raspberry_pi_5_8gb": {
        "filename": "raspberry-pi-5.step",
        "url": "https://pip-assets.raspberrypi.com/categories/892-raspberry-pi-5/documents/RP-010083-CA-1-rpi-5%203D%20STEP%20-%20No%20Graphics%20small%20file.zip",
        "archive": "zip",
        "source": "manufacturer",
        "fidelity": "official_step",
    },
    "power.pololu.d24v50f5": {
        "filename": "pololu-d24v50f5.step",
        "url": "https://www.pololu.com/file/0J1437/d24v50f5-step-down-voltage-regulator.step",
        "archive": None,
        "source": "manufacturer",
        "fidelity": "official_step",
    },
    "power.meanwell.lrs_75_12": {
        "filename": "meanwell-lrs-75.step",
        "url": "https://www.mouser.com/catalog/additional/MEAN_WELL_LRS_75_3D.zip",
        "archive": "zip",
        "source": "authorized_distributor",
        "fidelity": "verified_step",
    },
}

ACCEPTANCE_COMPONENTS = (
    "compute.raspberry_pi_5_8gb",
    "driver.adafruit.mosfet_5648",
    "solenoid.adafruit.412",
    "power.meanwell.lrs_75_12",
    "power.pololu.d24v50f5",
)


def _box(x: float, y: float, z: float, color: str, center=(0.0, 0.0, 0.0), radius: float = 0.0):
    cx, cy, cz = (float(v) for v in center)
    wp = cq.Workplane("XY").workplane(offset=cz - z / 2).box(x, y, z, centered=(True, True, False))
    if radius > 0:
        try:
            wp = wp.edges("|Z").fillet(min(radius, x / 2 - 0.01, y / 2 - 0.01))
        except Exception:
            pass
    return wp.val().translate((cx, cy, 0)), color


def _cyl(d: float, h: float, color: str, center=(0.0, 0.0, 0.0), axis: str = "z"):
    cx, cy, cz = (float(v) for v in center)
    half = float(h) / 2.0
    if axis == "x":
        shape = cq.Workplane("YZ").circle(d / 2).extrude(half, both=True).val()
    elif axis == "y":
        shape = cq.Workplane("XZ").circle(d / 2).extrude(half, both=True).val()
    else:
        shape = cq.Workplane("XY").circle(d / 2).extrude(half, both=True).val()
    return shape.translate((cx, cy, cz)), color


def _cut_round_holes(shape, points, diameter: float, depth: float = 8.0):
    result = shape
    for x, y in points:
        tool = cq.Workplane("XY").workplane(offset=-depth / 2).center(x, y).circle(diameter / 2).extrude(depth).val()
        result = result.cut(tool)
    return result


def _step_candidates(component_id: str) -> list[Path]:
    spec = CAD_ASSETS.get(component_id)
    if not spec:
        return []
    return [PACKAGE_ASSET_DIR / spec["filename"], CACHE_ASSET_DIR / spec["filename"]]


def _looks_like_step(path: Path) -> bool:
    try:
        if path.stat().st_size < 1000:
            return False
        with path.open("rb") as handle:
            head = handle.read(512).upper()
        return b"ISO-10303-21" in head or b"FILE_SCHEMA" in head
    except OSError:
        return False


def _extract_step(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith((".step", ".stp")) and not name.endswith("/")]
        if not members:
            raise RuntimeError(f"No STEP file found in {archive.name}")
        # Prefer the largest STEP member; vendor archives sometimes include tiny
        # ancillary/placeholder models alongside the actual assembly.
        member = max(members, key=lambda name: zf.getinfo(name).file_size)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def download_step(component_id: str, *, force: bool = False) -> Path:
    spec = CAD_ASSETS.get(component_id)
    if not spec:
        raise KeyError(component_id)
    destination = CACHE_ASSET_DIR / spec["filename"]
    if not force:
        for candidate in _step_candidates(component_id):
            if _looks_like_step(candidate):
                return candidate
    CACHE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        spec["url"],
        headers={"User-Agent": "ForgeCAD/2.1 (+https://github.com/US0RIS/CAD-for-Jarvis)"},
    )
    with tempfile.TemporaryDirectory(prefix="forgecad-cad-") as tmp:
        raw_path = Path(tmp) / ("asset.zip" if spec.get("archive") == "zip" else "asset.step")
        with urllib.request.urlopen(request, timeout=15) as response, raw_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if spec.get("archive") == "zip":
            _extract_step(raw_path, destination)
        else:
            shutil.copy2(raw_path, destination)
    if not _looks_like_step(destination):
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded geometry for {component_id} is not a STEP file")
    return destination


def resolve_step(component_id: str, *, allow_download: bool = False) -> Path | None:
    for candidate in _step_candidates(component_id):
        if _looks_like_step(candidate):
            return candidate
    if allow_download and component_id in CAD_ASSETS:
        with _DOWNLOAD_LOCK:
            if component_id in _DOWNLOAD_FAILURES:
                return None
            # Another geometry request may have populated the cache while this one waited.
            for candidate in _step_candidates(component_id):
                if _looks_like_step(candidate):
                    return candidate
            try:
                return download_step(component_id)
            except Exception:
                _DOWNLOAD_FAILURES.add(component_id)
                return None
    return None


def _center_shape(shape):
    bb = shape.BoundingBox()
    return shape.translate((-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -(bb.zmin + bb.zmax) / 2))


def _step_parts(component_id: str, path: Path):
    imported = cq.importers.importStep(str(path)).val()
    shape = _center_shape(imported)
    try:
        solids = list(shape.Solids())
    except Exception:
        solids = []
    if not solids:
        solids = [shape]
    # Preserve separate solids so the viewport reads as an assembly instead of a
    # single gray blob.  Colors are visual semantics only; geometry is untouched.
    palette = ["#aeb7c2", "#24292d", "#16813e", "#d5a52a", "#d9dde1", "#697077"]
    if component_id == "power.pololu.d24v50f5":
        palette = ["#1766a6", "#202428", "#c8cdd1", "#d5a52a", "#5e646a"]
    elif component_id == "compute.raspberry_pi_5_8gb":
        palette = ["#16813e", "#202428", "#b7bec5", "#d5a52a", "#e4ded1", "#555b61"]
    return [(solid, palette[index % len(palette)]) for index, solid in enumerate(solids)]


def _mosfet_5648_parts():
    # Adafruit 5648: 25.4 x 17.7 mm black PCB, two push-in output blocks,
    # JST-PH STEMMA input, AO3406 SOT-23 MOSFET, 1N4007 flyback diode,
    # status LEDs and 0.1-inch breakout pads.
    board, _ = _box(25.4, 17.7, 1.6, "#151719", radius=1.2)
    parts = [(board, "#151719")]
    # Two green push-in terminal blocks with front wire openings.
    for x in (-6.2, 6.2):
        block, _ = _box(10.2, 7.2, 6.4, "#35a94b", (x, 5.05, 3.95), 0.5)
        for hx in (-2.5, 2.5):
            hole = cq.Workplane("XZ").workplane(offset=2.0).center(x + hx, 3.8).circle(1.25).extrude(8, both=True).val()
            try:
                block = block.cut(hole)
            except Exception:
                pass
        parts.append((block, "#35a94b"))
    jst, _ = _box(8.6, 6.0, 5.8, "#ede8dc", (0, -5.6, 3.65), 0.8)
    cavity, _ = _box(5.6, 2.8, 3.0, "#222528", (0, -7.1, 4.1), 0.25)
    try:
        jst = jst.cut(cavity)
    except Exception:
        pass
    parts.append((jst, "#ede8dc"))
    parts += [
        _box(3.0, 1.6, 1.2, "#25282b", (-1.8, 0.0, 1.4), 0.15),
        _box(5.2, 2.5, 2.5, "#26292d", (4.1, -0.2, 2.05), 0.25),
        _cyl(2.1, 4.8, "#1e2023", (-5.0, -0.4, 2.4), "x"),
        _box(1.2, 0.8, 0.7, "#d7483d", (-8.8, -2.6, 1.15), 0.12),
        _box(1.2, 0.8, 0.7, "#58b95e", (-8.8, 0.0, 1.15), 0.12),
    ]
    # Gold breakout pads along the rear edge.
    pads = []
    for index in range(5):
        pad = cq.Workplane("XY").workplane(offset=0.82).center(-5.08 + index * 2.54, -7.15).circle(0.75).extrude(0.12).val()
        pads.append(pad)
    parts.append((cq.Compound.makeCompound(pads), "#d5a52a"))
    return parts


def _spring_parts(radius: float, z0: float, height: float):
    try:
        helix = cq.Wire.makeHelix(1.35, height, radius, center=cq.Vector(0, 0, z0), dir=cq.Vector(0, 0, 1))
        profile = cq.Workplane("XZ").workplane(offset=0).center(radius, z0).circle(0.38)
        return [(profile.sweep(helix, isFrenet=True).val(), "#b7bdc3")]
    except Exception:
        rings = []
        count = max(4, int(height / 1.35))
        for i in range(count):
            z = z0 + (height * i / max(1, count - 1))
            ring = cq.Workplane("XY").workplane(offset=z).circle(radius + 0.35).circle(radius - 0.35).extrude(0.35).val()
            rings.append(ring)
        return [(cq.Compound.makeCompound(rings), "#b7bdc3")]


def _solenoid_412_parts():
    # Product-specific push/pull solenoid: open steel frame, wound coil,
    # captive armature, return spring, mounting ears and wire leads.
    parts = []
    # Coil/spool centered in the steel U-frame.
    coil_outer = cq.Workplane("XY").circle(6.2).circle(3.1).extrude(15.0 / 2, both=True).val()
    parts.append((coil_outer, "#8b3e2f"))
    bobbin = cq.Workplane("XY").circle(6.7).circle(2.9).extrude(0.8).val().translate((0, 0, -7.9))
    bobbin2 = bobbin.translate((0, 0, 15.8))
    parts.extend([(bobbin, "#292c30"), (bobbin2, "#292c30")])
    # Open steel side straps and end plates instead of a solid cuboid.
    parts += [
        _box(2.2, 15.0, 22.0, "#9aa0a5", (-6.5, 0, -1.0), 0.4),
        _box(2.2, 15.0, 22.0, "#9aa0a5", (6.5, 0, -1.0), 0.4),
        _box(15.2, 15.0, 2.0, "#a5abb0", (0, 0, -11.0), 0.5),
        _box(15.2, 15.0, 2.0, "#a5abb0", (0, 0, 10.0), 0.5),
    ]
    # Mounting ears with bolt holes.
    ears, _ = _box(26.0, 6.0, 2.0, "#9aa0a5", (0, 0, -11.0), 1.0)
    ears = _cut_round_holes(ears, [(-10.0, 0.0), (10.0, 0.0)], 3.0, 6.0)
    parts.append((ears, "#9aa0a5"))
    parts.append(_cyl(3.8, 31.0, "#c1c6ca", (0, 0, 15.5), "z"))
    parts.extend(_spring_parts(3.2, 11.0, 10.5))
    # Red/black wire pigtails.
    parts.append(_cyl(1.0, 16.0, "#cf3d38", (6.4, -4.2, -18.0), "z"))
    parts.append(_cyl(1.0, 16.0, "#202326", (6.4, 4.2, -18.0), "z"))
    return parts


def _pololu_d24v50f5_parts():
    board, _ = _box(17.8, 20.3, 1.57, "#1766a6", radius=0.8)
    board = _cut_round_holes(board, [(-6.75, -8.0), (6.75, 8.0)], 2.18, 5.0)
    parts = [(board, "#1766a6")]
    # High-current buck layout: shielded inductor, IC/MOSFET packages,
    # electrolytic/polymer capacitors and 0.1-inch through-hole pads.
    parts += [
        _box(8.0, 8.0, 4.8, "#303438", (-1.8, 1.0, 3.18), 1.0),
        _box(4.4, 4.4, 1.1, "#24272a", (5.0, -2.4, 1.34), 0.35),
        _box(3.4, 5.0, 1.2, "#25282b", (-5.2, -3.0, 1.39), 0.25),
        _cyl(4.8, 5.7, "#32363a", (5.0, 4.8, 3.64), "z"),
        _cyl(4.2, 4.8, "#5b6065", (-5.2, 5.0, 3.19), "z"),
    ]
    pads = []
    for index in range(5):
        x = -5.08 + index * 2.54
        pad = cq.Workplane("XY").workplane(offset=0.8).center(x, -8.6).circle(0.78).extrude(0.15).val()
        pads.append(pad)
    parts.append((cq.Compound.makeCompound(pads), "#d5a52a"))
    return parts


def _terminal_block_parts(origin_x: float, origin_y: float, count: int = 7):
    parts = []
    spacing = 8.0
    start = -(count - 1) * spacing / 2
    for i in range(count):
        y = origin_y + start + i * spacing
        body, _ = _box(10.0, 7.5, 11.0, "#34383c", (origin_x, y, 2.5), 0.6)
        parts.append((body, "#34383c"))
        parts.append(_cyl(4.2, 1.2, "#b7bdc2", (origin_x, y, 8.5), "z"))
    return parts


def _meanwell_lrs75_parts():
    # Detailed offline representation of the open-frame LRS-75 enclosure and
    # major internal hardware.  The verified STEP is preferred when available.
    x, y, z = 99.0, 97.0, 30.0
    parts = []
    parts.append(_box(x, y, 1.2, "#aeb4b8", (0, 0, -14.4), 1.2))
    parts.append(_box(1.2, y, z, "#9fa6ab", (-49.0, 0, 0), 0.6))
    parts.append(_box(x, 1.2, z, "#9fa6ab", (0, -47.9, 0), 0.6))
    # Perforated top/side cage panels.  Slotting makes the part read as folded
    # sheet metal rather than a featureless rectangular enclosure.
    top, _ = _box(72.0, 87.0, 1.0, "#b7bdc1", (10.0, 0, 14.5), 0.8)
    for row in range(5):
        for col in range(6):
            slot, _ = _box(7.0, 2.2, 3.0, "#000000", (-14.0 + col * 11.0, -28.0 + row * 14.0, 14.5), 0.8)
            try:
                top = top.cut(slot)
            except Exception:
                pass
    parts.append((top, "#b7bdc1"))
    # PCB and visible power components under the mesh.
    parts.append(_box(88.0, 82.0, 1.6, "#247244", (2.0, 1.0, -10.0), 1.5))
    parts += [
        _cyl(24.0, 22.0, "#303438", (-14.0, 13.0, 1.0), "z"),
        _cyl(14.0, 18.0, "#2e3337", (20.0, 18.0, -1.0), "z"),
        _box(26.0, 20.0, 20.0, "#d0aa55", (-8.0, -17.0, -0.5), 1.2),
        _box(3.0, 35.0, 23.0, "#4e555b", (31.0, 2.0, 0.0), 0.4),
        _box(3.0, 29.0, 20.0, "#4e555b", (38.0, 4.0, -1.5), 0.4),
        _cyl(20.0, 8.0, "#c89b42", (-31.0, 25.0, -5.0), "z"),
    ]
    parts.extend(_terminal_block_parts(43.0, -7.0, 7))
    return parts


def _pi5_fallback_parts():
    # This path is used only if the official Raspberry Pi STEP is unavailable.
    board, _ = _box(85, 56, 1.6, "#16813e", radius=3)
    board = _cut_round_holes(board, [(-29, -24.5), (29, -24.5), (29, 24.5), (-29, 24.5)], 2.7, 5)
    parts = [(board, "#16813e")]
    parts += [
        _box(17.2, 17.2, 1.7, "#202327", (-8, -1, 1.65), 0.6),
        _box(12.5, 12.5, 1.4, "#24272b", (11, 2, 1.5), 0.4),
        _box(19, 17, 13.5, "#aeb5bc", (42.5, -16.5, 7.55), 0.8),
        _box(17, 14, 15.2, "#aab2ba", (43.5, 3.0, 8.4), 0.8),
        _box(17, 14, 15.2, "#aab2ba", (43.5, 19.0, 8.4), 0.8),
        _box(9.2, 8.0, 3.4, "#e0ddd3", (-31, -29.3, 2.5), 1.0),
        _box(15, 13, 1.7, "#9da5ac", (-35, 1, -1.65), 0.4),
        _box(51, 5.2, 2.5, "#17191b", (-5, 24.2, 2.05), 0.3),
    ]
    pins = []
    for col in range(20):
        for row in range(2):
            pin, _ = _box(0.65, 0.65, 8, "#d7a928", (-29.13 + col * 2.54, 22.93 + row * 2.54, 5.3))
            pins.append(pin)
    parts.append((cq.Compound.makeCompound(pins), "#d7a928"))
    return parts


PARAMETRIC_BUILDERS = {
    "compute.raspberry_pi_5_8gb": _pi5_fallback_parts,
    "driver.adafruit.mosfet_5648": _mosfet_5648_parts,
    "solenoid.adafruit.412": _solenoid_412_parts,
    "power.meanwell.lrs_75_12": _meanwell_lrs75_parts,
    "power.pololu.d24v50f5": _pololu_d24v50f5_parts,
}


def component_parts(obj: dict[str, Any], component: dict[str, Any] | None = None, *, allow_download: bool = False):
    component = component or {}
    component_id = str(obj.get("component_ref") or component.get("id") or "")
    if component_id in CAD_ASSETS:
        step_path = resolve_step(component_id, allow_download=allow_download)
        if step_path:
            try:
                return _step_parts(component_id, step_path)
            except Exception:
                pass
    builder = PARAMETRIC_BUILDERS.get(component_id)
    if builder:
        return builder()
    return None


def geometry_status(obj: dict[str, Any], component: dict[str, Any] | None = None) -> dict[str, Any]:
    component = component or {}
    component_id = str(obj.get("component_ref") or component.get("id") or "")
    step = resolve_step(component_id, allow_download=False)
    if step:
        spec = CAD_ASSETS[component_id]
        return {
            "component_id": component_id,
            "resolved": True,
            "geometry_source": spec["source"],
            "geometry_fidelity": spec["fidelity"],
            "asset": str(step),
            "fallback": False,
        }
    if component_id in PARAMETRIC_BUILDERS:
        return {
            "component_id": component_id,
            "resolved": True,
            "geometry_source": "forgecad_derived",
            "geometry_fidelity": "detailed_parametric",
            "asset": None,
            "fallback": component_id in CAD_ASSETS,
        }
    fidelity = str((component.get("geometry") or {}).get("fidelity") or "none")
    return {
        "component_id": component_id,
        "resolved": False,
        "geometry_source": "legacy_fallback",
        "geometry_fidelity": fidelity,
        "asset": None,
        "fallback": True,
    }


def prefetch_acceptance(*, force: bool = False, strict: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {}
    failures: list[str] = []
    for component_id in CAD_ASSETS:
        try:
            path = download_step(component_id, force=force)
            result[component_id] = {"ok": True, "path": str(path), "bytes": path.stat().st_size}
        except Exception as exc:
            result[component_id] = {"ok": False, "error": str(exc)}
            failures.append(component_id)
    if failures and strict:
        raise RuntimeError("Unable to prefetch high-fidelity CAD for: " + ", ".join(failures))
    return result


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefetch-acceptance", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-fallback", action="store_true")
    args = parser.parse_args()
    if args.prefetch_acceptance:
        import json
        print(json.dumps(prefetch_acceptance(force=args.force, strict=not args.allow_fallback), indent=2))


if __name__ == "__main__":
    _main()
