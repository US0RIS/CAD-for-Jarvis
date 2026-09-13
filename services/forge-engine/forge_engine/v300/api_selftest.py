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

        context = client.get("/v3/jarvis/context")
        assert context.status_code == 200, context.text
        context_body = context.json()
        assert context_body["world"]["entity_count"] >= 7, context_body
        assert any(row["source_links"].get("component_ref") == "compute.raspberry_pi_5_8gb" for row in context_body["entities"]), context_body

        compute = client.get("/v3/world/entities", params={"capability": "compute.execute"})
        assert compute.status_code == 200, compute.text
        compute_rows = compute.json()["items"]
        assert compute_rows, compute.json()
        pi = next(row for row in compute_rows if row["source_links"].get("component_ref") == "compute.raspberry_pi_5_8gb")

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

        return {
            "v300_api_selftest": "PASS",
            "engine_version": health_body["engine_version"],
            "world_entities": context_body["world"]["entity_count"],
            "world_relations": relations.json()["count"],
            "compute_entity": pi["id"],
            "observation_roundtrip": True,
            "project_sync": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
