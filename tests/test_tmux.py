"""Tests for TmuxController CLI architecture."""

import pytest
from cli.tmux_controller import TmuxController


def test_tmux_controller_init():
    tc = TmuxController(default_session="test-ai")
    assert tc.default_session == "test-ai"
    assert isinstance(tc.is_available(), bool)


@pytest.mark.asyncio
async def test_tmux_controller_unavailable_handling():
    tc = TmuxController()
    if not tc.is_available():
        code, out, err = await tc.run_command("list-sessions")
        assert code == -1
        assert "not installed" in err
        sessions = await tc.list_sessions()
        assert sessions == []
