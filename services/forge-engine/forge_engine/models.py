from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    FAILED = "failed"


class OllamaState(StrEnum):
    CHECKING = "checking"
    WARMING = "warming"
    READY = "ready"
    OFFLINE = "offline"
    FAILED = "failed"


class JobState(StrEnum):
    QUEUED = "queued"
    WARMING = "warming"
    PLANNING = "planning"
    APPLYING = "applying"
    ANALYZING = "analyzing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeStatus(BaseModel):
    engine: RuntimeState = RuntimeState.READY
    scene: RuntimeState = RuntimeState.STARTING
    ollama: OllamaState = OllamaState.CHECKING
    configured_model: str
    resolved_model: str | None = None
    api_version: str = "2"


class CreateJobRequest(BaseModel):
    kind: Literal["agent", "simulation", "campaign", "component-search", "deploy"]
    text: str | None = None
    branch: str | None = None
    selected_object_id: str | None = None
    payload: dict = Field(default_factory=dict)


class EngineeringJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: Literal["agent", "simulation", "campaign", "component-search", "deploy"]
    state: JobState = JobState.QUEUED
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    progress: float | None = None
    message: str | None = None
    branch: str | None = None
    selected_object_id: str | None = None
