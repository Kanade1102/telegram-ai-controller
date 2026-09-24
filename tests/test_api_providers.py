"""Tests for API providers and generic OpenAI-compatible adapter."""

import pytest
import httpx
from providers.api.openai_compatible import OpenAICompatibleProvider
from providers.api.base import AuthError, RateLimitError, ModelNotFoundError, ServerError
from providers.api import registry, get_api_provider, list_api_providers


def test_openai_compatible_initialization():
    p = OpenAICompatibleProvider(
        name="test_provider",
        friendly_name="Test Provider",
        base_url="https://api.example.com/v1",
        api_key="sk-testkey123",
        default_model="test-model",
        custom_headers={"X-Custom": "Header"}
    )
    headers = p._get_headers()
    assert headers["Authorization"] == "Bearer sk-testkey123"
    assert headers["X-Custom"] == "Header"
    assert headers["Content-Type"] == "application/json"


def test_openai_compatible_error_classification():
    p = OpenAICompatibleProvider(name="test", api_key="sk-123")

    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    # 401 AuthError
    res_401 = httpx.Response(401, request=req, json={"error": {"message": "Invalid API key"}})
    with pytest.raises(AuthError):
        p._handle_http_error(res_401)

    # 429 RateLimitError
    res_429 = httpx.Response(429, request=req, json={"error": {"message": "Rate limit reached"}})
    with pytest.raises(RateLimitError):
        p._handle_http_error(res_429)

    # 404 ModelNotFoundError
    res_404 = httpx.Response(404, request=req, json={"error": {"message": "Model not found"}})
    with pytest.raises(ModelNotFoundError):
        p._handle_http_error(res_404)

    # 500 ServerError
    res_500 = httpx.Response(500, request=req, text="Internal server error")
    with pytest.raises(ServerError):
        p._handle_http_error(res_500)


def test_provider_registry_lookup():
    prov = get_api_provider("openai")
    assert prov is not None
    assert prov.name == "openai"

    prov_openrouter = get_api_provider("openrouter")
    assert prov_openrouter is not None
    assert prov_openrouter.name == "openrouter"

    prov_gemini = get_api_provider("gemini_api")
    assert prov_gemini is not None
    assert prov_gemini.name == "gemini_api"


def test_custom_provider_registration():
    custom = OpenAICompatibleProvider(
        name="custom_local",
        friendly_name="Local LM",
        base_url="http://127.0.0.1:1234/v1",
        default_model="qwen-2.5"
    )
    registry.register(custom)

    found = get_api_provider("custom_local")
    assert found is not None
    assert found.default_model == "qwen-2.5"
