from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import secrets
from threading import RLock
from typing import Any, Awaitable, Callable, Protocol
import uuid

from pydantic import BaseModel, Field

from .world_model import PhysicalWorldStore


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_path() -> Path:
    configured = os.environ.get("FORGECAD_DATA_DIR", "").strip()
    if configured:
        root = Path(configured)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ForgeCAD"
    elif __import__("sys").platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "ForgeCAD"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "forgecad"
    root.mkdir(parents=True, exist_ok=True)
    return root / "capability-runtime-v1.json"


class CapabilityBinding(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    entity_id: str
    capability: str
    operation: str
    adapter_id: str
    risk: str = "read"
    requires_confirmation: bool = False
    enabled: bool = True
    argument_contract: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class CapabilityAction(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    entity_id: str
    capability: str
    operation: str
    binding_id: str
    adapter_id: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk: str
    requires_confirmation: bool
    status: str = "planned"
    planned_at: str = Field(default_factory=now_iso)
    confirmed_at: str | None = None
    executed_at: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    requested_by: str = "jarvis"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityRuntimeSnapshot(BaseModel):
    schema_version: int = 1
    bindings: list[CapabilityBinding] = Field(default_factory=list)
    actions: list[CapabilityAction] = Field(default_factory=list)


class CapabilityAdapter(Protocol):
    id: str

    async def invoke(
        self,
        *,
        entity_id: str,
        capability: str,
        operation: str,
        args: dict[str, Any],
        binding: CapabilityBinding,
    ) -> dict[str, Any]: ...


@dataclass
class _RegisteredAdapter:
    id: str
    invoke_fn: Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]

    async def invoke(
        self,
        *,
        entity_id: str,
        capability: str,
        operation: str,
        args: dict[str, Any],
        binding: CapabilityBinding,
    ) -> dict[str, Any]:
        result = self.invoke_fn(
            entity_id=entity_id,
            capability=capability,
            operation=operation,
            args=args,
            binding=binding,
        )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError("Capability adapter must return a JSON object")
        return result


class CapabilityRuntime:
    """Typed, fail-closed action broker between Jarvis and device adapters.

    The runtime intentionally separates four concerns:

    * the world model says what an entity *is* and claims it *can do*;
    * a binding says which concrete adapter owns one operation;
    * an action is a durable audit record of an attempted invocation;
    * confirmation is a distinct state transition for physical/high-consequence work.

    A model cannot bypass these checks by inventing an adapter name or capability.
    """

    PHYSICAL_RISKS = {"physical", "high_consequence"}
    VALID_RISKS = {"read", "software", "physical", "high_consequence"}
    VALID_ACTION_STATES = {
        "planned",
        "awaiting_confirmation",
        "confirmed",
        "executing",
        "completed",
        "failed",
        "cancelled",
    }

    def __init__(
        self,
        world: PhysicalWorldStore,
        path: str | Path | None = None,
        *,
        autosave: bool = True,
        max_actions: int = 500,
    ) -> None:
        self.world = world
        self.path = Path(path) if path is not None else _runtime_path()
        self.autosave = autosave
        self.max_actions = max(20, int(max_actions))
        self._lock = RLock()
        self._bindings: dict[str, CapabilityBinding] = {}
        self._actions: dict[str, CapabilityAction] = {}
        self._action_order: list[str] = []
        self._confirmation_hashes: dict[str, str] = {}
        self._adapters: dict[str, _RegisteredAdapter] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            snapshot = CapabilityRuntimeSnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        self._bindings = {row.id: row for row in snapshot.bindings}
        self._actions = {row.id: row for row in snapshot.actions}
        self._action_order = [row.id for row in snapshot.actions]

    def _persist(self) -> None:
        if not self.autosave:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self.snapshot()
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(self.path)

    def snapshot(self) -> CapabilityRuntimeSnapshot:
        with self._lock:
            return CapabilityRuntimeSnapshot(
                bindings=[row.model_copy(deep=True) for row in self._bindings.values()],
                actions=[self._actions[action_id].model_copy(deep=True) for action_id in self._action_order if action_id in self._actions],
            )

    def register_adapter(
        self,
        adapter_id: str,
        invoke_fn: Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]],
    ) -> None:
        adapter_id = str(adapter_id).strip()
        if not adapter_id:
            raise ValueError("adapter_id is required")
        with self._lock:
            self._adapters[adapter_id] = _RegisteredAdapter(id=adapter_id, invoke_fn=invoke_fn)

    def unregister_adapter(self, adapter_id: str) -> None:
        with self._lock:
            self._adapters.pop(adapter_id, None)

    def adapters(self) -> list[str]:
        with self._lock:
            return sorted(self._adapters)

    def _entity_has_capability(self, entity_id: str, capability: str) -> bool:
        entity = self.world.entity(entity_id)
        return any(row.name == capability for row in entity.capabilities)

    def bind(self, binding: CapabilityBinding) -> CapabilityBinding:
        if binding.risk not in self.VALID_RISKS:
            raise ValueError(f"Unsupported capability risk: {binding.risk}")
        if not self._entity_has_capability(binding.entity_id, binding.capability):
            raise ValueError(f"Entity {binding.entity_id} does not expose capability {binding.capability}")
        candidate = binding.model_copy(deep=True)
        if candidate.risk in self.PHYSICAL_RISKS:
            candidate.requires_confirmation = True
        with self._lock:
            existing = self._bindings.get(candidate.id)
            candidate.created_at = existing.created_at if existing else candidate.created_at
            candidate.updated_at = now_iso()
            self._bindings[candidate.id] = candidate
            self._persist()
            return candidate.model_copy(deep=True)

    def unbind(self, binding_id: str) -> None:
        with self._lock:
            if binding_id not in self._bindings:
                raise KeyError(binding_id)
            self._bindings.pop(binding_id)
            self._persist()

    def bindings(
        self,
        *,
        entity_id: str | None = None,
        capability: str | None = None,
        operation: str | None = None,
    ) -> list[CapabilityBinding]:
        with self._lock:
            rows = list(self._bindings.values())
            if entity_id is not None:
                rows = [row for row in rows if row.entity_id == entity_id]
            if capability is not None:
                rows = [row for row in rows if row.capability == capability]
            if operation is not None:
                rows = [row for row in rows if row.operation == operation]
            return [row.model_copy(deep=True) for row in rows]

    def _binding_for(self, entity_id: str, capability: str, operation: str) -> CapabilityBinding:
        matches = [
            row
            for row in self._bindings.values()
            if row.enabled
            and row.entity_id == entity_id
            and row.capability == capability
            and row.operation == operation
        ]
        if not matches:
            raise KeyError(f"No enabled binding for {entity_id} {capability}.{operation}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous capability binding for {entity_id} {capability}.{operation}")
        return matches[0]

    def _validate_arguments(self, binding: CapabilityBinding, args: dict[str, Any]) -> None:
        contract = binding.argument_contract or {}
        required = contract.get("required") or []
        if not isinstance(required, list):
            raise ValueError("binding argument_contract.required must be a list")
        missing = [str(key) for key in required if str(key) not in args]
        if missing:
            raise ValueError(f"Missing required capability arguments: {', '.join(missing)}")
        allowed = contract.get("allowed")
        if isinstance(allowed, list):
            allowed_keys = {str(key) for key in allowed}
            unknown = sorted(str(key) for key in args if str(key) not in allowed_keys)
            if unknown:
                raise ValueError(f"Unknown capability arguments: {', '.join(unknown)}")

    def _trim_actions(self) -> None:
        while len(self._action_order) > self.max_actions:
            oldest = self._action_order.pop(0)
            self._actions.pop(oldest, None)
            self._confirmation_hashes.pop(oldest, None)

    def plan(
        self,
        *,
        entity_id: str,
        capability: str,
        operation: str,
        args: dict[str, Any] | None = None,
        requested_by: str = "jarvis",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[CapabilityAction, str | None]:
        if not self._entity_has_capability(entity_id, capability):
            raise ValueError(f"Entity {entity_id} does not expose capability {capability}")
        with self._lock:
            binding = self._binding_for(entity_id, capability, operation)
            payload = dict(args or {})
            self._validate_arguments(binding, payload)
            action = CapabilityAction(
                entity_id=entity_id,
                capability=capability,
                operation=operation,
                binding_id=binding.id,
                adapter_id=binding.adapter_id,
                args=payload,
                risk=binding.risk,
                requires_confirmation=binding.requires_confirmation,
                status="awaiting_confirmation" if binding.requires_confirmation else "planned",
                requested_by=requested_by,
                metadata=metadata or {},
            )
            confirmation_token: str | None = None
            if binding.requires_confirmation:
                confirmation_token = secrets.token_urlsafe(24)
                self._confirmation_hashes[action.id] = hashlib.sha256(confirmation_token.encode("utf-8")).hexdigest()
            self._actions[action.id] = action
            self._action_order.append(action.id)
            self._trim_actions()
            self._persist()
            return action.model_copy(deep=True), confirmation_token

    def action(self, action_id: str) -> CapabilityAction:
        with self._lock:
            if action_id not in self._actions:
                raise KeyError(action_id)
            return self._actions[action_id].model_copy(deep=True)

    def actions(self, *, entity_id: str | None = None, status: str | None = None) -> list[CapabilityAction]:
        with self._lock:
            rows = [self._actions[action_id] for action_id in self._action_order if action_id in self._actions]
            if entity_id is not None:
                rows = [row for row in rows if row.entity_id == entity_id]
            if status is not None:
                rows = [row for row in rows if row.status == status]
            return [row.model_copy(deep=True) for row in rows]

    def confirm(self, action_id: str, confirmation_token: str, *, confirmed_by: str = "human") -> CapabilityAction:
        with self._lock:
            if action_id not in self._actions:
                raise KeyError(action_id)
            action = self._actions[action_id]
            if not action.requires_confirmation:
                if action.status == "planned":
                    action.status = "confirmed"
                    action.confirmed_at = now_iso()
                    action.metadata["confirmed_by"] = confirmed_by
                    self._persist()
                return action.model_copy(deep=True)
            if action.status != "awaiting_confirmation":
                raise ValueError(f"Action is not awaiting confirmation: {action.status}")
            expected = self._confirmation_hashes.get(action_id)
            supplied = hashlib.sha256(str(confirmation_token).encode("utf-8")).hexdigest()
            if not expected or not secrets.compare_digest(expected, supplied):
                raise PermissionError("Invalid capability-action confirmation token")
            action.status = "confirmed"
            action.confirmed_at = now_iso()
            action.metadata["confirmed_by"] = confirmed_by
            self._confirmation_hashes.pop(action_id, None)
            self._persist()
            return action.model_copy(deep=True)

    def cancel(self, action_id: str, *, cancelled_by: str = "human") -> CapabilityAction:
        with self._lock:
            if action_id not in self._actions:
                raise KeyError(action_id)
            action = self._actions[action_id]
            if action.status in {"executing", "completed", "failed"}:
                raise ValueError(f"Action cannot be cancelled from state {action.status}")
            action.status = "cancelled"
            action.metadata["cancelled_by"] = cancelled_by
            self._confirmation_hashes.pop(action_id, None)
            self._persist()
            return action.model_copy(deep=True)

    async def execute(self, action_id: str) -> CapabilityAction:
        with self._lock:
            if action_id not in self._actions:
                raise KeyError(action_id)
            action = self._actions[action_id]
            if action.requires_confirmation and action.status != "confirmed":
                raise PermissionError("Physical/high-consequence action requires explicit confirmation")
            if not action.requires_confirmation and action.status not in {"planned", "confirmed"}:
                raise ValueError(f"Action cannot execute from state {action.status}")
            if action.requires_confirmation and action.status != "confirmed":
                raise ValueError(f"Action cannot execute from state {action.status}")
            binding = self._bindings.get(action.binding_id)
            if binding is None or not binding.enabled:
                raise RuntimeError("Capability binding is missing or disabled")
            adapter = self._adapters.get(action.adapter_id)
            if adapter is None:
                raise RuntimeError(f"Capability adapter is not registered: {action.adapter_id}")
            action.status = "executing"
            action.executed_at = now_iso()
            self._persist()
            invocation = {
                "entity_id": action.entity_id,
                "capability": action.capability,
                "operation": action.operation,
                "args": dict(action.args),
                "binding": binding.model_copy(deep=True),
            }

        try:
            result = await adapter.invoke(**invocation)
        except Exception as exc:
            with self._lock:
                current = self._actions[action_id]
                current.status = "failed"
                current.error = str(exc)
                current.completed_at = now_iso()
                self._persist()
                return current.model_copy(deep=True)

        with self._lock:
            current = self._actions[action_id]
            current.status = "completed"
            current.result = result
            current.completed_at = now_iso()
            self._persist()
            return current.model_copy(deep=True)
