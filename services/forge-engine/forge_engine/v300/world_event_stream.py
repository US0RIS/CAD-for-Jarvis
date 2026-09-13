from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from .world_model import PhysicalWorldStore


WORLD_EVENT_WS_PATH = "/v3/world/events/ws"


def _events_after(snapshot, after_id: str | None) -> tuple[list[Any], bool]:
    events = list(snapshot.events)
    if not after_id:
        return [], True
    for index, event in enumerate(events):
        if event.id == after_id:
            return events[index + 1 :], True
    return [], False


def install_world_event_stream(
    app: FastAPI,
    world: PhysicalWorldStore,
    *,
    session_token: str = "",
    jarvis_token_verifier: Callable[[str], bool] | None = None,
    poll_interval_s: float = 0.20,
) -> None:
    """Install an authenticated push stream for bounded physical-world events.

    The world store remains synchronous and deterministic; this transport tails its
    bounded event log. Clients may reconnect with ``after_id`` to receive any retained
    events they missed. If that cursor has aged out, the stream emits
    ``world.reset_required`` and closes so the client refreshes `/v3/world` rather than
    silently skipping physical-world changes.
    """

    if getattr(app.state, "forgecad_v300_world_event_stream", False):
        return
    app.state.forgecad_v300_world_event_stream = True

    router = APIRouter()

    @router.websocket(WORLD_EVENT_WS_PATH)
    async def world_event_stream(websocket: WebSocket) -> None:
        supplied_session = websocket.query_params.get("token", "")
        supplied_jarvis = websocket.query_params.get("jarvis_token", "")
        authenticated = not session_token
        if session_token and supplied_session == session_token:
            authenticated = True
        if not authenticated and supplied_jarvis and jarvis_token_verifier is not None:
            try:
                authenticated = bool(jarvis_token_verifier(supplied_jarvis))
            except Exception:
                authenticated = False
        if not authenticated:
            await websocket.close(code=4401)
            return

        after_id = websocket.query_params.get("after_id") or None
        await websocket.accept()

        snapshot = world.snapshot()
        catchup, cursor_valid = _events_after(snapshot, after_id)
        if after_id and not cursor_valid:
            await websocket.send_json(
                {
                    "type": "world.reset_required",
                    "revision": snapshot.revision,
                    "reason": "event_cursor_not_retained",
                }
            )
            await websocket.close(code=4409)
            return

        last_event_id = after_id
        if not after_id and snapshot.events:
            # A subscription without a cursor starts at "now". The current snapshot is
            # the initial state; subsequent frames are changes after this point.
            last_event_id = snapshot.events[-1].id

        await websocket.send_json(
            {
                "type": "world.subscribed",
                "revision": snapshot.revision,
                "last_event_id": last_event_id,
                "catchup_count": len(catchup),
            }
        )

        for event in catchup:
            await websocket.send_json(
                {
                    "type": "world.event",
                    "revision": snapshot.revision,
                    "event": event.model_dump(mode="json"),
                }
            )
            last_event_id = event.id

        try:
            while True:
                await asyncio.sleep(max(0.05, float(poll_interval_s)))
                snapshot = world.snapshot()
                pending, cursor_valid = _events_after(snapshot, last_event_id)
                if last_event_id and not cursor_valid:
                    await websocket.send_json(
                        {
                            "type": "world.reset_required",
                            "revision": snapshot.revision,
                            "reason": "event_cursor_not_retained",
                        }
                    )
                    await websocket.close(code=4409)
                    return
                for event in pending:
                    await websocket.send_json(
                        {
                            "type": "world.event",
                            "revision": snapshot.revision,
                            "event": event.model_dump(mode="json"),
                        }
                    )
                    last_event_id = event.id
        except WebSocketDisconnect:
            return

    app.include_router(router)
