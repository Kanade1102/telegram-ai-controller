"""Tests for session manager and minimal state persistence."""

import json
import pytest
from pathlib import Path
from services.session_manager import SessionManager, SessionState


class StubDB:
    """In-memory stand-in so tests never touch the real controller.db."""

    def __init__(self):
        self.vals: dict[str, str] = {}

    def get_session_val(self, key, default=None):
        return self.vals.get(key, default)

    def set_session_val(self, key, value):
        self.vals[key] = value

    def delete_session_val(self, key):
        self.vals.pop(key, None)


def make_mgr(tmp_path: Path) -> tuple[SessionManager, StubDB]:
    stub = StubDB()
    mgr = SessionManager(state_file=tmp_path / "state.json", database=stub)
    return mgr, stub


def test_session_state_defaults(tmp_path: Path):
    mgr, _ = make_mgr(tmp_path)
    assert mgr.state.active_mode in ("browser", "api", "auto")
    assert mgr.state.last_status == "IDLE"
    # Fallback must be OFF by default (never silently route to third-party APIs)
    assert mgr.state.active_fallback_chain is None


def test_session_state_save_and_reload(tmp_path: Path):
    state_file = tmp_path / "state.json"
    stub = StubDB()
    mgr = SessionManager(state_file=state_file, database=stub)
    mgr.set_provider("openrouter")
    mgr.set_conversation(42)
    mgr.record_prompt("test prompt", "2026-09-24T10:00:00Z")
    mgr.record_response("test response", status="IDLE")

    assert state_file.is_file()

    # Create new manager pointing to same file
    mgr2 = SessionManager(state_file=state_file, database=stub)
    assert mgr2.state.active_provider == "openrouter"
    assert mgr2.state.active_conversation_id == 42
    assert mgr2.state.last_prompt == "test prompt"
    assert mgr2.state.last_known_response == "test response"
    assert mgr2.state.last_status == "IDLE"


def test_provider_mode_automatic_switch(tmp_path: Path):
    mgr, _ = make_mgr(tmp_path)

    mgr.set_provider("chatgpt_web")
    assert mgr.state.active_mode == "browser"

    mgr.set_provider("openai")
    assert mgr.state.active_mode == "api"

    mgr.set_provider("gemini_web")
    assert mgr.state.active_mode == "browser"

    mgr.set_provider("gemini_api")
    assert mgr.state.active_mode == "api"


def test_effort_persistence(tmp_path: Path):
    state_file = tmp_path / "state.json"
    stub = StubDB()
    mgr = SessionManager(state_file=state_file, database=stub)
    assert mgr.state.active_effort is None

    mgr.set_effort("high")
    assert mgr.state.active_effort == "high"
    assert stub.vals.get("active_effort") == "high"

    # Reload from same files
    mgr2 = SessionManager(state_file=state_file, database=stub)
    assert mgr2.state.active_effort == "high"

    # set_effort(None) persists None
    mgr2.set_effort(None)
    mgr3 = SessionManager(state_file=state_file, database=stub)
    assert mgr3.state.active_effort is None
