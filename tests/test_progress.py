"""Tests for per-provider progress sections (no live backends required)."""

import asyncio
import pytest
from services.progress import progress_service


def test_progress_runs_without_any_backend():
    """No task, no local sessions, no browser -> IDLE fallback section."""
    class FakeClaude:
        @staticmethod
        def get_local_claude_session():
            return None

    class FakeHermes:
        @staticmethod
        def get_local_hermes_session():
            return None

    class FakeBrowser:
        @staticmethod
        async def get_active_session():
            return None

    import services.progress as mod
    orig_cl, orig_hm = mod.claude_local, mod.hermes_local
    orig_bm = mod.browser_manager
    mod.claude_local = FakeClaude()
    mod.hermes_local = FakeHermes()
    mod.browser_manager = FakeBrowser()
    try:
        info = asyncio.run(progress_service.get_progress())
    finally:
        mod.claude_local, mod.hermes_local = orig_cl, orig_hm
        mod.browser_manager = orig_bm
    assert info["backend"] == "multi"
    assert "IDLE" in info["text"]
    assert info["screenshot_path"] is None


def test_progress_never_merges_provider_names():
    """Local claude + hermes sections must keep their own headers."""
    class FakeClaude:
        @staticmethod
        def get_local_claude_session():
            return {
                "status": "GENERATING",
                "elapsed": 10.0,
                "prompt": "claude prompt",
                "cwd": "/x",
                "file": "/x/y.jsonl",
            }

        @staticmethod
        def format_local_claude(info):
            return f"📊 *Claude Code (local session)*\n\n*Status:* {info['status']}"

    class FakeHermes:
        @staticmethod
        def get_local_hermes_session():
            return {
                "status": "IDLE",
                "elapsed": None,
                "prompt": "hermes answer",
                "title": "t",
                "cwd": "/y",
                "session_id": "s",
            }

        @staticmethod
        def format_local_hermes(info):
            return f"📊 *Hermes (local session)*\n\n*Status:* {info['status']}"

    class FakeBrowser:
        @staticmethod
        async def get_active_session():
            return None

    import services.progress as mod
    orig_cl, orig_hm = mod.claude_local, mod.hermes_local
    orig_bm = mod.browser_manager
    mod.claude_local = FakeClaude()
    mod.hermes_local = FakeHermes()
    mod.browser_manager = FakeBrowser()
    try:
        info = asyncio.run(progress_service.get_progress())
    finally:
        mod.claude_local, mod.hermes_local = orig_cl, orig_hm
        mod.browser_manager = orig_bm

    text = info["text"]
    assert "Claude Code (local session)" in text
    assert "Hermes (local session)" in text
    # two separate sections, each with own status
    assert text.count("*Status:*") == 2
    assert "GENERATING" in text
    assert "IDLE" in text
    # screenshot suppressed in multi-section view
    assert info["screenshot_path"] is None
