"""Tests for command parsing and prompt text preservation."""

import pytest
from bot.handlers import extract_prompt_text
from services.model_manager import model_manager
from config import settings


def test_extract_prompt_text_simple():
    raw = "/prompt hello world"
    assert extract_prompt_text(raw) == "hello world"


def test_extract_promt_alias():
    raw = "/promt Fix this error"
    assert extract_prompt_text(raw) == "Fix this error"


def test_extract_prompt_multiline_preserve():
    raw = """/promt Fix this program.

Requirements:
1. Fix error
2. Optimize code
3. Build project"""
    extracted = extract_prompt_text(raw)
    expected = """Fix this program.

Requirements:
1. Fix error
2. Optimize code
3. Build project"""
    assert extracted == expected


def test_extract_prompt_unicode_vietnamese_and_emojis():
    raw = "/prompt 🚀 Sửa lỗi chương trình này giúp tôi:\n- Lỗi cú pháp dòng 42\n- 'Special quotes' & \"double\""
    extracted = extract_prompt_text(raw)
    assert "🚀" in extracted
    assert "Sửa lỗi chương trình" in extracted
    assert "'Special quotes'" in extracted
    assert '"double"' in extracted


def test_extract_prompt_empty():
    assert extract_prompt_text("/prompt") == ""
    assert extract_prompt_text("/promt   ") == ""
    assert extract_prompt_text("") == ""


def test_model_alias_resolution():
    settings.aliases = {
        "coding": {"provider": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct"},
        "fast": {"provider": "gemini_api", "model": "gemini-1.5-flash"}
    }
    assert model_manager.resolve_alias("coding") == ("openrouter", "meta-llama/llama-3.3-70b-instruct")
    assert model_manager.resolve_alias("fast") == ("gemini_api", "gemini-1.5-flash")
    assert model_manager.resolve_alias("nonexistent") is None
