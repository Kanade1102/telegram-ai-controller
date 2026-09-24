"""Tests for the Claude Code CLI provider (no network, no real claude execution)."""

import asyncio
import json
import pytest
from providers.api.claudecode import ClaudeCodeCLIProvider
from providers.api.base import APIError


def test_claudecode_is_registered():
    from providers.api import get_api_provider
    prov = get_api_provider("claudecode")
    assert prov is not None
    assert prov.name == "claudecode"
    assert prov.friendly_name == "Claude Code (local CLI)"


def test_claudecode_provider_attributes():
    prov = ClaudeCodeCLIProvider(cli_path="/bin/false", default_model="idk")
    assert prov.cli_path == "/bin/false"
    assert prov.default_model == "idk"
    assert prov.api_key == ""  # claude owns its own credentials


def test_claudecode_missing_binary_reports_unavailable():
    prov = ClaudeCodeCLIProvider(cli_path="/nonexistent/claude-binary", default_model="m")
    ok, msg, _ = asyncio.run(prov.test_connection())
    assert ok is False
    assert "not found" in msg


def test_claudecode_empty_prompt_raises():
    async def run():
        prov = ClaudeCodeCLIProvider(cli_path="/bin/true", default_model="m")
        with pytest.raises(APIError):
            async for _ in prov.send_message([], model="m"):
                pass

    asyncio.run(run())


def test_claudecode_invalid_effort_raises():
    async def run():
        prov = ClaudeCodeCLIProvider(cli_path="/bin/true", default_model="m")
        with pytest.raises(APIError):
            async for _ in prov.send_message(
                [{"role": "user", "content": "hi"}], model="m", effort="ultra"
            ):
                pass

    asyncio.run(run())


def test_claudecode_default_model_falls_back_to_settings():
    from config import settings
    prov = ClaudeCodeCLIProvider(cli_path="/bin/true")
    assert prov.default_model == settings.claudecode_default_model


def test_claudecode_stream_parses_events():
    """Fake stream: text deltas yield, result sets real usage from JSON."""

    lines = [
        json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "PO"}},
            "session_id": "s1",
        }),
        json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "NG"}},
            "session_id": "s1",
        }),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "PONG",
            "session_id": "s1",
            "total_cost_usd": 0.01488,
            "usage": {"input_tokens": 2858, "output_tokens": 24},
        }),
        "",
    ]

    async def fake_exec(self, *args, **kwargs):
        class FakeStream:
            async def readline(self):
                if not lines:
                    return b""
                return lines.pop(0).encode()

        class FakeStdin:
            def write(self, data):
                pass

            async def drain(self):
                pass

            def close(self):
                pass

        class FakeProc:
            returncode = 0
            stdout = FakeStream()
            stdin = FakeStdin()

            async def wait(self):
                return 0

            def kill(self):
                pass

        return FakeProc()

    async def run():
        prov = ClaudeCodeCLIProvider(cli_path="/bin/true", default_model="m")
        prov._spawn = fake_exec  # type: ignore[attr-defined]
        # Use the real spawn but patch asyncio.create_subprocess_exec instead.
        import providers.api.claudecode as mod
        original = mod.asyncio.create_subprocess_exec
        mod.asyncio.create_subprocess_exec = fake_exec  # type: ignore[assignment]
        try:
            chunks = []
            async for chunk in prov.send_message([{"role": "user", "content": "ping"}]):
                chunks.append(chunk)
        finally:
            mod.asyncio.create_subprocess_exec = original
        return prov, chunks

    prov, chunks = asyncio.run(run())
    assert "".join(chunks) == "PONG"
    assert prov._last_usage["prompt_tokens"] == 2858
    assert prov._last_usage["completion_tokens"] == 24
    assert prov._last_usage["total_tokens"] == 2882
    assert prov._last_usage["cost"] == 0.01488
