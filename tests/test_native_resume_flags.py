"""Native /resume IDs reach each CLI's real resume flag."""

import asyncio
import json

from providers.api.hermes import HermesCLIProvider
from providers.api.claudecode import ClaudeCodeCLIProvider
from providers.api.agy import AgyCLIProvider


class FakeStdin:
    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class FakeStream:
    def __init__(self, lines):
        self.lines = [line.encode() for line in lines]

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class FakeProc:
    def __init__(self, lines):
        self.returncode = 0
        self.stdin = FakeStdin()
        self.stdout = FakeStream(lines)

    async def wait(self):
        return 0

    def kill(self):
        pass


def run_provider(mod, provider, lines, session_id):
    seen = []

    async def fake_exec(*args, **kwargs):
        seen.extend(args)
        return FakeProc(lines)

    original = mod.asyncio.create_subprocess_exec
    mod.asyncio.create_subprocess_exec = fake_exec
    try:
        async def run():
            async for _ in provider.send_message(
                [{"role": "user", "content": "continue"}],
                native_session_id=session_id,
            ):
                pass
        asyncio.run(run())
    finally:
        mod.asyncio.create_subprocess_exec = original
    return seen


def test_hermes_resume_flag():
    import providers.api.hermes as mod
    args = run_provider(
        mod,
        HermesCLIProvider(cli_path="/bin/true"),
        [json.dumps({"type": "result", "text": "ok"})],
        "20260924_111308_df377c",
    )
    i = args.index("--resume")
    assert args[i + 1] == "20260924_111308_df377c"


def test_claude_resume_flag():
    import providers.api.claudecode as mod
    args = run_provider(
        mod,
        ClaudeCodeCLIProvider(cli_path="/bin/true"),
        [json.dumps({"type": "result", "result": "ok", "usage": {}})],
        "claude-id",
    )
    i = args.index("--resume")
    assert args[i + 1] == "claude-id"


def test_agy_resume_flag():
    import providers.api.agy as mod
    args = run_provider(
        mod,
        AgyCLIProvider(cli_path="/bin/true", default_model="m"),
        [json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}})],
        "agy-id",
    )
    i = args.index("--conversation")
    assert args[i + 1] == "agy-id"
