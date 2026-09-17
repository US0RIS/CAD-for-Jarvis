from __future__ import annotations

"""Keep v2 electrical net metadata transactional with the v1.1 undo/redo ledger.

The v1.1 connect operation records its history snapshot before the v2 electrical layer
adds canonical net metadata. Without synchronizing that just-created snapshot, undoing
the *next* engineering operation could restore the connection while silently dropping
its net name/class/voltage. This adapter keeps the authoritative history state identical
to the persisted project state without adding a second user-visible undo step.
"""

from copy import deepcopy
from typing import Any, Callable

from ..v110 import core


_INSTALLED = False
_PREVIOUS_EXECUTE: Callable[..., dict[str, Any]] | None = None
_NET_FIELDS = ("net_name", "net_class", "nominal_voltage_v")


def _sync_latest_history(connection_ids: set[str]) -> None:
    if not connection_ids or not core.HISTORY:
        return
    current = {
        str(connection.get("id") or ""): connection
        for connection in core.PROJECT.get("connections") or []
        if isinstance(connection, dict) and str(connection.get("id") or "") in connection_ids
    }
    if not current:
        return
    snapshot = core.HISTORY[-1]
    history_connections = snapshot.get("connections") or []
    for index, connection in enumerate(history_connections):
        if not isinstance(connection, dict):
            continue
        connection_id = str(connection.get("id") or "")
        if connection_id not in current:
            continue
        # Replace the complete connection record. This also protects future v2
        # connection metadata from being forgotten when more fields are introduced.
        history_connections[index] = deepcopy(current[connection_id])


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    assert _PREVIOUS_EXECUTE is not None
    payload = deepcopy(args or {})
    before = {
        str(connection.get("id") or "")
        for connection in core.PROJECT.get("connections") or []
        if isinstance(connection, dict)
    } if op == "connect_interfaces" else set()

    result = _PREVIOUS_EXECUTE(op, payload, actor=actor, reason=reason)

    if op == "connect_interfaces" and any(key in payload for key in _NET_FIELDS):
        after = {
            str(connection.get("id") or "")
            for connection in core.PROJECT.get("connections") or []
            if isinstance(connection, dict)
        }
        with core.LOCK:
            _sync_latest_history(after - before)
            core.persist()
    return result


def install() -> None:
    global _INSTALLED, _PREVIOUS_EXECUTE
    if _INSTALLED:
        return
    _PREVIOUS_EXECUTE = core.execute
    core.execute = _execute
    _INSTALLED = True
