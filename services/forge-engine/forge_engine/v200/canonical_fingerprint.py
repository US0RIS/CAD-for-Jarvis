from __future__ import annotations

"""Extend physical-evidence binding to v2 canonical route and safety state.

Older designs without routes/failure modes retain the legacy fingerprint so existing
physical evidence is not invalidated merely by installing a newer ForgeCAD build. Once
a project uses either v2 domain, those records become part of the evidence binding.
Verification observations themselves are excluded from the failure-mode fingerprint so
recording evidence does not immediately invalidate that evidence.
"""

from copy import deepcopy
import hashlib
import json
from typing import Any, Callable

from . import physical_evidence


_INSTALLED = False
_ORIGINAL_FINGERPRINT: Callable[..., str] | None = None


def _failure_mode_input(raw: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(raw)
    row.pop("verification_evidence", None)
    row.pop("verification_status", None)
    row.pop("last_verified_at", None)
    return row


def _fingerprint(project: dict[str, Any] | None = None) -> str:
    assert _ORIGINAL_FINGERPRINT is not None
    legacy = _ORIGINAL_FINGERPRINT(project)
    source = project if project is not None else physical_evidence.core.PROJECT
    routes = deepcopy(source.get("routes") or [])
    failure_modes = [
        _failure_mode_input(row)
        for row in source.get("failure_modes") or []
        if isinstance(row, dict)
    ]
    if not routes and not failure_modes:
        return legacy
    extension = json.dumps(
        {"routes": routes, "failure_modes": failure_modes},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(f"{legacy}\n{extension}".encode("utf-8")).hexdigest()


def install() -> None:
    global _INSTALLED, _ORIGINAL_FINGERPRINT
    if _INSTALLED:
        return
    _ORIGINAL_FINGERPRINT = physical_evidence.design_fingerprint
    physical_evidence.design_fingerprint = _fingerprint
    _INSTALLED = True
