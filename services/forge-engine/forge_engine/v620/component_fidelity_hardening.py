from __future__ import annotations

"""Hardening layer for ForgeCAD 6.2 authoritative purchased-component CAD.

This module deliberately wraps the already-working 6.2 resolver rather than creating a
second geometry system. It adds four properties that matter for the original ForgeCAD
contract:

* vendor pages are fetched with normal browser request headers and link discovery also
  sees STEP/STP/ZIP URLs embedded in page script/JSON;
* known release parts use current product/download endpoints instead of stale guessed
  asset URLs;
* a syntactically valid STEP is not accepted as the requested SKU unless its geometry
  is physically plausible for that component and its source is bound to that SKU;
* completion of a background exact-CAD resolution advances a process-local generation
  counter so the desktop can replace a temporary fallback without a project mutation.

The engineering truth boundary is unchanged: manufacturer CAD is authoritative geometry,
not evidence that a physical specimen matches the model.
"""

import argparse
from copy import deepcopy
import html
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from urllib.parse import urljoin, urlparse
import urllib.request

import cadquery as cq

from . import component_fidelity as base


_MAX_DOWNLOAD_BYTES = 180 * 1024 * 1024
_INSTALL_LOCK = threading.RLock()
_GENERATION_LOCK = threading.RLock()
_INSTALLED = False
_ASSET_GENERATION = 0
_VERIFIED_ASSETS: dict[tuple[str, str], dict[str, Any]] = {}
_REJECTED_ASSETS: set[tuple[str, str]] = set()
_SOURCE_FAILURES: dict[str, list[str]] = {}

_ORIGINAL_REQUEST = base._request
_ORIGINAL_DISCOVER = base._discover_asset_links
_ORIGINAL_FETCH_SOURCE = base._fetch_source
_ORIGINAL_RESOLVE = base.resolve_authoritative_step
_ORIGINAL_QUEUE = base.queue_authoritative_resolution


def _source_overrides() -> None:
    # StepperOnline publishes the exact STEP on the current product page. The download
    # route is included first because some server/CDN combinations omit that link from
    # bot-oriented HTML even though it is present for normal browsers.
    base.AUTHORITATIVE_SOURCES["motor.stepperonline.17hs19-2004s1"] = (
        base.CadSource(
            "https://www.omc-stepperonline.com/index.php?file=110%2F17HS19-2004S1.STEP&route=product%2Fproduct%2Fget_file",
            direct=True,
            filename="17HS19-2004S1.STEP",
            required_for_release=True,
        ),
        base.CadSource(
            "https://www.omc-stepperonline.com/nema-17-bipolar-59ncm-84oz-in-2a-42x48mm-4-wires-w-1m-cable-connector-17hs19-2004s1",
            required_for_release=True,
        ),
    )

    # Mouser currently exposes the LRS-75 model as an STP ZIP from the exact product
    # page. Prefer page discovery over the old guessed /catalog/additional ZIP path.
    base.AUTHORITATIVE_SOURCES["power.meanwell.lrs_75_12"] = (
        base.CadSource(
            "https://www.mouser.com/ProductDetail/MEAN-WELL/LRS-75-12",
            kind="authorized_distributor",
            required_for_release=True,
        ),
        base.CadSource(
            "https://www.mouser.co.uk/en/ProductDetail/MEAN-WELL/LRS-75-12",
            kind="authorized_distributor",
            required_for_release=True,
        ),
    )

    # Keep Noctua on its exact product download page; browser-like requests and the
    # expanded link parser below resolve the CDN STEP link published under 3D CAD.
    base.AUTHORITATIVE_SOURCES["fan.noctua.nf_a4x10_5v"] = (
        base.CadSource(
            "https://www.noctua.at/en/products/nf-a4x10-5v/downloads",
            required_for_release=True,
        ),
    )


def _browser_request(url: str, *, timeout: int = 25) -> bytes:
    if not base._safe_remote_url(url):
        raise ValueError(f"Refusing non-public CAD URL: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/zip,application/octet-stream,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = str(response.geturl())
        if not base._safe_remote_url(final_url):
            raise ValueError(f"CAD download redirected to non-public URL: {final_url}")
        length = response.headers.get("Content-Length")
        if length and int(length) > _MAX_DOWNLOAD_BYTES:
            raise ValueError("Authoritative CAD asset exceeds 180 MB download limit")
        data = response.read(_MAX_DOWNLOAD_BYTES + 1)
        if len(data) > _MAX_DOWNLOAD_BYTES:
            raise ValueError("Authoritative CAD asset exceeds 180 MB download limit")
        return data


def _embedded_urls(page_url: str, text: str) -> list[tuple[str, str]]:
    """Find download URLs that are present in script/JSON rather than anchor tags."""
    decoded = html.unescape(text).replace("\\/", "/")
    rows: list[tuple[str, str]] = []
    patterns = (
        r"https://[^\s\"'<>]+",
        r"(?i)(?:href|url|download(?:url)?)\s*[:=]\s*[\"']([^\"']+)[\"']",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, decoded):
            raw = match.group(1) if match.lastindex else match.group(0)
            raw = raw.rstrip(",);]")
            try:
                url = urljoin(page_url, raw)
            except Exception:
                continue
            if base._safe_remote_url(url):
                rows.append((url, raw))
    return rows


def _discover_asset_links(page_url: str, component: dict[str, Any]) -> list[str]:
    payload = base._request(page_url)
    text = payload.decode("utf-8", errors="replace")
    parser = base._LinkParser()
    parser.feed(text)
    candidates: list[tuple[str, str]] = [
        (urljoin(page_url, href), label) for href, label in parser.links
    ]
    candidates.extend(_embedded_urls(page_url, text))

    scored: list[tuple[int, str]] = []
    for url, label in candidates:
        if not base._safe_remote_url(url):
            continue
        score = base._link_score(component, url, label)
        lower = f"{url} {label}".lower()
        # Product pages often label a download simply "STEP"/"STP File (Zip)" while
        # the underlying CDN route has an opaque filename. Preserve that strong signal.
        if re.search(r"\b(?:step|stp)\b", lower):
            score += 20
        if score >= 60:
            scored.append((score, url))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return list(dict.fromkeys(url for _, url in scored[:20]))


def _expected_dimensions(component: dict[str, Any]) -> list[float] | None:
    raw = (component.get("geometry") or {}).get("dimensions_mm") or component.get("dimensions_mm")
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        values = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 0 for value in values):
        return None
    return values


def _top_two_match(actual: list[float], expected: list[float]) -> tuple[bool, list[float]]:
    a = sorted(float(value) for value in actual)
    e = sorted(float(value) for value in expected)
    ratios = [a[-2] / e[-2], a[-1] / e[-1]]
    return all(0.45 <= ratio <= 2.25 for ratio in ratios), ratios


def _solid_body_matches(data: bytes, expected: list[float]) -> bool:
    """Allow wires/shafts to enlarge the assembly envelope if a real body matches."""
    try:
        with tempfile.TemporaryDirectory(prefix="forgecad-v620-identity-") as temp_dir:
            path = Path(temp_dir) / "candidate.step"
            path.write_bytes(data)
            shape = cq.importers.importStep(str(path)).val()
            for solid in shape.Solids():
                bounds = solid.BoundingBox()
                dims = [float(bounds.xlen), float(bounds.ylen), float(bounds.zlen)]
                if any(value <= 0 or not math.isfinite(value) for value in dims):
                    continue
                matched, _ = _top_two_match(dims, expected)
                if matched:
                    return True
    except Exception:
        return False
    return False


def _strong_tokens(component: dict[str, Any]) -> list[str]:
    tokens = []
    for raw in (
        str(component.get("manufacturer_part_number") or ""),
        str(component.get("model") or ""),
    ):
        compact = re.sub(r"[^a-z0-9]+", "", raw.lower())
        if len(compact) >= 5:
            tokens.append(compact)
    return list(dict.fromkeys(tokens))


def _source_is_bound(component: dict[str, Any], source_url: str | None, metadata: dict[str, Any]) -> bool:
    if metadata.get("source_layer") in {"v110", "component_registry"}:
        return True
    url = str(source_url or "")
    component_id = str(component.get("id") or "")
    for source in base.AUTHORITATIVE_SOURCES.get(component_id, ()):  # explicit SKU mapping
        if source.url == url:
            return True
    for raw in (component.get("geometry") or {}).get("asset_sources") or []:
        if isinstance(raw, dict) and str(raw.get("url") or "") == url:
            return True
    return False


def _verify_component_identity(
    component: dict[str, Any],
    verification: dict[str, Any],
    *,
    source_url: str | None,
    resolved_url: str | None,
    metadata: dict[str, Any] | None = None,
    data: bytes | None = None,
) -> dict[str, Any]:
    """Fail closed when a valid STEP is not plausibly the requested purchased SKU."""
    metadata = metadata or {}
    component_id = str(component.get("id") or "")
    expected = _expected_dimensions(component)
    actual = [float(value) for value in verification.get("dimensions_mm") or []]
    if expected is None or len(actual) != 3:
        raise ValueError(f"{component_id}: exact CAD identity requires three known component dimensions")

    envelope_match, ratios = _top_two_match(actual, expected)
    body_match = False
    if not envelope_match and data is not None:
        body_match = _solid_body_matches(data, expected)
    if not envelope_match and not body_match:
        raise ValueError(
            f"{component_id}: STEP envelope {actual!r} is incompatible with declared dimensions {expected!r}"
        )

    bound = _source_is_bound(component, source_url, metadata)
    source_text = re.sub(r"[^a-z0-9]+", "", f"{source_url or ''} {resolved_url or ''}".lower())
    token_match = next((token for token in _strong_tokens(component) if token in source_text), None)
    if not bound and not token_match:
        raise ValueError(
            f"{component_id}: STEP source is not explicitly bound to this SKU and contains no model/MPN identity token"
        )

    return {
        "component_id": component_id,
        "method": "explicit_source_binding+geometry" if bound else "source_token+geometry",
        "source_bound": bound,
        "source_token": token_match,
        "expected_dimensions_mm": expected,
        "actual_dimensions_mm": actual,
        "top_two_dimension_ratios": [round(value, 5) for value in ratios],
        "assembly_envelope_match": envelope_match,
        "matching_body_solid": body_match,
    }


def _record_failure(component: dict[str, Any], source: base.CadSource, exc: Exception) -> None:
    component_id = str(component.get("id") or "unknown")
    _SOURCE_FAILURES.setdefault(component_id, []).append(f"{source.url}: {exc}")


def _fetch_source(component: dict[str, Any], source: base.CadSource) -> tuple[bytes, dict[str, Any]]:
    try:
        data, metadata = _ORIGINAL_FETCH_SOURCE(component, source)
        verification = metadata.get("verification") or base._validate_step_bytes(
            data, component_id=str(component.get("id") or "")
        )
        evidence = _verify_component_identity(
            component,
            verification,
            source_url=source.url,
            resolved_url=str(metadata.get("resolved_url") or source.url),
            metadata=metadata,
            data=data,
        )
        return data, {**metadata, "identity_verification": evidence}
    except Exception as exc:
        _record_failure(component, source, exc)
        raise


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _verify_resolved(component: dict[str, Any], path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    component_id = str(component.get("id") or "")
    asset_sha = str(metadata.get("sha256") or base._file_sha(path))
    key = (component_id, asset_sha)
    if key in _REJECTED_ASSETS:
        raise ValueError(f"{component_id}: previously rejected authoritative CAD asset {asset_sha[:12]}")
    cached = _VERIFIED_ASSETS.get(key)
    if cached is not None:
        return cached

    verification = metadata.get("verification")
    data: bytes | None = None
    if not isinstance(verification, dict) or len(verification.get("dimensions_mm") or []) != 3:
        data = path.read_bytes()
        verification = base._validate_step_bytes(data, component_id=component_id)
    evidence = metadata.get("identity_verification")
    if not isinstance(evidence, dict):
        if data is None:
            data = path.read_bytes()
        evidence = _verify_component_identity(
            component,
            verification,
            source_url=str(metadata.get("source_url") or ""),
            resolved_url=str(metadata.get("resolved_url") or metadata.get("source_url") or ""),
            metadata=metadata,
            data=data,
        )
    _VERIFIED_ASSETS[key] = evidence
    return evidence


def _resolve_authoritative_step(
    component: dict[str, Any], *, allow_download: bool = False
) -> tuple[Path, dict[str, Any]] | None:
    result = _ORIGINAL_RESOLVE(component, allow_download=allow_download)
    if not result:
        return None
    path, metadata = result
    component_id = str(component.get("id") or "")
    asset_sha = str(metadata.get("sha256") or base._file_sha(path))
    try:
        evidence = _verify_resolved(component, path, metadata)
        return path, {**metadata, "identity_verification": evidence}
    except Exception as exc:
        _REJECTED_ASSETS.add((component_id, asset_sha))
        # A bad network cache must not permanently shadow a corrected source. Package
        # assets are immutable and therefore fail closed to the lower-fidelity model.
        if _path_under(path, base.CACHE_ASSET_DIR):
            try:
                path.unlink(missing_ok=True)
                base._metadata_path(base.CACHE_ASSET_DIR, component_id).unlink(missing_ok=True)
            except OSError:
                pass
            if allow_download:
                second = _ORIGINAL_RESOLVE(component, allow_download=True)
                if second:
                    second_path, second_metadata = second
                    try:
                        evidence = _verify_resolved(component, second_path, second_metadata)
                        return second_path, {**second_metadata, "identity_verification": evidence}
                    except Exception:
                        pass
        _SOURCE_FAILURES.setdefault(component_id, []).append(f"resolved asset rejected: {exc}")
        return None


def _bump_generation() -> None:
    global _ASSET_GENERATION
    with _GENERATION_LOCK:
        _ASSET_GENERATION += 1


def asset_generation() -> int:
    with _GENERATION_LOCK:
        return int(_ASSET_GENERATION)


def _queue_authoritative_resolution(component: dict[str, Any]) -> None:
    component_id = str(component.get("id") or "")
    if not component_id or not base._source_candidates(component):
        return
    if component_id in base._DOWNLOAD_FAILURES:
        return
    with base._DOWNLOAD_LOCK:
        if component_id in base._DOWNLOAD_QUEUED:
            return
        if base.resolve_authoritative_step(component, allow_download=False):
            return
        base._DOWNLOAD_QUEUED.add(component_id)

    def worker() -> None:
        try:
            resolved = base.resolve_authoritative_step(component, allow_download=True)
            if resolved:
                _bump_generation()
        finally:
            with base._DOWNLOAD_LOCK:
                base._DOWNLOAD_QUEUED.discard(component_id)

    threading.Thread(
        target=worker,
        name=f"ForgeCAD exact CAD {component_id}",
        daemon=True,
    ).start()


def install() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _source_overrides()
        base._request = _browser_request
        base._discover_asset_links = _discover_asset_links
        base._fetch_source = _fetch_source
        base.resolve_authoritative_step = _resolve_authoritative_step
        base.queue_authoritative_resolution = _queue_authoritative_resolution
        _INSTALLED = True


def prefetch(*, required_only: bool = False, root: Path = base.PACKAGE_ASSET_DIR, strict: bool = False) -> dict[str, Any]:
    install()
    _SOURCE_FAILURES.clear()
    result = base.prefetch(required_only=required_only, root=root, strict=False)
    failures = dict(result.get("failures") or {})
    for component_id in failures:
        detail = _SOURCE_FAILURES.get(component_id)
        if detail:
            failures[component_id] = " | ".join(detail)
    result["failures"] = failures
    result["ok"] = not failures
    if strict and failures:
        raise RuntimeError("Authoritative CAD prefetch failed: " + json.dumps(failures, sort_keys=True))
    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="ForgeCAD 6.2 hardened authoritative CAD tools")
    sub = parser.add_subparsers(dest="command", required=True)
    prefetch_parser = sub.add_parser("prefetch")
    prefetch_parser.add_argument("--required-only", action="store_true")
    prefetch_parser.add_argument("--strict", action="store_true")
    prefetch_parser.add_argument("--root", type=Path, default=base.PACKAGE_ASSET_DIR)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    install()
    if args.command == "prefetch":
        print(json.dumps(prefetch(required_only=args.required_only, root=args.root, strict=args.strict), indent=2))
    else:
        print(json.dumps(base.catalog_audit(attempt_download=args.download), indent=2))


install()

if __name__ == "__main__":
    _main()
