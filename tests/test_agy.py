"""Tests for the agy CLI provider (no network, no real agy execution)."""

import pytest
from providers.api.agy import AgyCLIProvider
from providers.api.base import APIError


def test_agy_is_registered():
    from providers.api import get_api_provider
    prov = get_api_provider("agy")
    assert prov is not None
    assert prov.name == "agy"
    assert prov.friendly_name == "AGY (Antigravity)"


def test_agy_provider_attributes():
    prov = AgyCLIProvider(cli_path="/bin/false", default_model="gemini-3.8-flash-medium")
    assert prov.cli_path == "/bin/false"
    assert prov.default_model == "gemini-3.8-flash-medium"
    assert prov.api_key == ""  # no API key exists for agy


def test_agy_missing_binary_reports_unavailable():
    prov = AgyCLIProvider(cli_path="/nonexistent/agy-binary", default_model="m")
    import asyncio
    ok, msg, _ = asyncio.run(prov.test_connection())
    assert ok is False
    assert "not found" in msg


def test_agy_model_list_parsing():
    prov = AgyCLIProvider(default_model="fallback-model")

    # Simulate agy models output: "<id>\t<Display Name>"
    class FakeProc:
        returncode = 0
        async def communicate(self):
            return (
                b"gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                b"claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n",
                b""
            )

    import asyncio

    async def run():
        prov._cached_models = []
        prov._cache_time = 0
        models = []
        async def fake_run(*args, timeout=60.0):
            return 0, "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\nclaude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n", ""
        # monkeypatch run helper
        orig = prov._run_agy
        prov._run_agy = fake_run
        try:
            models = await prov.list_models(refresh=True)
        finally:
            prov._run_agy = orig
        return models

    models = asyncio.run(run())
    assert models == ["claude-sonnet-4-6", "gemini-3.8-flash-high"]


def test_agy_empty_prompt_raises():
    import asyncio

    async def run():
        prov = AgyCLIProvider(cli_path="/bin/true", default_model="m")
        with pytest.raises(APIError):
            async for _ in prov.send_message([], model="m"):
                pass

    asyncio.run(run())
