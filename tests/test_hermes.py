"""Tests for the Hermes CLI provider (no network, no real hermes execution)."""

import asyncio
import pytest
from providers.api.hermes import HermesCLIProvider
from providers.api.base import APIError


def test_hermes_is_registered():
    from providers.api import get_api_provider
    prov = get_api_provider("hermes")
    assert prov is not None
    assert prov.name == "hermes"
    assert prov.friendly_name == "Hermes Agent (local CLI)"


def test_hermes_provider_attributes():
    prov = HermesCLIProvider(cli_path="/bin/false", default_model="idk")
    assert prov.cli_path == "/bin/false"
    assert prov.default_model == "idk"
    assert prov.api_key == ""  # Hermes owns its own credentials


def test_hermes_missing_binary_reports_unavailable():
    prov = HermesCLIProvider(cli_path="/nonexistent/hermes-binary", default_model="m")
    ok, msg, _ = asyncio.run(prov.test_connection())
    assert ok is False
    assert "not found" in msg


def test_hermes_empty_prompt_raises():
    async def run():
        prov = HermesCLIProvider(cli_path="/bin/true", default_model="m")
        with pytest.raises(APIError):
            async for _ in prov.send_message([], model="m"):
                pass

    asyncio.run(run())


def test_hermes_default_model_falls_back_to_settings():
    from config import settings
    prov = HermesCLIProvider(cli_path="/bin/true")
    assert prov.default_model == settings.hermes_default_model
