from __future__ import annotations

import json
from pathlib import Path
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from .world_event_stream import install_world_event_stream
from .world_model import PhysicalWorldStore, ProvenanceRecord, ROOT_WORLD_ID, WorldEntity


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        world = PhysicalWorldStore(Path(temp_dir) / "world.json")
        app = FastAPI()
        install_world_event_stream(app, world, session_token="stream-selftest", poll_interval_s=0.01)

        device = world.upsert_entity(
            WorldEntity(
                id="device:stream-selftest",
                name="Stream Self-test Device",
                kind="device",
                parent_id=ROOT_WORLD_ID,
                provenance=[ProvenanceRecord(source="human", source_id="stream-selftest", authoritative=True)],
            ),
            source="human",
        )
        cursor = world.snapshot().events[-1].id

        with TestClient(app) as client:
            # Reconnect/catch-up semantics: an event recorded after the cursor is sent
            # immediately after the subscription acknowledgement.
            world.observe(
                entity_id=device.id,
                key="state",
                value="idle",
                source="sensor",
                source_id="stream-selftest-sensor",
            )
            with client.websocket_connect(
                f"/v3/world/events/ws?token=stream-selftest&after_id={cursor}"
            ) as websocket:
                subscribed = websocket.receive_json()
                assert subscribed["type"] == "world.subscribed", subscribed
                assert subscribed["catchup_count"] == 1, subscribed
                catchup = websocket.receive_json()
                assert catchup["type"] == "world.event", catchup
                assert catchup["event"]["type"] == "observation.recorded", catchup
                assert catchup["event"]["entity_id"] == device.id, catchup

                world.observe(
                    entity_id=device.id,
                    key="state",
                    value="active",
                    source="sensor",
                    source_id="stream-selftest-sensor",
                )
                pushed = websocket.receive_json()
                assert pushed["type"] == "world.event", pushed
                assert pushed["event"]["payload"]["key"] == "state", pushed

            # No cursor means start from now instead of replaying the retained log.
            with client.websocket_connect("/v3/world/events/ws?token=stream-selftest") as websocket:
                subscribed = websocket.receive_json()
                assert subscribed["type"] == "world.subscribed"
                assert subscribed["catchup_count"] == 0
                world.observe(
                    entity_id=device.id,
                    key="temperature_c",
                    value=31.5,
                    unit="degC",
                    source="sensor",
                    source_id="stream-selftest-temp",
                )
                pushed = websocket.receive_json()
                assert pushed["event"]["payload"]["key"] == "temperature_c", pushed

            unauthorized_rejected = False
            try:
                with client.websocket_connect("/v3/world/events/ws?token=wrong-token") as websocket:
                    websocket.receive_json()
            except WebSocketDisconnect as exc:
                unauthorized_rejected = exc.code == 4401
            assert unauthorized_rejected

            missing_cursor_rejected = False
            try:
                with client.websocket_connect(
                    "/v3/world/events/ws?token=stream-selftest&after_id=definitely-not-retained"
                ) as websocket:
                    reset = websocket.receive_json()
                    assert reset["type"] == "world.reset_required", reset
                    websocket.receive_json()
            except WebSocketDisconnect as exc:
                missing_cursor_rejected = exc.code == 4409
            assert missing_cursor_rejected

        return {
            "world_event_stream_selftest": "PASS",
            "authenticated": True,
            "catchup_from_event_cursor": True,
            "live_push": True,
            "starts_at_now_without_cursor": True,
            "invalid_session_rejected": unauthorized_rejected,
            "expired_cursor_requires_snapshot_reset": missing_cursor_rejected,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
