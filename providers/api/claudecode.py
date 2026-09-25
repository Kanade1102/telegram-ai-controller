"""Claude Code CLI provider.

Drives the locally installed `claude` binary (Anthropic's coding agent CLI).
No API keys involved: `claude` owns its own auth (OAuth token / env var),
here routed through the local 9Router proxy. The Telegram bot runs
`claude -p` (print mode, non-interactive, no permission prompts).

ponytail: tool mode (agentic Bash/Edit) would hang on permission prompts in
headless -p, so default is pure chat: --tools "" + --max-turns 2. Upgrade
path: add a per-provider "agent" option that passes --allowedTools +
--permission-mode acceptEdits when the user wants real coding from Telegram.
"""

import asyncio
import json
import logging
import shutil
import time
from typing import AsyncGenerator, Optional, Any

from providers.api.base import APIProvider, APIError, AuthError
from config import settings

logger = logging.getLogger(__name__)

CLAUDE_BIN_DEFAULT = "claude"
CLAUDE_TURN_TIMEOUT = 300  # seconds; claude -p can take minutes on big turns
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")


class ClaudeCodeCLIProvider(APIProvider):
    name = "claudecode"
    friendly_name = "Claude Code (local CLI)"

    def __init__(
        self,
        cli_path: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.cli_path = cli_path or settings.claudecode_cli_path
        self.default_model = default_model or settings.claudecode_default_model or ""
        self.api_key = ""  # claude owns its own credentials; nothing to expose
        self._cached_models: list[str] = []
        self._cache_time: float = 0
        self._last_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }

    def is_available(self) -> bool:
        if self.cli_path == CLAUDE_BIN_DEFAULT:
            return shutil.which("claude") is not None
        return shutil.which(self.cli_path) is not None

    async def _run_claude(self, *args: str, timeout: float = 60.0) -> tuple[int, str, str]:
        """Run claude with argv (never a shell), returning (code, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return -1, "", f"claude timed out after {timeout:.0f}s"
        return proc.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")

    async def test_connection(self) -> tuple[bool, str, float]:
        start = time.perf_counter()
        if not self.is_available():
            return False, f"claude binary not found ({self.cli_path})", 0.0
        code, out, err = await self._run_claude("--version", timeout=60.0)
        latency = (time.perf_counter() - start) * 1000
        if code != 0:
            return False, f"claude failed: {err.strip()[:120] or 'unknown error'}", latency
        return True, f"Connected (Claude Code {out.strip()})", latency

    async def list_models(self, refresh: bool = False) -> list[str]:
        now = time.time()
        if not refresh and self._cached_models and (now - self._cache_time) < settings.model_cache_seconds:
            return self._cached_models
        if self._cached_models and not refresh:
            return self._cached_models
        # claude has no non-interactive model list. Return the configured
        # default ("idk" = whatever claude auth/settings pick).
        models = [self.default_model] if self.default_model else []
        if models:
            self._cached_models = models
            self._cache_time = now
        return models

    async def send_message(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        **options: Any
    ) -> AsyncGenerator[str, None]:
        if not self.is_available():
            raise AuthError(f"claude binary not found ({self.cli_path})", provider=self.name)

        # Rebuild one prompt from history. claude -p is stateless per run;
        # history is folded into the prompt for multi-turn context.
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"<instructions>\n{content}\n</instructions>")
            elif role == "assistant":
                parts.append(f"<assistant>\n{content}\n</assistant>")
            else:
                parts.append(content)
        prompt_text = "\n\n".join(parts).strip()
        if not prompt_text:
            raise APIError("Empty prompt for claude", provider=self.name)

        # Effort maps to claude --effort: low|medium|high|xhigh|max.
        # Default to low explicitly: ~/.claude/settings.json has effortLevel
        # "high" (thinking model), which made bot chats slow. Always send a
        # flag so the user-config high never leaks into Telegram runs.
        effort = options.get("effort") or settings.claudecode_effort or "low"
        if effort:
            effort = effort.lower()
            if effort not in CLAUDE_EFFORTS:
                raise APIError(
                    f"Invalid claude effort: {effort} (use low|medium|high|xhigh|max)",
                    provider=self.name,
                )

        self._last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        # stream-json yields incremental text_delta events and a final result
        # object with real usage + cost (never fabricated).
        args = [
            "-p",
            "--output-format", "stream-json",
            "--verbose",  # required for stream-json in print mode
            "--include-partial-messages",
            # Pure chat: no tools. Headless -p would block on permission
            # prompts for Bash/Edit, so agentic mode is off by default.
            "--tools", "",
            # Safety net: even pure chat can loop on edge cases.
            "--max-turns", "2",
        ]
        if model and model not in ("idk", "default"):
            args += ["--model", model]
        if effort:
            args += ["--effort", effort]

        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            # Never PIPE stderr — an unread full buffer blocks claude mid-stream.
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdin is not None
        proc.stdin.write(prompt_text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        emitted = False
        try:
            assert proc.stdout is not None
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=CLAUDE_TURN_TIMEOUT + 30)
                if not line:
                    break
                line_str = line.decode("utf-8", "replace").strip()
                if not line_str:
                    continue
                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                ev_type = event.get("type", "")
                if ev_type == "stream_event":
                    ev = event.get("event", {})
                    if ev.get("type") == "content_block_delta":
                        chunk = ev.get("delta", {}).get("text", "")
                        if chunk:
                            emitted = True
                            yield chunk
                elif ev_type == "result":
                    usage = event.get("usage") or {}
                    self._last_usage = {
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                        "cost": float(event.get("total_cost_usd") or 0.0),
                    }
                    if event.get("is_error"):
                        err = event.get("result") or event.get("api_error_status") or "unknown error"
                        raise APIError(f"claude: {err}", provider=self.name)
                    if not emitted:
                        result = event.get("result", "")
                        if result:
                            yield result
                    return
        except asyncio.TimeoutError:
            proc.kill()
            await self._bounded_wait(proc)
            raise APIError(f"claude timed out after {CLAUDE_TURN_TIMEOUT}s", provider=self.name)
        except GeneratorExit:
            # Consumer stopped iterating (e.g. /stop mid-stream). Kill now.
            proc.kill()
            await self._bounded_wait(proc)
            raise
        finally:
            if proc.returncode is None:
                await self._bounded_wait(proc)

        if proc.returncode not in (0, None) and not emitted:
            raise APIError(f"claude failed: exit code {proc.returncode}", provider=self.name)

    @staticmethod
    async def _bounded_wait(proc: asyncio.subprocess.Process, timeout: float = 10.0) -> None:
        """Wait for process exit with a hard cap so cleanup never hangs."""
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            try:
                proc.kill()
            except Exception:
                pass

    async def get_usage(self) -> dict[str, Any]:
        # stream-json result carries real tokens and cost; zeros when absent.
        return dict(self._last_usage)
