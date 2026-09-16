from __future__ import annotations

"""Authoritative purchased-component geometry for ForgeCAD 6.2.

The component registry has always carried identity/provenance, but older viewport paths
only knew about a handful of hard-coded STEP files. 6.2 makes exact vendor geometry a
data-driven first-class path:

* manufacturer or authorized-distributor CAD is preferred over every derived model;
* direct STEP/STP assets and product/download pages that publish STEP ZIPs are supported;
* downloaded geometry is validated, hashed, cached, and reusable across projects;
* exact B-rep solids remain separate render subparts instead of becoming one gray blob;
* if authoritative CAD cannot be resolved, ForgeCAD falls back explicitly and reports
  the lower fidelity rather than making a family approximation look authoritative.

Network resolution is intentionally limited to high-trust built-in sources. User-created
components can still register their own geometry assets through the existing registry.
"""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import threading
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
import urllib.request
import zipfile

import cadquery as cq

from ..v110 import component_registry as registry
from ..v110 import physical_components
from ..v110 import realistic_components


PACKAGE_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "authoritative"
CACHE_ASSET_DIR = registry.ASSET_DIR / "authoritative-v620"
_METADATA_NAME = "asset.json"
_DOWNLOAD_LOCK = threading.RLock()
_DOWNLOAD_FAILURES: set[str] = set()
_DOWNLOAD_QUEUED: set[str] = set()
_INSTALLED = False
_ORIGINAL_COMPONENT_PARTS = None
_ORIGINAL_GEOMETRY_STATUS = None


@dataclass(frozen=True)
class CadSource:
    url: str
    kind: str = "manufacturer"
    direct: bool = False
    archive: str | None = None
    filename: str | None = None
    required_for_release: bool = False


# Explicit sources are used where the manufacturer/authorized distributor publicly
# exposes CAD. Page sources are intentionally preferred over brittle guessed download
# URLs; the resolver follows the page's current STEP/ZIP link and records that final URL.
AUTHORITATIVE_SOURCES: dict[str, tuple[CadSource, ...]] = {
    "compute.raspberry_pi_5_8gb": (
        CadSource(
            "https://pip-assets.raspberrypi.com/categories/892-raspberry-pi-5/documents/RP-010083-CA-1-rpi-5%203D%20STEP%20-%20No%20Graphics%20small%20file.zip",
            direct=True,
            archive="zip",
            filename="raspberry-pi-5.step",
            required_for_release=True,
        ),
    ),
    "motor.stepperonline.17hs19-2004s1": (
        CadSource(
            "https://www.omc-stepperonline.com/nema-17-bipolar-59ncm-84oz-in-2a-42x48mm-4-wires-w-1m-cable-connector-17hs19-2004s1",
            required_for_release=True,
        ),
    ),
    "driver.pololu.g2_18v17": (
        CadSource("https://www.pololu.com/product/2991/resources", required_for_release=True),
    ),
    "power.pololu.d24v50f5": (
        CadSource(
            "https://www.pololu.com/file/0J1437/d24v50f5-step-down-voltage-regulator.step",
            direct=True,
            filename="pololu-d24v50f5.step",
            required_for_release=True,
        ),
    ),
    "power.meanwell.lrs_75_12": (
        CadSource(
            "https://www.mouser.com/catalog/additional/MEAN_WELL_LRS_75_3D.zip",
            kind="authorized_distributor",
            direct=True,
            archive="zip",
            filename="meanwell-lrs-75.step",
            required_for_release=True,
        ),
    ),
    "fan.noctua.nf_a4x10_5v": (
        CadSource("https://www.noctua.at/en/products/nf-a4x10-5v/downloads", required_for_release=True),
    ),
    "mcu.raspberry_pi_pico_2": (
        CadSource("https://pip.raspberrypi.com/categories/1264-raspberry-pi-pico-2-h"),
        CadSource("https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html"),
    ),
    "mcu.arduino_nano_every": (
        CadSource("https://docs.arduino.cc/hardware/nano-every"),
    ),
    "mcu.arduino_mega_2560": (
        CadSource("https://docs.arduino.cc/hardware/mega-2560"),
    ),
    "mcu.arduino_uno_r4_wifi": (
        CadSource("https://docs.arduino.cc/hardware/uno-r4-wifi"),
    ),
    "mcu.arduino_nano_esp32": (
        CadSource("https://docs.arduino.cc/hardware/nano-esp32"),
    ),
}


# Render appearance is not engineering truth, but preserving broad material classes is
# what keeps a detailed STEP assembly from still looking like one monochrome CAD blob.
MATERIALS: dict[str, dict[str, Any]] = {
    "pcb_green": {"color": "#176f3b", "metalness": 0.05, "roughness": 0.52},
    "pcb_blue": {"color": "#1766a6", "metalness": 0.04, "roughness": 0.52},
    "black_plastic": {"color": "#202428", "metalness": 0.02, "roughness": 0.50},
    "dark_polymer": {"color": "#34383d", "metalness": 0.01, "roughness": 0.58},
    "white_plastic": {"color": "#e7e3d8", "metalness": 0.00, "roughness": 0.48},
    "steel": {"color": "#aeb5bb", "metalness": 0.86, "roughness": 0.29},
    "stainless": {"color": "#c4c9cd", "metalness": 0.91, "roughness": 0.24},
    "aluminum": {"color": "#a7afb6", "metalness": 0.78, "roughness": 0.34},
    "galvanized_steel": {"color": "#aab1b5", "metalness": 0.73, "roughness": 0.39},
    "copper": {"color": "#b87333", "metalness": 0.88, "roughness": 0.31},
    "brass": {"color": "#c49a42", "metalness": 0.85, "roughness": 0.30},
    "rubber": {"color": "#2a2c2e", "metalness": 0.00, "roughness": 0.86},
    "noctua_brown": {"color": "#7a4d35", "metalness": 0.00, "roughness": 0.62},
    "noctua_beige": {"color": "#d6c3a2", "metalness": 0.00, "roughness": 0.60},
    "generic_component": {"color": "#7f8992", "metalness": 0.28, "roughness": 0.46},
}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "component"


def _component_dir(root: Path, component_id: str) -> Path:
    return root / _slug(component_id)


def _asset_path(root: Path, component_id: str) -> Path:
    return _component_dir(root, component_id) / "component.step"


def _metadata_path(root: Path, component_id: str) -> Path:
    return _component_dir(root, component_id) / _METADATA_NAME


def _file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_step(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 800:
            return False
        with path.open("rb") as stream:
            head = stream.read(2048).upper()
        return b"ISO-10303-21" in head or b"FILE_SCHEMA" in head
    except OSError:
        return False


def _safe_remote_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(host)
            return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)
        except ValueError:
            pass
        return True
    except Exception:
        return False


def _request(url: str, *, timeout: int = 20) -> bytes:
    if not _safe_remote_url(url):
        raise ValueError(f"Refusing non-public CAD URL: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ForgeCAD/6.2 (+https://github.com/US0RIS/CAD-for-Jarvis)",
            "Accept": "text/html,application/zip,application/octet-stream,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = str(response.geturl())
        if not _safe_remote_url(final_url):
            raise ValueError(f"CAD download redirected to non-public URL: {final_url}")
        length = response.headers.get("Content-Length")
        if length and int(length) > 180 * 1024 * 1024:
            raise ValueError("Authoritative CAD asset exceeds 180 MB download limit")
        data = response.read(180 * 1024 * 1024 + 1)
        if len(data) > 180 * 1024 * 1024:
            raise ValueError("Authoritative CAD asset exceeds 180 MB download limit")
        return data


def _step_from_zip_bytes(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="forgecad-v620-zip-") as temp_dir:
        path = Path(temp_dir) / "asset.zip"
        path.write_bytes(data)
        with zipfile.ZipFile(path) as archive:
            candidates = [
                info for info in archive.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() in {".step", ".stp"}
            ]
            if not candidates:
                raise ValueError("CAD ZIP contains no STEP/STP model")
            candidate = max(candidates, key=lambda info: info.file_size)
            if candidate.file_size > 180 * 1024 * 1024:
                raise ValueError("STEP member exceeds 180 MB limit")
            return archive.read(candidate)


def _validate_step_bytes(data: bytes, *, component_id: str) -> dict[str, Any]:
    if len(data) < 800 or len(data) > 180 * 1024 * 1024:
        raise ValueError("STEP asset has invalid size")
    with tempfile.TemporaryDirectory(prefix="forgecad-v620-step-") as temp_dir:
        path = Path(temp_dir) / "component.step"
        path.write_bytes(data)
        if not _looks_like_step(path):
            raise ValueError("Downloaded CAD file is not a STEP/STP exchange file")
        try:
            shape = cq.importers.importStep(str(path)).val()
            bounds = shape.BoundingBox()
            solids = list(shape.Solids())
        except Exception as exc:
            raise ValueError(f"STEP import failed for {component_id}: {exc}") from exc
        dimensions = [float(bounds.xlen), float(bounds.ylen), float(bounds.zlen)]
        if any(not math.isfinite(value) or value <= 0.0 for value in dimensions):
            raise ValueError("STEP asset has degenerate/non-finite bounds")
        return {
            "dimensions_mm": dimensions,
            "solid_count": max(1, len(solids)),
            "bytes": len(data),
            "sha256": sha256(data).hexdigest(),
        }


def _component_tokens(component: dict[str, Any]) -> list[str]:
    raw = [
        str(component.get("manufacturer_part_number") or ""),
        str(component.get("model") or ""),
        str(component.get("name") or ""),
    ]
    tokens: list[str] = []
    for value in raw:
        normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
        if len(normalized) >= 4:
            tokens.append(normalized)
        for part in re.split(r"[^A-Za-z0-9]+", value.lower()):
            if len(part) >= 4 and part not in {"model", "board", "module", "driver", "power", "motor"}:
                tokens.append(part)
    return list(dict.fromkeys(tokens))


def _link_score(component: dict[str, Any], href: str, text: str) -> int:
    target = f"{href} {text}".lower()
    compact = re.sub(r"[^a-z0-9]+", "", target)
    suffix = Path(urlparse(href).path).suffix.lower()
    score = 0
    if suffix in {".step", ".stp"}:
        score += 160
    elif suffix == ".zip":
        score += 85
    elif suffix in {".igs", ".iges", ".stl", ".obj", ".pdf", ".dxf"}:
        score -= 100
    if "step" in target or "stp" in target:
        score += 75
    if "3d cad" in target or "3d model" in target or "cad files" in target:
        score += 45
    if "download" in target or "resources" in target:
        score += 12
    for token in _component_tokens(component):
        if token in compact:
            score += 30
    return score


def _discover_asset_links(page_url: str, component: dict[str, Any]) -> list[str]:
    html = _request(page_url).decode("utf-8", errors="replace")
    parser = _LinkParser()
    parser.feed(html)
    scored: list[tuple[int, str]] = []
    for href, text in parser.links:
        url = urljoin(page_url, href)
        if not _safe_remote_url(url):
            continue
        score = _link_score(component, url, text)
        if score >= 70:
            scored.append((score, url))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return list(dict.fromkeys(url for _, url in scored[:12]))


def _download_step_candidate(url: str) -> tuple[bytes, str]:
    data = _request(url)
    lower = urlparse(url).path.lower()
    if lower.endswith(".zip") or data[:4] == b"PK\x03\x04":
        return _step_from_zip_bytes(data), "zip"
    with tempfile.TemporaryDirectory(prefix="forgecad-v620-candidate-") as temp_dir:
        path = Path(temp_dir) / "candidate.step"
        path.write_bytes(data)
        if _looks_like_step(path):
            return data, "step"
    raise ValueError("CAD candidate is neither a STEP file nor a ZIP containing STEP")


def _source_candidates(component: dict[str, Any]) -> list[CadSource]:
    component_id = str(component.get("id") or "")
    result = list(AUTHORITATIVE_SOURCES.get(component_id, ()))

    # A built-in/custom component may already declare a remote authoritative asset.
    geometry = component.get("geometry") or {}
    for raw in geometry.get("asset_sources") or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "")
        kind = str(raw.get("kind") or "manufacturer")
        if url and kind in {"manufacturer", "authorized_distributor"}:
            result.append(CadSource(url, kind=kind, direct=bool(raw.get("direct")), archive=raw.get("archive"), filename=raw.get("filename")))

    # High-trust manufacturer provenance is a useful generic discovery boundary. We do
    # not crawl arbitrary user/procurement URLs or low-trust community sources.
    if int(component.get("trust_score") or 0) >= 85:
        for provenance in component.get("provenance") or []:
            if not isinstance(provenance, dict):
                continue
            kind = str(provenance.get("kind") or "")
            url = str(provenance.get("url") or "")
            if kind in {"manufacturer", "authorized_distributor"} and url and not url.lower().endswith((".pdf", ".dxf")):
                result.append(CadSource(url, kind=kind))

    dedup: list[CadSource] = []
    seen: set[tuple[str, str]] = set()
    for source in result:
        key = (source.url, source.kind)
        if key not in seen:
            seen.add(key)
            dedup.append(source)
    return dedup


def _registry_step(component: dict[str, Any]) -> Path | None:
    for asset in (component.get("geometry") or {}).get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("role") or "geometry") != "geometry" or str(asset.get("format") or "").lower() not in {"step", "stp"}:
            continue
        source_kind = str((asset.get("source") or {}).get("kind") or "")
        if source_kind not in {"manufacturer", "authorized_distributor"}:
            continue
        path = registry.resolve_asset_path(asset)
        if path and _looks_like_step(path):
            return path
    return None


def _existing_authoritative_asset(component_id: str) -> tuple[Path, dict[str, Any]] | None:
    for root in (PACKAGE_ASSET_DIR, CACHE_ASSET_DIR):
        path = _asset_path(root, component_id)
        metadata_path = _metadata_path(root, component_id)
        if not _looks_like_step(path):
            continue
        metadata: dict[str, Any] = {}
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        except Exception:
            metadata = {}
        metadata.setdefault("sha256", _file_sha(path))
        metadata.setdefault("source_kind", "manufacturer")
        metadata.setdefault("geometry_fidelity", "official_step")
        return path, metadata
    return None


def _existing_v110_asset(component_id: str) -> tuple[Path, dict[str, Any]] | None:
    # Preserve the three official/verified assets already shipped by the v1.1 layer.
    try:
        path = realistic_components.resolve_step(component_id, allow_download=False)
    except Exception:
        path = None
    if path and _looks_like_step(path):
        spec = realistic_components.CAD_ASSETS.get(component_id) or {}
        kind = str(spec.get("source") or "manufacturer")
        return path, {
            "component_id": component_id,
            "source_url": spec.get("url"),
            "resolved_url": spec.get("url"),
            "source_kind": kind,
            "geometry_fidelity": "official_step" if kind == "manufacturer" else "verified_step",
            "sha256": _file_sha(path),
            "bytes": path.stat().st_size,
            "source_layer": "v110",
        }
    return None


def _write_cached_asset(component_id: str, data: bytes, metadata: dict[str, Any], *, root: Path = CACHE_ASSET_DIR) -> tuple[Path, dict[str, Any]]:
    folder = _component_dir(root, component_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = _asset_path(root, component_id)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)
    metadata = deepcopy(metadata)
    metadata.update({
        "component_id": component_id,
        "sha256": sha256(data).hexdigest(),
        "bytes": len(data),
    })
    _metadata_path(root, component_id).write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return path, metadata


def _fetch_source(component: dict[str, Any], source: CadSource) -> tuple[bytes, dict[str, Any]]:
    urls: list[str]
    if source.direct:
        urls = [source.url]
    else:
        urls = _discover_asset_links(source.url, component)
        # Some high-trust source records themselves point straight at a STEP/ZIP even
        # without being marked direct in component metadata.
        if Path(urlparse(source.url).path).suffix.lower() in {".step", ".stp", ".zip"}:
            urls.insert(0, source.url)
    errors: list[str] = []
    for url in list(dict.fromkeys(urls)):
        try:
            data, transport = _download_step_candidate(url)
            verification = _validate_step_bytes(data, component_id=str(component.get("id") or ""))
            return data, {
                "source_url": source.url,
                "resolved_url": url,
                "source_kind": source.kind,
                "geometry_fidelity": "official_step" if source.kind == "manufacturer" else "verified_step",
                "transport": transport,
                "verification": verification,
            }
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors) if errors else f"No STEP link discovered on {source.url}")


def resolve_authoritative_step(component: dict[str, Any], *, allow_download: bool = False) -> tuple[Path, dict[str, Any]] | None:
    component_id = str(component.get("id") or "")
    if not component_id:
        return None

    registered = _registry_step(component)
    if registered:
        return registered, {
            "component_id": component_id,
            "source_kind": "manufacturer_or_authorized_registry_asset",
            "geometry_fidelity": str((component.get("geometry") or {}).get("fidelity") or "official_step"),
            "sha256": _file_sha(registered),
            "bytes": registered.stat().st_size,
            "source_layer": "component_registry",
        }

    existing = _existing_authoritative_asset(component_id) or _existing_v110_asset(component_id)
    if existing:
        return existing
    if not allow_download or component_id in _DOWNLOAD_FAILURES:
        return None

    sources = _source_candidates(component)
    if not sources:
        return None
    with _DOWNLOAD_LOCK:
        existing = _existing_authoritative_asset(component_id) or _existing_v110_asset(component_id)
        if existing:
            return existing
        failures: list[str] = []
        for source in sources:
            try:
                data, metadata = _fetch_source(component, source)
                return _write_cached_asset(component_id, data, metadata)
            except Exception as exc:
                failures.append(f"{source.url}: {exc}")
        _DOWNLOAD_FAILURES.add(component_id)
        return None


def queue_authoritative_resolution(component: dict[str, Any]) -> None:
    component_id = str(component.get("id") or "")
    if not component_id or not _source_candidates(component):
        return
    if component_id in _DOWNLOAD_FAILURES:
        return
    with _DOWNLOAD_LOCK:
        if component_id in _DOWNLOAD_QUEUED:
            return
        if _existing_authoritative_asset(component_id) or _existing_v110_asset(component_id):
            return
        _DOWNLOAD_QUEUED.add(component_id)

    def worker() -> None:
        try:
            resolve_authoritative_step(component, allow_download=True)
        finally:
            with _DOWNLOAD_LOCK:
                _DOWNLOAD_QUEUED.discard(component_id)

    threading.Thread(target=worker, name=f"ForgeCAD exact CAD {component_id}", daemon=True).start()


def _center_shape(shape: Any) -> Any:
    bounds = shape.BoundingBox()
    return shape.translate((
        -(float(bounds.xmin) + float(bounds.xmax)) / 2.0,
        -(float(bounds.ymin) + float(bounds.ymax)) / 2.0,
        -(float(bounds.zmin) + float(bounds.zmax)) / 2.0,
    ))


def _material_for_solid(component: dict[str, Any], solid: Any, assembly_bounds: Any, index: int) -> str:
    category = str(component.get("category") or "").lower()
    tags = {str(value).lower() for value in component.get("tags") or []}
    bounds = solid.BoundingBox()
    dims = sorted([float(bounds.xlen), float(bounds.ylen), float(bounds.zlen)])
    assembly_dims = sorted([float(assembly_bounds.xlen), float(assembly_bounds.ylen), float(assembly_bounds.zlen)])
    thinness = dims[0] / max(dims[-1], 1e-9)
    relative_long = dims[-1] / max(assembly_dims[-1], 1e-9)

    if category in {"compute", "microcontroller", "motor_driver", "load_driver", "sensor", "power_converter"}:
        if thinness < 0.09 and relative_long > 0.55:
            return "pcb_blue" if "pololu" in str(component.get("manufacturer") or "").lower() else "pcb_green"
        if dims[-1] <= 4.5 and dims[-2] <= 25:
            return "black_plastic"
        if dims[0] < 1.5 and dims[-1] > 5:
            return "brass"
        return "steel"
    if category in {"stepper_motor", "dc_motor", "gearmotor", "bldc_motor"}:
        if dims[0] < max(8.0, assembly_dims[0] * 0.25) and dims[-1] > assembly_dims[-1] * 0.25:
            return "stainless"
        if index in {0, 1}:
            return "black_plastic"
        return "steel"
    if category == "fan":
        if "noctua" in str(component.get("manufacturer") or "").lower():
            return "noctua_brown" if index % 3 else "noctua_beige"
        return "dark_polymer"
    if category == "bearing":
        return "steel"
    if category in {"power_supply", "power"}:
        if thinness < 0.08 and relative_long > 0.55:
            return "galvanized_steel"
        if dims[-1] < assembly_dims[-1] * 0.25:
            return "black_plastic"
        return "galvanized_steel"
    if category in {"fastener", "shaft", "linear_motion"}:
        return "steel"
    return "generic_component"


def _exact_render_parts(component: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    imported = cq.importers.importStep(str(path)).val()
    shape = _center_shape(imported)
    solids = list(shape.Solids())
    if not solids:
        solids = [shape]
    assembly_bounds = shape.BoundingBox()
    parts: list[dict[str, Any]] = []
    for index, solid in enumerate(solids):
        material_class = _material_for_solid(component, solid, assembly_bounds, index)
        material = MATERIALS[material_class]
        parts.append({
            "shape": solid,
            "name": f"solid-{index + 1:03d}",
            "material_class": material_class,
            "material": deepcopy(material),
            "color": str(material["color"]),
        })
    return parts


def _fallback_material_class(color: str, component: dict[str, Any]) -> str:
    value = color.lower()
    if value in {"#16813e", "#167a3b", "#187a3b", "#247244"}:
        return "pcb_green"
    if value == "#1766a6":
        return "pcb_blue"
    if value in {"#17191b", "#202327", "#202428", "#24272b", "#25282b", "#25282c", "#303337", "#303438", "#34383d"}:
        return "black_plastic"
    if value in {"#d5a52a", "#d7a928", "#c89b42"}:
        return "brass"
    category = str(component.get("category") or "")
    if category in {"bearing", "fastener", "shaft", "linear_motion", "stepper_motor"}:
        return "steel"
    return "generic_component"


def rich_render_parts(obj: dict[str, Any], *, allow_download: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    component = physical_components.component_definition(obj) or {}
    component_id = str(obj.get("component_ref") or component.get("id") or "")
    exact = resolve_authoritative_step(component, allow_download=allow_download) if component else None
    if exact:
        path, metadata = exact
        parts = _exact_render_parts(component, path)
        return parts, {
            "component_id": component_id,
            "resolved": True,
            "geometry_source": metadata.get("source_kind", "manufacturer"),
            "geometry_fidelity": metadata.get("geometry_fidelity", "official_step"),
            "asset_sha256": metadata.get("sha256") or _file_sha(path),
            "asset_bytes": metadata.get("bytes") or path.stat().st_size,
            "asset_path": str(path),
            "solid_count": len(parts),
            "fallback": False,
            "authoritative_cad": True,
        }

    if component and _source_candidates(component):
        queue_authoritative_resolution(component)

    # Important: fallback stays whatever the validated 6.1 component layer already
    # considered correct. 6.2 only enriches its render metadata; it does not silently
    # change engineering dimensions when exact CAD is unavailable.
    assert _ORIGINAL_COMPONENT_PARTS is not None
    fallback = _ORIGINAL_COMPONENT_PARTS(obj) or []
    parts: list[dict[str, Any]] = []
    for index, item in enumerate(fallback):
        try:
            shape, color = item
        except Exception:
            continue
        material_class = _fallback_material_class(str(color), component)
        parts.append({
            "shape": shape,
            "name": f"derived-{index + 1:03d}",
            "material_class": material_class,
            "material": deepcopy(MATERIALS[material_class]) | {"color": str(color)},
            "color": str(color),
        })
    base_status = _ORIGINAL_GEOMETRY_STATUS(obj) if _ORIGINAL_GEOMETRY_STATUS is not None else {}
    return parts, {
        **(base_status if isinstance(base_status, dict) else {}),
        "component_id": component_id,
        "resolved": bool(parts),
        "fallback": True,
        "authoritative_cad": False,
        "authoritative_source_available": bool(component and _source_candidates(component)),
        "solid_count": len(parts),
    }


def geometry_status(obj: dict[str, Any]) -> dict[str, Any]:
    component = physical_components.component_definition(obj) or {}
    component_id = str(obj.get("component_ref") or component.get("id") or "")
    exact = resolve_authoritative_step(component, allow_download=False) if component else None
    if exact:
        path, metadata = exact
        try:
            solid_count = len(list(_center_shape(cq.importers.importStep(str(path)).val()).Solids())) or 1
        except Exception:
            solid_count = int((metadata.get("verification") or {}).get("solid_count") or 1)
        return {
            "component_id": component_id,
            "resolved": True,
            "geometry_source": metadata.get("source_kind", "manufacturer"),
            "geometry_fidelity": metadata.get("geometry_fidelity", "official_step"),
            "asset_sha256": metadata.get("sha256") or _file_sha(path),
            "asset_bytes": metadata.get("bytes") or path.stat().st_size,
            "solid_count": solid_count,
            "fallback": False,
            "authoritative_cad": True,
        }
    base = _ORIGINAL_GEOMETRY_STATUS(obj) if _ORIGINAL_GEOMETRY_STATUS is not None else {}
    return {
        **(base if isinstance(base, dict) else {}),
        "component_id": component_id,
        "authoritative_cad": False,
        "authoritative_source_available": bool(component and _source_candidates(component)),
        "resolution_state": "queued" if component_id in _DOWNLOAD_QUEUED else ("failed" if component_id in _DOWNLOAD_FAILURES else "fallback"),
    }


def geometry_revision(obj: dict[str, Any]) -> str:
    status = geometry_status(obj)
    return str(status.get("asset_sha256") or f"fallback:{status.get('geometry_fidelity')}:{status.get('solid_count', 0)}")


def _parts_for_engineering(obj: dict[str, Any]):
    parts, status = rich_render_parts(obj, allow_download=False)
    if status.get("authoritative_cad"):
        return [(part["shape"], part["color"]) for part in parts]
    assert _ORIGINAL_COMPONENT_PARTS is not None
    return _ORIGINAL_COMPONENT_PARTS(obj)


def catalog_audit(*, attempt_download: bool = False) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    exact = fallback = source_available = 0
    for component in registry.all_components():
        manufacturer = str(component.get("manufacturer") or "")
        actual_sku = manufacturer.lower() not in {"", "generic", "unknown", "iso", "multi-source commodity"}
        if not actual_sku:
            continue
        obj = {
            "id": f"audit:{component['id']}",
            "kind": "component",
            "component_ref": component["id"],
            "component_snapshot": deepcopy(component),
            "features": [],
            "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0], "scale": [1, 1, 1]},
        }
        resolved = resolve_authoritative_step(component, allow_download=attempt_download)
        sources = _source_candidates(component)
        if resolved:
            exact += 1
            state = "authoritative_cad"
        else:
            fallback += 1
            state = "fallback"
        if sources:
            source_available += 1
        rows.append({
            "component_id": component["id"],
            "manufacturer": manufacturer,
            "model": component.get("model"),
            "state": state,
            "source_candidates": [source.url for source in sources],
            "geometry_fidelity": (component.get("geometry") or {}).get("fidelity"),
        })
    return {
        "specific_purchased_components": len(rows),
        "authoritative_cad_resolved": exact,
        "fallback": fallback,
        "authoritative_source_candidates": source_available,
        "rows": rows,
    }


def prefetch(*, required_only: bool = False, root: Path = PACKAGE_ASSET_DIR, strict: bool = False) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for component_id, sources in AUTHORITATIVE_SOURCES.items():
        if required_only and not any(source.required_for_release for source in sources):
            continue
        try:
            component = registry.component_by_id(component_id)
        except KeyError:
            failures[component_id] = "component missing from registry"
            continue
        try:
            # Download through the normal cache path, then copy the verified bytes into
            # package assets so installed builds are network-independent.
            resolved = resolve_authoritative_step(component, allow_download=True)
            if not resolved:
                raise RuntimeError("no authoritative STEP resolved")
            source_path, metadata = resolved
            data = source_path.read_bytes()
            verification = _validate_step_bytes(data, component_id=component_id)
            packaged, packaged_metadata = _write_cached_asset(
                component_id,
                data,
                {**metadata, "verification": verification, "packaged": True},
                root=root,
            )
            results[component_id] = {
                "path": str(packaged),
                "sha256": packaged_metadata["sha256"],
                "bytes": packaged_metadata["bytes"],
                "solid_count": verification["solid_count"],
                "source": packaged_metadata.get("resolved_url") or packaged_metadata.get("source_url"),
            }
        except Exception as exc:
            failures[component_id] = str(exc)
    if strict and failures:
        raise RuntimeError("Authoritative CAD prefetch failed: " + json.dumps(failures, sort_keys=True))
    return {"ok": not failures, "resolved": results, "failures": failures, "root": str(root)}


def install() -> None:
    global _INSTALLED, _ORIGINAL_COMPONENT_PARTS, _ORIGINAL_GEOMETRY_STATUS
    if _INSTALLED:
        return
    _ORIGINAL_COMPONENT_PARTS = physical_components.component_parts
    _ORIGINAL_GEOMETRY_STATUS = physical_components.component_geometry_status
    physical_components.component_parts = _parts_for_engineering
    physical_components.component_geometry_status = geometry_status
    _INSTALLED = True


def _main() -> None:
    parser = argparse.ArgumentParser(description="ForgeCAD 6.2 authoritative component CAD tools")
    sub = parser.add_subparsers(dest="command", required=True)
    prefetch_parser = sub.add_parser("prefetch")
    prefetch_parser.add_argument("--required-only", action="store_true")
    prefetch_parser.add_argument("--strict", action="store_true")
    prefetch_parser.add_argument("--root", type=Path, default=PACKAGE_ASSET_DIR)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.command == "prefetch":
        print(json.dumps(prefetch(required_only=args.required_only, root=args.root, strict=args.strict), indent=2))
    else:
        print(json.dumps(catalog_audit(attempt_download=args.download), indent=2))


if __name__ == "__main__":
    _main()
