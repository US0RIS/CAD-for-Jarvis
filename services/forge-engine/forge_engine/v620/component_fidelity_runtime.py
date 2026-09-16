from __future__ import annotations

"""Runtime/provider hardening for ForgeCAD 6.2 purchased-component CAD.

This layer is intentionally small and provider-oriented. The canonical component model,
B-rep import, identity verification and renderer remain in ``component_fidelity`` and
``component_fidelity_hardening``. This module adds the operational behavior needed for
real vendor sites:

* direct manufacturer CDN assets when product pages rate-limit automated clients;
* cookie + Referer preserving downloads for vendor endpoints that reject hotlinks;
* an authorized-distributor fallback for CAD hidden behind client-rendered UI;
* DNS-aware public-network validation for remote component asset sources;
* a process epoch plus monotonic asset generation for cheap desktop refresh polling.

None of these network/provider rules promote a model to physical evidence. They only
establish provenance for the digital geometry used for a purchased SKU.
"""

import argparse
from http.cookiejar import CookieJar
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
import urllib.request
from uuid import uuid4

from . import component_fidelity as base
from . import component_fidelity_hardening as hardening


_INSTALL_LOCK = threading.RLock()
_INSTALLED = False
_PROCESS_EPOCH = uuid4().hex
_MAX_DOWNLOAD_BYTES = 180 * 1024 * 1024

# Capture the hardened source fetch before this module replaces the public resolver hook.
_HARDENED_FETCH_SOURCE = base._fetch_source

_STEPPER_COMPONENT_ID = "motor.stepperonline.17hs19-2004s1"
_STEPPER_PRODUCT_URL = (
    "https://www.omc-stepperonline.com/"
    "nema-17-bipolar-59ncm-84oz-in-2a-42x48mm-4-wires-w-1m-cable-connector-17hs19-2004s1"
)
_STEPPER_DIRECT_URL = (
    "https://www.omc-stepperonline.com/index.php?"
    "route=product/product/get_file&file=110/17HS19-2004S1.STEP"
)

_NOCTUA_COMPONENT_ID = "fan.noctua.nf_a4x10_5v"
# Direct manufacturer CDN target behind the product page's current "3D CAD -> STEP" link.
# Using the CDN avoids rate-limit failures on noctua.at while preserving manufacturer
# provenance and the exact product-family CAD Noctua publishes for mounting dimensions.
_NOCTUA_CAD_URL = "https://cdn.noctua.at/media/46800471/NF-A4x10_Public-CAD.zip?download=true"

_MEANWELL_COMPONENT_ID = "power.meanwell.lrs_75_12"
_TRANSMOTEC_LRS75_URL = "https://transmotec.com/product/LRS-75-12/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def asset_epoch() -> str:
    return _PROCESS_EPOCH


def asset_revision() -> dict[str, Any]:
    return {"epoch": _PROCESS_EPOCH, "generation": hardening.asset_generation()}


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _safe_remote_url_dns(url: str) -> bool:
    """Require HTTPS and public DNS results before the engine performs a remote fetch."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            return _is_public_address(host)
        except ValueError:
            pass
        try:
            records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            return False
        addresses = {str(record[4][0]).split("%", 1)[0] for record in records if record[4]}
        return bool(addresses) and all(_is_public_address(address) for address in addresses)
    except (ValueError, OSError):
        return False


def _read_response(response: Any) -> tuple[bytes, str, str]:
    final_url = str(response.geturl())
    if not _safe_remote_url_dns(final_url):
        raise ValueError(f"CAD download redirected to non-public URL: {final_url}")
    length = response.headers.get("Content-Length")
    if length and int(length) > _MAX_DOWNLOAD_BYTES:
        raise ValueError("Authoritative CAD asset exceeds 180 MB download limit")
    data = response.read(_MAX_DOWNLOAD_BYTES + 1)
    if len(data) > _MAX_DOWNLOAD_BYTES:
        raise ValueError("Authoritative CAD asset exceeds 180 MB download limit")
    content_type = str(response.headers.get("Content-Type") or "").lower()
    return data, final_url, content_type


def _opener_request(
    opener: Any,
    url: str,
    *,
    referer: str | None = None,
    timeout: int = 25,
    ajax: bool = False,
    retries_429: int = 1,
) -> tuple[bytes, str, str]:
    if not _safe_remote_url_dns(url):
        raise ValueError(f"Refusing non-public CAD URL: {url}")
    headers = dict(_BROWSER_HEADERS)
    headers["Accept"] = "application/zip,application/octet-stream,application/json,text/html,*/*;q=0.6"
    if referer:
        headers["Referer"] = referer
        origin = urlparse(referer)
        if origin.scheme and origin.netloc:
            headers["Origin"] = f"{origin.scheme}://{origin.netloc}"
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    request = urllib.request.Request(url, headers=headers)
    attempts = retries_429 + 1
    for attempt in range(attempts):
        try:
            with opener.open(request, timeout=timeout) as response:
                return _read_response(response)
        except HTTPError as exc:
            if exc.code != 429 or attempt + 1 >= attempts:
                raise
            retry_after = str(exc.headers.get("Retry-After") or "1").strip()
            try:
                delay = max(0.5, min(float(retry_after), 4.0))
            except ValueError:
                delay = 1.0
            time.sleep(delay)
    raise RuntimeError(f"Could not fetch CAD URL: {url}")


def _browser_request(url: str, *, timeout: int = 25) -> bytes:
    opener = urllib.request.build_opener()
    data, _, _ = _opener_request(opener, url, timeout=timeout)
    return data


def _strict_cad_links(page_url: str, payload: bytes, component: dict[str, Any]) -> list[str]:
    text = payload.decode("utf-8", errors="replace")
    parser = base._LinkParser()
    parser.feed(text)
    candidates: list[tuple[str, str]] = [
        (urljoin(page_url, href), label) for href, label in parser.links
    ]
    candidates.extend(hardening._embedded_urls(page_url, text))
    scored: list[tuple[int, str]] = []
    for url, label in candidates:
        if not _safe_remote_url_dns(url):
            continue
        path = urlparse(url).path.lower()
        lower = f"{url} {label}".lower()
        explicit_file = path.endswith((".step", ".stp", ".zip"))
        explicit_cad = bool(re.search(r"(?:\bstep\b|\bstp\b|3d\s*cad|3d\s*model)", lower))
        if not explicit_file and not explicit_cad:
            continue
        score = base._link_score(component, url, label)
        if explicit_file:
            score += 50
        if explicit_cad:
            score += 30
        scored.append((score, url))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return list(dict.fromkeys(url for _, url in scored[:12]))


def _discover_asset_links(page_url: str, component: dict[str, Any]) -> list[str]:
    payload = base._request(page_url)
    return _strict_cad_links(page_url, payload, component)


def _step_from_payload(data: bytes, url: str, content_type: str = "") -> tuple[bytes, str]:
    if data[:4] == b"PK\x03\x04" or urlparse(url).path.lower().endswith(".zip"):
        return base._step_from_zip_bytes(data), "zip"
    with tempfile.TemporaryDirectory(prefix="forgecad-v620-provider-") as temp_dir:
        path = Path(temp_dir) / "candidate.step"
        path.write_bytes(data)
        if base._looks_like_step(path):
            return data, "step"
    if "json" in content_type:
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
        except Exception:
            payload = None
        if payload is not None:
            raise ValueError(f"Vendor download returned JSON instead of STEP: {payload!r}")
    raise ValueError("CAD candidate is neither a STEP file nor a ZIP containing STEP")


def _metadata_for(
    component: dict[str, Any],
    source: base.CadSource,
    resolved_url: str,
    data: bytes,
    transport: str,
) -> dict[str, Any]:
    verification = base._validate_step_bytes(data, component_id=str(component.get("id") or ""))
    metadata = {
        "source_url": source.url,
        "resolved_url": resolved_url,
        "source_kind": source.kind,
        "geometry_fidelity": "official_step" if source.kind == "manufacturer" else "verified_step",
        "transport": transport,
        "verification": verification,
    }
    identity = hardening._verify_component_identity(
        component,
        verification,
        source_url=source.url,
        resolved_url=resolved_url,
        metadata=metadata,
        data=data,
    )
    metadata["identity_verification"] = identity
    return metadata


def _urls_from_json(payload: Any, page_url: str) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            found.extend(_urls_from_json(value, page_url))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(_urls_from_json(value, page_url))
    elif isinstance(payload, str):
        value = payload.strip()
        if ".step" in value.lower() or ".stp" in value.lower() or ".zip" in value.lower():
            candidate = urljoin(page_url, value)
            if _safe_remote_url_dns(candidate):
                found.append(candidate)
    return list(dict.fromkeys(found))


def _fetch_stepperonline(component: dict[str, Any], source: base.CadSource) -> tuple[bytes, dict[str, Any]]:
    """StepperOnline rejects a naked hotlink; preserve its product-page session."""
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page, page_final, _ = _opener_request(opener, _STEPPER_PRODUCT_URL, timeout=25, retries_429=0)
    links = _strict_cad_links(page_final, page, component)
    candidates = [
        url for url in links
        if "17hs19-2004s1" in re.sub(r"[^a-z0-9]+", "", url.lower()) and ".step" in url.lower()
    ]
    candidates.extend([_STEPPER_DIRECT_URL])
    errors: list[str] = []
    for candidate in list(dict.fromkeys(candidates)):
        try:
            data, final_url, content_type = _opener_request(
                opener,
                candidate,
                referer=page_final,
                timeout=25,
                ajax=True,
                retries_429=0,
            )
            if "json" in content_type or data.lstrip().startswith((b"{", b"[")):
                try:
                    payload = json.loads(data.decode("utf-8", errors="replace"))
                except Exception:
                    payload = None
                nested = _urls_from_json(payload, page_final) if payload is not None else []
                if nested:
                    for nested_url in nested:
                        nested_data, nested_final, nested_type = _opener_request(
                            opener,
                            nested_url,
                            referer=page_final,
                            timeout=25,
                            retries_429=0,
                        )
                        step, transport = _step_from_payload(nested_data, nested_final, nested_type)
                        return step, _metadata_for(component, source, nested_final, step, transport)
            step, transport = _step_from_payload(data, final_url, content_type)
            return step, _metadata_for(component, source, final_url, step, transport)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError("; ".join(errors) if errors else "StepperOnline exact STEP was not downloadable")


def _fetch_source(component: dict[str, Any], source: base.CadSource) -> tuple[bytes, dict[str, Any]]:
    if str(component.get("id") or "") == _STEPPER_COMPONENT_ID:
        try:
            return _fetch_stepperonline(component, source)
        except Exception as exc:
            hardening._record_failure(component, source, exc)
            raise
    return _HARDENED_FETCH_SOURCE(component, source)


def _source_overrides() -> None:
    # Exact manufacturer CDN asset. The product page itself currently returns 429 to
    # GitHub-hosted clients, while the CDN file is stable and linked by that page.
    base.AUTHORITATIVE_SOURCES[_NOCTUA_COMPONENT_ID] = (
        base.CadSource(
            _NOCTUA_CAD_URL,
            kind="manufacturer",
            direct=True,
            archive="zip",
            filename="NF-A4x10_Public-CAD.step",
            required_for_release=True,
        ),
    )

    # Mouser visibly lists an STP ZIP but serves the document list through client-side
    # behavior. Transmotec's exact LRS-75-12 product page exposes the same Mean Well
    # series CAD as an authorized distributor and is usable by the resolver.
    base.AUTHORITATIVE_SOURCES[_MEANWELL_COMPONENT_ID] = (
        base.CadSource(
            _TRANSMOTEC_LRS75_URL,
            kind="authorized_distributor",
            required_for_release=True,
        ),
        base.CadSource(
            "https://www.mouser.com/ProductDetail/MEAN-WELL/LRS-75-12",
            kind="authorized_distributor",
            required_for_release=True,
        ),
    )

    # Keep the exact StepperOnline page as the provenance binding. The special adapter
    # above performs the session-preserving STEP request.
    base.AUTHORITATIVE_SOURCES[_STEPPER_COMPONENT_ID] = (
        base.CadSource(_STEPPER_PRODUCT_URL, kind="manufacturer", required_for_release=True),
    )


def install() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        hardening.install()
        _source_overrides()
        base._safe_remote_url = _safe_remote_url_dns
        base._request = _browser_request
        base._discover_asset_links = _discover_asset_links
        base._fetch_source = _fetch_source
        _INSTALLED = True


def prefetch(*, required_only: bool = False, root: Path = base.PACKAGE_ASSET_DIR, strict: bool = False) -> dict[str, Any]:
    install()
    hardening._SOURCE_FAILURES.clear()
    result = hardening.prefetch(required_only=required_only, root=root, strict=False)
    failures = dict(result.get("failures") or {})
    for component_id in list(failures):
        detail = hardening._SOURCE_FAILURES.get(component_id)
        if detail:
            failures[component_id] = " | ".join(detail)
    result["failures"] = failures
    result["ok"] = not failures
    result["asset_revision"] = asset_revision()
    if strict and failures:
        raise RuntimeError("Authoritative CAD prefetch failed: " + json.dumps(failures, sort_keys=True))
    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="ForgeCAD 6.2 robust purchased-component CAD providers")
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
