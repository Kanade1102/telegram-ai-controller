"""Tests for Telegram security and secret masking."""

import pytest
from config import Settings
from bot.security import is_authorized
from services.credential_manager import mask_secret


def test_deny_by_default_when_no_allowed_users():
    s = Settings(telegram_allowed_users=set())
    assert s.is_user_allowed(12345) is False
    assert s.is_user_allowed(99999) is False


def test_authorized_user_allowed():
    s = Settings(telegram_allowed_users={123456789, 987654321})
    assert s.is_user_allowed(123456789) is True
    assert s.is_user_allowed(987654321) is True
    assert s.is_user_allowed(111111111) is False


def test_mask_secret_none_or_empty():
    assert mask_secret(None) == "[NOT SET]"
    assert mask_secret("") == "[NOT SET]"


def test_mask_secret_standard():
    assert mask_secret("sk-1234567890abcdef") == "sk-12...cdef"
    assert "1234567890" not in mask_secret("sk-1234567890abcdef")


def test_mask_secret_short():
    assert mask_secret("12345") == "********"
