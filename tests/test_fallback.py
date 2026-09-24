"""Tests for FallbackManager routing chains."""

import pytest
from services.fallback_manager import fallback_manager
from config import settings


def test_fallback_chains_listing():
    settings.fallback_chains = {
        "coding": ["openai", "openrouter", "9router"],
        "browser": ["chatgpt_web", "gemini_web"]
    }

    chains = fallback_manager.list_chains()
    assert "coding" in chains
    assert "browser" in chains
    assert chains["coding"] == ["openai", "openrouter", "9router"]


def test_fallback_set_and_get():
    settings.fallback_chains = {
        "coding": ["openai", "openrouter"],
        "general": ["gemini_api", "openrouter"]
    }

    assert fallback_manager.set_active_chain("general") is True
    assert fallback_manager.get_active_chain_name() == "general"
    assert fallback_manager.get_chain_providers() == ["gemini_api", "openrouter"]


def test_fallback_disable():
    fallback_manager.set_active_chain("off")
    assert fallback_manager.get_active_chain_name() is None
    assert fallback_manager.get_chain_providers() == []
