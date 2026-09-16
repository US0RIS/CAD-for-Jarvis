from __future__ import annotations

import asyncio

import httpx

from . import main as legacy
from .models import OllamaState
from .v601_ollama_runtime import candidate_urls, probe_status


async def _run() -> None:
    original_url = legacy.OLLAMA_BASE_URL
    original_model = legacy.CONFIGURED_MODEL
    try:
        legacy.OLLAMA_BASE_URL = "http://127.0.0.1:11434"
        legacy.CONFIGURED_MODEL = "qwen3:8b"

        urls = candidate_urls(
            legacy,
            {
                "OLLAMA_HOST": "localhost:11434",
            },
        )
        assert "http://127.0.0.1:11434" in urls
        assert "http://localhost:11434" in urls
        assert "http://[::1]:11434" in urls

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "127.0.0.1":
                raise httpx.ConnectError("simulated first loopback endpoint unavailable", request=request)
            if request.url.host == "localhost":
                return httpx.Response(
                    200,
                    json={"models": [{"name": "qwen3:8b"}]},
                    request=request,
                )
            raise httpx.ConnectError("simulated endpoint unavailable", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            state, resolved = await probe_status(legacy, client, urls)
        assert state is OllamaState.READY
        assert resolved == "qwen3:8b"
        assert legacy.OLLAMA_BASE_URL == "http://localhost:11434"

        # A same-family installed tag must be resolved to the actual installed name so
        # subsequent /api/chat calls cannot use a nonexistent configured alias.
        legacy.OLLAMA_BASE_URL = "http://127.0.0.1:11434"
        legacy.CONFIGURED_MODEL = "qwen3:8b"

        async def alias_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": [{"name": "qwen3:latest"}]}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(alias_handler), trust_env=False) as client:
            state, resolved = await probe_status(legacy, client, ["http://127.0.0.1:11434"])
        assert state is OllamaState.READY
        assert resolved == "qwen3:latest"
        assert legacy.CONFIGURED_MODEL == "qwen3:latest"

        print({
            "forgecad_v601_ollama_selftest": {
                "fallback_endpoint": "pass",
                "exact_model": "pass",
                "family_alias_resolution": "pass",
                "proxy_bypass": "trust_env=False",
            }
        })
    finally:
        legacy.OLLAMA_BASE_URL = original_url
        legacy.CONFIGURED_MODEL = original_model


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
