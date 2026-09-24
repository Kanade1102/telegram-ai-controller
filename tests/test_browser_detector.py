"""Tests for browser URL detection and provider display names."""

import pytest
from browser.detector import detect_provider_from_url, get_provider_display_name, ProgressState


def test_detect_chatgpt_url():
    assert detect_provider_from_url("https://chatgpt.com/c/12345") == "chatgpt_web"
    assert detect_provider_from_url("https://chat.openai.com/g/g-abc") == "chatgpt_web"


def test_detect_gemini_url():
    assert detect_provider_from_url("https://gemini.google.com/app") == "gemini_web"


def test_detect_claude_url():
    assert detect_provider_from_url("https://claude.ai/chat/abcd") == "claude_web"


def test_detect_deepseek_url():
    assert detect_provider_from_url("https://chat.deepseek.com/") == "deepseek_web"


def test_detect_unrecognized_url():
    assert detect_provider_from_url("https://google.com") is None
    assert detect_provider_from_url("") is None


def test_provider_display_names():
    assert get_provider_display_name("chatgpt_web") == "ChatGPT Web"
    assert get_provider_display_name("gemini_web") == "Gemini Web"
    assert get_provider_display_name("openrouter") == "OpenRouter"
    assert get_provider_display_name("9router") == "9Router"


def test_progress_states_enum():
    assert ProgressState.IDLE.value == "IDLE"
    assert ProgressState.GENERATING.value == "GENERATING"
    assert ProgressState.WAITING_FOR_USER.value == "WAITING_FOR_USER"
    assert ProgressState.ERROR.value == "ERROR"
    assert ProgressState.UNKNOWN.value == "UNKNOWN"
