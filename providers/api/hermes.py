"""Hermes Agent CLI provider.

Drives the locally installed `hermes` binary (this machine's own Hermes Agent).
No API keys involved: Hermes owns its OAuth/keys in ~/.hermes/.env and
~/.hermes/auth.json. The Telegram bot just runs `hermes chat` one-shot.

ponytail: model listing is not exposed by `hermes` (model picker is interactive),
so /models returns the provider's configured default model only. Upgrade path:
parse `hermes status` output if Hermes ever prints its full model list non-interactively.
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

HERMES_BIN_DEFAULT = "hermes"
HERMES_TURN_TIMEOUT = 600  # seconds; Hermes agents can run tools for many minutes


class HermesCLIProvider(APIProvider):
    name = "hermes"
    friendly_name = "Hermes Agent (local CLI)"

    def __init__(
        self,
        cli_path: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.cli_path = cli_path or settings.hermes_cli_path
        # Hermes's model is configured in ~/.hermes/config.yaml; "idk" means
        # "use whatever Hermes is currently configured with".
        self.default_model = default_model or settings.hermes_default_model or ""
        self.api_key = ""  # Hermes owns its own credentials; nothing to expose
        self._cached_models: list[str] = []
        self._cache_time: float = 0
        self._last_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }

    def is_available(self) -> bool:
        return shutil.which(self.cli_path) is not None

    async def _run_hermes(self, *args: str, timeout: float = 60.0) -> tuple[int, str, str]:
        """Run hermes with argv (never a shell), returning (code, stdout, stderr)."""
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
            return -1, "", f"hermes timed out after {timeout:.0f}s"
        return proc.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")

    async def test_connection(self) -> tuple[bool, str, float]:
        start = time.perf_counter()
        if not self.is_available():
            return False, f"hermes binary not found ({self.cli_path})", 0.0
        # Cheap, non-generative check: hermes status returns quickly.
        code, out, err = await self._run_hermes("status", timeout=60.0)
        latency = (time.perf_counter() - start) * 1000
        if code != 0:
            return False, f"hermes failed: {err.strip()[:120] or 'unknown error'}", latency
        return True, "Connected (local Hermes Agent)", latency

    async def list_models(self, refresh: bool = False) -> list[str]:
        now = time.time()
        if not refresh and self._cached_models and (now - self._cache_time) < settings.model_cache_seconds:
            return self._cached_models
        if self._cached_models and not refresh:
            return self._cached_models
        # Hermes has no non-interactive model list. Return the configured default
        # (possibly "idk" = "whatever Hermes uses").
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
            raise AuthError(f"hermes binary not found ({self.cli_path})", provider=self.name)

        # Rebuild one prompt from history. hermes one-shot is stateless; history
        # is folded into the prompt for multi-turn context.
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
            raise APIError("Empty prompt for hermes", provider=self.name)

        # Effort maps to --reasoning: none|minimal|low|medium|high|xhigh|max|ultra.
        # Default to low explicitly: ~/.hermes/config.yaml has
        # agent.reasoning_effort "high" (thinking model), which made bot chats
        # slow. Always send a flag so user-config high never leaks in.
        effort = options.get("effort") or settings.hermes_effort or "low"
        effort_arg = f"--reasoning={effort}" if effort else ""

        self._last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        # Use --query-file - so prompts reach Hermes verbatim through stdin:
        # nothing is shell-interpreted (quotes, backticks, $() stay intact).
        args = [
            "chat",
            "--query-file", "-",
            "--oneshot",
            "--format", "stream-json",
            "--no-restore-cwd",
            # Pure chat: NO toolsets. With tools enabled Hermes explores
            # (terminal, web, skills) and the user sees "progress" instead of
            # an answer. -t "" = answer directly.
            "-t", "",
            # Light mode: skip AGENTS.md / SOUL.md / memory / skill preloads —
            # nothing needed for plain chat, saves startup time and RAM.
            "--ignore-rules",
            # Safety net if a future flag re-enables tools.
            "--max-turns", "4",
            "--run-budget", "300",
        ]
        if model and model not in ("idk", "default"):
            args += [f"--model={model}"]
        if effort_arg:
            args.append(effort_arg)

        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            # Hermes writes its logs to stderr; never PIPE it — an unread full
            # buffer blocks Hermes mid-stream (classic subprocess deadlock).
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
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=HERMES_TURN_TIMEOUT + 60)
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
                if ev_type == "text":
                    chunk = event.get("text", "")
                    if chunk:
                        emitted = True
                        yield chunk
                elif ev_type == "result":
                    tokens = event.get("tokens") or {}
                    if tokens:
                        self._last_usage = {
                            "prompt_tokens": tokens.get("input", 0),
                            "completion_tokens": tokens.get("output", 0),
                            "total_tokens": tokens.get("total", 0),
                            "cost": 0.0,
                        }
                    err = event.get("error")
                    if err:
                        raise APIError(f"hermes: {err}", provider=self.name)
                    if not emitted:
                        text = event.get("text", "")
                        if text:
                            yield text
                    return
        except asyncio.TimeoutError:
            proc.kill()
            await self._bounded_wait(proc)
            raise APIError(f"hermes timed out after {HERMES_TURN_TIMEOUT}s", provider=self.name)
        except GeneratorExit:
            # Consumer stopped iterating (e.g. /stop mid-stream). Kill now —
            # never block on proc.wait() for a process that may run minutes.
            proc.kill()
            await self._bounded_wait(proc)
            raise
        finally:
            if proc.returncode is None:
                await self._bounded_wait(proc)

        if proc.returncode not in (0, None) and not emitted:
            raise APIError(f"hermes failed: exit code {proc.returncode}", provider=self.name)

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
        # stream-json result carries real tokens; zeros when absent. Never invent.
        return dict(self._last_usage)
