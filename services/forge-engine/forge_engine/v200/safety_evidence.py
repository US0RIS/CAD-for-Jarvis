from __future__ import annotations

"""Include safety verification records in ForgeCAD's unified evidence listing."""

from copy import deepcopy
from typing import Any, Callable

from ..v110 import core
from . import physical_evidence


_INSTALLED = False
_ORIGINAL_EVIDENCE_ROWS: Callable[..., list[dict[str, Any]]] | None = None


def _evidence_rows(kind: str | None = None) -> list[dict[str, Any]]:
    assert _ORIGINAL_EVIDENCE_ROWS is not None
    base = _ORIGINAL_EVIDENCE_ROWS(None)
    known_ids = {str(row.get("id") or "") for row in base if isinstance(row, dict)}
    current = physical_evidence.design_fingerprint()
    rows = list(base)
    for raw in core.PROJECT.get("notebook") or []:
        if not isinstance(raw, dict) or raw.get("kind") != "failure_mode_verification":
            continue
        if str(raw.get("id") or "") in known_ids:
            continue
        row = deepcopy(raw)
        fingerprint = str(row.get("design_fingerprint") or "")
        row["applies_to_current_design"] = bool(fingerprint and fingerprint == current)
        row["evidence_binding"] = "current" if row["applies_to_current_design"] else "stale" if fingerprint else "legacy_unbound"
        rows.append(row)
    if kind:
        rows = [row for row in rows if row.get("kind") == kind]
    return rows


def install() -> None:
    global _INSTALLED, _ORIGINAL_EVIDENCE_ROWS
    if _INSTALLED:
        return
    _ORIGINAL_EVIDENCE_ROWS = physical_evidence.evidence_rows
    physical_evidence.evidence_rows = _evidence_rows
    _INSTALLED = True
