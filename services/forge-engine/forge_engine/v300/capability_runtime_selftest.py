from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile

from .capability_runtime import CapabilityBinding, CapabilityRuntime
from .world_model import PhysicalWorldStore, ProvenanceRecord, ROOT_WORLD_ID, WorldCapability, WorldEntity


async def run_async() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        world = PhysicalWorldStore(root / "world.json")
        relay = world.upsert_entity(
            WorldEntity(
                id="device:test-relay",
                name="Test Relay",
                kind="actuator",
                parent_id=ROOT_WORLD_ID,
                capabilities=[WorldCapability(name="actuator.relay", mode="actuate")],
                provenance=[ProvenanceRecord(source="human", source_id="selftest", authoritative=True)],
            ),
            source="human",
        )
        runtime = CapabilityRuntime(world, root / "capabilities.json")

        calls: list[dict[str, object]] = []

        async def fake_adapter(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "state": kwargs["args"]["state"]}

        runtime.register_adapter("selftest-relay", fake_adapter)
        binding = runtime.bind(
            CapabilityBinding(
                entity_id=relay.id,
                capability="actuator.relay",
                operation="set",
                adapter_id="selftest-relay",
                risk="physical",
                requires_confirmation=False,
                argument_contract={"required": ["state"], "allowed": ["state"]},
            )
        )
        assert binding.requires_confirmation is True, "physical action must force confirmation"

        missing_rejected = False
        try:
            runtime.plan(entity_id=relay.id, capability="actuator.relay", operation="set", args={})
        except ValueError:
            missing_rejected = True
        assert missing_rejected

        action, token = runtime.plan(
            entity_id=relay.id,
            capability="actuator.relay",
            operation="set",
            args={"state": True},
            requested_by="jarvis-selftest",
        )
        assert action.status == "awaiting_confirmation"
        assert token

        unconfirmed_rejected = False
        try:
            await runtime.execute(action.id)
        except PermissionError:
            unconfirmed_rejected = True
        assert unconfirmed_rejected
        assert not calls

        wrong_token_rejected = False
        try:
            runtime.confirm(action.id, "wrong-token")
        except PermissionError:
            wrong_token_rejected = True
        assert wrong_token_rejected

        confirmed = runtime.confirm(action.id, token, confirmed_by="human-selftest")
        assert confirmed.status == "confirmed"
        completed = await runtime.execute(action.id)
        assert completed.status == "completed", completed
        assert completed.result == {"ok": True, "state": True}
        assert len(calls) == 1

        unbound_rejected = False
        try:
            runtime.plan(entity_id=relay.id, capability="actuator.relay", operation="pulse", args={})
        except KeyError:
            unbound_rejected = True
        assert unbound_rejected

        # Plan another physical action but deliberately do not confirm it. Confirmation
        # tokens are memory-only secrets, so a runtime restart must cancel rather than
        # resurrect an apparently actionable physical command.
        pending, pending_token = runtime.plan(
            entity_id=relay.id,
            capability="actuator.relay",
            operation="set",
            args={"state": False},
            requested_by="jarvis-selftest",
        )
        assert pending.status == "awaiting_confirmation"
        assert pending_token

        reloaded = CapabilityRuntime(world, root / "capabilities.json")
        assert reloaded.action(action.id).status == "completed"
        assert reloaded.bindings(entity_id=relay.id)[0].id == binding.id
        expired = reloaded.action(pending.id)
        assert expired.status == "cancelled", expired
        assert expired.error == "confirmation_expired_on_restart", expired
        assert expired.metadata.get("recovery") == "fail_closed_restart", expired

        return {
            "capability_runtime_selftest": "PASS",
            "physical_confirmation_forced": True,
            "unconfirmed_execution_rejected": unconfirmed_rejected,
            "wrong_confirmation_rejected": wrong_token_rejected,
            "argument_contract_enforced": missing_rejected,
            "unbound_action_rejected": unbound_rejected,
            "pending_physical_action_expired_on_restart": True,
            "adapter_invocations": len(calls),
            "audit_persisted": True,
        }


def run() -> dict[str, object]:
    return asyncio.run(run_async())


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
