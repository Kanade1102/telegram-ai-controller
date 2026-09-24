"""Tests for session manager and minimal state persistence."""

import json
import pytest
from pathlib import Path
from services.session_manager import SessionManager, SessionState


def test_session_state_defaults(tmp_path: Path):
    state_file = tmp_path / "state.json"
    mgr = SessionManager(state_file=state_file)
    assert mgr.state.active_mode in ("browser", "api", "auto")
    assert mgr.state.last_status == "IDLE"
    # Fallback must be OFF by default (never silently route to third-party APIs)
    assert mgr.state.active_fallback_chain is None


def test_session_state_save_and_reload(tmp_path: Path):
    state_file = tmp_path / "state.json"
    mgr = SessionManager(state_file=state_file)
    mgr.set_provider("openrouter")
    mgr.set_conversation(42)
    mgr.record_prompt("test prompt", "2026-09-24T10:00:00Z")
    mgr.record_response("test response", status="IDLE")

    assert state_file.is_file()

    # Create new manager pointing to same file
    mgr2 = SessionManager(state_file=state_file)
    assert mgr2.state.active_provider == "openrouter"
    assert mgr2.state.active_conversation_id == 42
    assert mgr2.state.last_prompt == "test prompt"
    assert mgr2.state.last_known_response == "test response"
    assert mgr2.state.last_status == "IDLE"


def test_provider_mode_automatic_switch(tmp_path: Path):
    state_file = tmp_path / "state.json"
    mgr = SessionManager(state_file=state_file)

    mgr.set_provider("chatgpt_web")
    assert mgr.state.active_mode == "browser"

    mgr.set_provider("openai")
    assert mgr.state.active_mode == "api"

    mgr.set_provider("gemini_web")
    assert mgr.state.active_mode == "browser"

    mgr.set_provider("gemini_api")
    assert mgr.state.active_mode == "api"
