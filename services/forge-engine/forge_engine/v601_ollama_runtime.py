from __future__ import annotations

"""ForgeCAD 6.0.1 local-Ollama discovery hardening.

The legacy runtime probes one URL (127.0.0.1:11434) once with a 1.5 second timeout.
That is too brittle for a packaged desktop app: Ollama may be bound via OLLAMA_HOST,
localhost may resolve differently, the daemon may still be waking, or proxy
environment variables may accidentally intercept loopback HTTP.

This layer preserves the existing ForgeCAD/Ollama API contract while making local
model discovery deterministic and resilient. Once a working Ollama endpoint is found,
legacy.OLLAMA_BASE_URL is rebound so all existing planner/chat code uses that exact
endpoint for the rest of the process.
"""

import asyncio
import os
from typing import Any, Iterable, Mapping

import httpx

from .models import OllamaState


_DEFAULTS = (
    "http://127.0.0.1:11434",
    "http://localhost:11434",
    "http://[::1]:11434",
)


def _normalize_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"
    raw = raw.rstrip("/")
    # OLLAMA_HOST commonly uses wildcard bind addresses; they are server bind
    # addresses, not useful client destinations. Convert them to loopback.
    raw = raw.replace("http://0.0.0.0:", "http://127.0.0.1:")
    raw = raw.replace("https://0.0.0.0:", "https://127.0.0.1:")
    raw = raw.replace("http://[::]:", "http://[::1]:")
    raw = raw.replace("https://[::]:", "https://[::1]:")
    return raw


def candidate_urls(legacy: Any, environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    values: list[str | None] = [
        env.get("FORGECAD_OLLAMA_URL"),
        env.get("OLLAMA_HOST"),
        getattr(legacy, "OLLAMA_BASE_URL", None),
        *_DEFAULTS,
    ]
    result: list[str] = []
    for value in values:
        normalized = _normalize_url(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _model_match(configured: str, names: Iterable[str]) -> str | None:
    configured = str(configured or "").strip()
    cleaned = [str(name or "").strip() for name in names if str(name or "").strip()]
    if configured in cleaned:
        return configured
    base = configured.split(":", 1)[0]
    return next((name for name in cleaned if name.split(":", 1)[0] == base), None)


async def _probe_one(client: httpx.AsyncClient, base_url: str) -> tuple[str, list[str]] | None:
    try:
        response = await client.get(f"{base_url}/api/tags")
        response.raise_for_status()
        payload = response.json()
        names = [str(model.get("name", "")) for model in payload.get("models", []) if isinstance(model, dict)]
        return base_url, names
    except Exception:
        return None


async def probe_status(legacy: Any, client: httpx.AsyncClient, urls: list[str] | None = None) -> tuple[OllamaState, str | None]:
    candidates = urls or candidate_urls(legacy)
    configured = str(getattr(legacy, "CONFIGURED_MODEL", "qwen3:8b"))
    online_endpoint: str | None = None

    results = await asyncio.gather(*(_probe_one(client, url) for url in candidates))
    for result in results:
        if result is None:
            continue
        base_url, names = result
        if online_endpoint is None:
            online_endpoint = base_url
        resolved = _model_match(configured, names)
        if resolved:
            legacy.OLLAMA_BASE_URL = base_url
            # Existing planner/chat code reads CONFIGURED_MODEL directly. If the user
            # requested a family name/tag that resolves to another installed tag, use
            # the actual installed tag so the subsequent /api/chat call cannot fail on
            # a model name we already know does not exist.
            legacy.CONFIGURED_MODEL = resolved
            return OllamaState.READY, resolved

    if online_endpoint is not None:
        legacy.OLLAMA_BASE_URL = online_endpoint
        return OllamaState.FAILED, None
    return OllamaState.OFFLINE, None


def install(legacy: Any) -> None:
    if getattr(legacy, "_forgecad_v601_ollama_runtime", False):
        return

    async def robust_ollama_status() -> tuple[OllamaState, str | None]:
        # trust_env=False is intentional for local discovery. A corporate/system HTTP
        # proxy must never intercept ForgeCAD -> localhost Ollama traffic.
        timeout = httpx.Timeout(3.0, connect=1.5)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            state, resolved = await probe_status(legacy, client)
            if state is not OllamaState.OFFLINE:
                return state, resolved
            # One short retry covers a daemon that is still waking when ForgeCAD opens
            # without turning a genuinely offline Ollama install into a long UI stall.
            await asyncio.sleep(0.35)
            return await probe_status(legacy, client)

    legacy.ollama_status = robust_ollama_status
    legacy._forgecad_v601_ollama_runtime = True
