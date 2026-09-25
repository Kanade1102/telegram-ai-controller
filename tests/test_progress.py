"""Tests for per-provider progress sections (no live backends required)."""

import asyncio
from services.progress import progress_service


class FakeBrowser:
    """Browser manager stub: configurable AI sessions."""

    def __init__(self, sessions=None):
        self.sessions = sessions or []

    async def get_ai_sessions(self):
        return self.sessions


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
    assert info["screenshot_path"] is None


def test_progress_screenshots_generating_tab():
    """GENERATING browser tab is focused and captured even with other sections."""

    class FakePage:
        def __init__(self):
            self.brought_to_front = False

        async def bring_to_front(self):
            self.brought_to_front = True

    class FakeStatusProvider:
        def __init__(self, status):
            self.status = status

        async def get_status(self, page):
            return self.status

        async def get_last_response(self, page):
            return ""

    class FakeClaude:
        @staticmethod
        def get_local_claude_session():
            return None

    class FakeHermes:
        @staticmethod
        def get_local_hermes_session():
            return None

    idle_page = FakePage()
    gen_page = FakePage()
    sessions = [
        {
            "page": idle_page,
            "provider": FakeStatusProvider("IDLE"),
            "provider_name": "ChatGPT Web",
            "title": "chat",
            "active": False,
        },
        {
            "page": gen_page,
            "provider": FakeStatusProvider("GENERATING"),
            "provider_name": "Gemini Web",
            "title": "gemini",
            "active": True,
        },
    ]

    import services.progress as mod
    import services.screenshot as shot_mod
    orig_cl, orig_hm = mod.claude_local, mod.hermes_local
    orig_bm = mod.browser_manager
    orig_capture = shot_mod.screenshot_service.capture

    mod.claude_local = FakeClaude()
    mod.hermes_local = FakeHermes()
    mod.browser_manager = FakeBrowser(sessions)

    async def fake_capture(page=None, force_mode=None):
        return "/fake/shot.png" if page is gen_page else None

    shot_mod.screenshot_service.capture = fake_capture
    try:
        info = asyncio.run(progress_service.get_progress())
    finally:
        mod.claude_local, mod.hermes_local = orig_cl, orig_hm
        mod.browser_manager = orig_bm
        shot_mod.screenshot_service.capture = orig_capture

    assert info["screenshot_path"] == "/fake/shot.png"
    assert gen_page.brought_to_front is True
    assert "Gemini Web" in info["text"]
    assert "ChatGPT Web" in info["text"]
    assert "GENERATING" in info["text"]


def test_progress_falls_back_to_active_tab_for_screenshot():
    """No tab generating: the active tab is focused and captured."""

    class FakePage:
        def __init__(self):
            self.brought_to_front = False

        async def bring_to_front(self):
            self.brought_to_front = True

    class FakeStatusProvider:
        async def get_status(self, page):
            return "IDLE"

        async def get_last_response(self, page):
            return ""

    active_page = FakePage()
    sessions = [
        {
            "page": FakePage(),
            "provider": FakeStatusProvider(),
            "provider_name": "ChatGPT Web",
            "title": "chat",
            "active": False,
        },
        {
            "page": active_page,
            "provider": FakeStatusProvider(),
            "provider_name": "Gemini Web",
            "title": "gemini",
            "active": True,
        },
    ]

    import services.progress as mod
    import services.screenshot as shot_mod
    orig_cl, orig_hm = mod.claude_local, mod.hermes_local
    orig_bm = mod.browser_manager
    orig_capture = shot_mod.screenshot_service.capture

    mod.claude_local = FakeClaudeNone()
    mod.hermes_local = FakeHermesNone()
    mod.browser_manager = FakeBrowser(sessions)

    async def fake_capture(page=None, force_mode=None):
        return "/fake/active.png" if page is active_page else None

    shot_mod.screenshot_service.capture = fake_capture
    try:
        info = asyncio.run(progress_service.get_progress())
    finally:
        mod.claude_local, mod.hermes_local = orig_cl, orig_hm
        mod.browser_manager = orig_bm
        shot_mod.screenshot_service.capture = orig_capture

    assert info["screenshot_path"] == "/fake/active.png"
    assert active_page.brought_to_front is True


class FakeClaudeNone:
    @staticmethod
    def get_local_claude_session():
        return None


class FakeHermesNone:
    @staticmethod
    def get_local_hermes_session():
        return None
