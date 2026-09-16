from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ..main_v3 import app


def run() -> dict[str, object]:
    with TestClient(app) as client:
        health = client.get("/v3/health")
        assert health.status_code == 200, health.text
        health_body = health.json()
        assert health_body["api_version"] == "3", health_body
        assert health_body["engine_version"] == "3.0.0", health_body
        assert health_body["world_model_schema_version"] == 1, health_body
        assert health_body["project_sync"]["ok"] is True, health_body
        assert "capability_runtime" in health_body, health_body

        context = client.get("/v3/jarvis/context")
        assert context.status_code == 200, context.text
        context_body = context.json()
        assert context_body["world"]["entity_count"] >= 7, context_body
        assert any(
            row["source_links"].get("component_ref") == "compute.raspberry_pi_5_8gb"
            for row in context_body["entities"]
        ), context_body

        compute = client.get("/v3/world/entities", params={"capability": "compute.execute"})
        assert compute.status_code == 200, compute.text
        compute_rows = compute.json()["items"]
        assert compute_rows, compute.json()
        pi = next(
            row
            for row in compute_rows
            if row["source_links"].get("component_ref") == "compute.raspberry_pi_5_8gb"
        )

        exact_resolution = client.get("/v3/jarvis/resolve", params={"q": pi["id"]})
        assert exact_resolution.status_code == 200, exact_resolution.text
        assert exact_resolution.json()["status"] == "resolved", exact_resolution.json()
        assert exact_resolution.json()["entity_id"] == pi["id"], exact_resolution.json()

        observation = client.post(
            "/v3/world/observations",
            json={
                "entity_id": pi["id"],
                "key": "cpu_temperature_c",
                "value": 46.25,
                "unit": "degC",
                "source": "sensor",
                "source_id": "selftest:pi-temp",
                "confidence": 0.99,
            },
        )
        assert observation.status_code == 200, observation.text
        assert observation.json()["sample"]["value"] == 46.25

        fetched = client.get(f"/v3/world/entities/{pi['id']}")
        assert fetched.status_code == 200, fetched.text
        fetched_pi = fetched.json()
        assert fetched_pi["live_state"]["cpu_temperature_c"]["source_id"] == "selftest:pi-temp"
        assert fetched_pi["metadata"]["designed_transform_mm"], fetched_pi

        sync = client.post("/v3/world/sync-project", json={})
        assert sync.status_code == 200, sync.text
        assert sync.json()["ok"] is True

        relations = client.get("/v3/world/relations")
        assert relations.status_code == 200, relations.text
        assert relations.json()["count"] >= 5, relations.json()

        before_events = client.get("/v3/world/events", params={"limit": 1000})
        assert before_events.status_code == 200, before_events.text
        before_body = before_events.json()
        before_last = before_body["last_event_id"]
        assert before_last, before_body

        # Exercise the public Jarvis action boundary. Adapters are intentionally not
        # registerable over HTTP; trusted host code owns them. The API can bind a world
        # capability to a configured adapter ID, but physical execution still requires
        # an explicit confirmation transition and then a live trusted adapter.
        relay_id = "device:api-selftest-relay"
        relay = client.post(
            "/v3/world/entities",
            json={
                "id": relay_id,
                "name": "API Self-test Relay",
                "kind": "actuator",
                "parent_id": "world:local",
                "capabilities": [{"name": "actuator.relay", "mode": "actuate"}],
                "provenance": [
                    {
                        "source": "human",
                        "source_id": "v300-api-selftest",
                        "confidence": 1.0,
                        "authoritative": True,
                    }
                ],
            },
        )
        assert relay.status_code == 200, relay.text

        incremental_events = client.get(
            "/v3/world/events",
            params={"after_id": before_last, "limit": 50},
        )
        assert incremental_events.status_code == 200, incremental_events.text
        incremental_body = incremental_events.json()
        assert incremental_body["count"] >= 1, incremental_body
        assert any(row["entity_id"] == relay_id for row in incremental_body["items"]), incremental_body

        unique_name = client.get("/v3/jarvis/resolve", params={"q": "API Self-test Relay"})
        assert unique_name.status_code == 200, unique_name.text
        assert unique_name.json()["status"] == "resolved", unique_name.json()
        assert unique_name.json()["entity_id"] == relay_id, unique_name.json()

        duplicate_id = "device:api-selftest-relay-2"
        duplicate = client.post(
            "/v3/world/entities",
            json={
                "id": duplicate_id,
                "name": "API Self-test Relay",
                "kind": "actuator",
                "parent_id": "world:local",
                "capabilities": [{"name": "actuator.relay", "mode": "actuate"}],
                "provenance": [
                    {
                        "source": "human",
                        "source_id": "v300-api-selftest-2",
                        "confidence": 1.0,
                        "authoritative": True,
                    }
                ],
            },
        )
        assert duplicate.status_code == 200, duplicate.text
        ambiguous = client.get("/v3/jarvis/resolve", params={"q": "API Self-test Relay"})
        assert ambiguous.status_code == 200, ambiguous.text
        assert ambiguous.json()["status"] == "ambiguous", ambiguous.json()
        assert ambiguous.json()["entity_id"] is None, ambiguous.json()
        assert len(ambiguous.json()["candidates"]) == 2, ambiguous.json()

        binding = client.post(
            "/v3/capabilities/bindings",
            json={
                "entity_id": relay_id,
                "capability": "actuator.relay",
                "operation": "set",
                "adapter_id": "selftest-unregistered-adapter",
                "risk": "physical",
                "requires_confirmation": False,
                "argument_contract": {"required": ["state"], "allowed": ["state"]},
            },
        )
        assert binding.status_code == 200, binding.text
        binding_body = binding.json()
        assert binding_body["requires_confirmation"] is True, binding_body

        planned = client.post(
            "/v3/actions/plan",
            json={
                "entity_id": relay_id,
                "capability": "actuator.relay",
                "operation": "set",
                "args": {"state": True},
                "requested_by": "jarvis-api-selftest",
            },
        )
        assert planned.status_code == 200, planned.text
        planned_body = planned.json()
        action_id = planned_body["action"]["id"]
        confirmation_token = planned_body["confirmation_token"]
        assert planned_body["action"]["status"] == "awaiting_confirmation", planned_body
        assert confirmation_token, planned_body

        blocked = client.post(f"/v3/actions/{action_id}/execute")
        assert blocked.status_code == 403, blocked.text

        confirmed = client.post(
            f"/v3/actions/{action_id}/confirm",
            json={"confirmation_token": confirmation_token, "confirmed_by": "human-api-selftest"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed", confirmed.json()

        # Confirmation alone is not enough to invent hardware control. With no trusted
        # adapter registered in-process, execution must still fail closed.
        no_adapter = client.post(f"/v3/actions/{action_id}/execute")
        assert no_adapter.status_code == 409, no_adapter.text
        assert "not registered" in no_adapter.text.lower(), no_adapter.text

        action_list = client.get("/v3/actions", params={"entity_id": relay_id})
        assert action_list.status_code == 200, action_list.text
        assert action_list.json()["count"] == 1, action_list.json()

        return {
            "v300_api_selftest": "PASS",
            "engine_version": health_body["engine_version"],
            "world_entities": context_body["world"]["entity_count"],
            "world_relations": relations.json()["count"],
            "compute_entity": pi["id"],
            "observation_roundtrip": True,
            "project_sync": True,
            "incremental_world_events": True,
            "exact_identity_resolution": True,
            "ambiguous_identity_failed_closed": True,
            "physical_action_confirmation_boundary": True,
            "unregistered_adapter_failed_closed": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
