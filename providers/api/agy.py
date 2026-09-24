"""Google Antigravity CLI (agy) provider.

Drives the locally installed, Google-account-authenticated `agy` binary.
No API keys involved: `agy` owns its own OAuth state in the OS credential store.

ponytail: print mode returns the full response in one shot (no token streaming,
no token usage). Upgrade path: `--input-format stream-json --output-format
stream-json` for per-turn NDJSON streaming if fine-grained progress is needed.
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

AGY_BIN_DEFAULT = "agy"
AGY_TURN_TIMEOUT = 300  # seconds; a full agentic turn can take minutes


class AgyCLIProvider(APIProvider):
    name = "agy"
    friendly_name = "AGY (Antigravity)"

    def __init__(
        self,
        cli_path: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.cli_path = cli_path or settings.agy_cli_path
        self.default_model = default_model or settings.agy_default_model
        self.api_key = ""  # agy uses Google OAuth; no API key exists
        self._cached_models: list[str] = []
        self._cache_time: float = 0
        self._last_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }

    def is_available(self) -> bool:
        if self.cli_path == AGY_BIN_DEFAULT:
            return shutil.which("agy") is not None
        return shutil.which(self.cli_path) is not None

    async def _run_agy(self, *args: str, timeout: float = 60.0) -> tuple[int, str, str]:
        """Run agy with argv (never a shell), returning (code, stdout, stderr)."""
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
            return -1, "", f"agy timed out after {timeout:.0f}s"
        return proc.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")

    async def test_connection(self) -> tuple[bool, str, float]:
        start = time.perf_counter()
        if not self.is_available():
            return False, f"agy binary not found ({self.cli_path})", 0.0
        code, out, err = await self._run_agy("models", timeout=180.0)
        latency = (time.perf_counter() - start) * 1000
        if code != 0:
            if "eligibility" in err.lower() or "unavailable" in err.lower() or "503" in err:
                return False, f"Antigravity service unavailable: {err.strip()[:120]}", latency
            return False, f"agy failed: {err.strip()[:120] or 'unknown error'}", latency
        if out.strip():
            return True, "Connected (Google account via agy)", latency
        return False, "no models returned", latency

    async def list_models(self, refresh: bool = False) -> list[str]:
        now = time.time()
        if not refresh and self._cached_models and (now - self._cache_time) < settings.model_cache_seconds:
            return self._cached_models

        code, out, err = await self._run_agy("models", timeout=180.0)
        if code != 0:
            if self._cached_models:
                return self._cached_models
            if self.default_model:
                return [self.default_model]
            raise APIError(f"agy models failed: {err.strip()[:120]}", provider=self.name)

        models: list[str] = []
        for line in out.splitlines():
            parts = line.split("\t", 1)
            model_id = parts[0].strip()
            if model_id:
                models.append(model_id)
        if models:
            self._cached_models = sorted(models)
            self._cache_time = now
            return self._cached_models
        if self.default_model:
            return [self.default_model]
        return []

    async def send_message(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        **options: Any
    ) -> AsyncGenerator[str, None]:
        if not self.is_available():
            raise AuthError(f"agy binary not found ({self.cli_path})", provider=self.name)

        chosen_model = model or self.default_model
        if not chosen_model:
            raise APIError("No agy model selected", provider=self.name)

        # Reasoning effort (low|medium|high) forwarded to agy --effort.
        effort = options.get("effort") or settings.agy_effort
        if effort and effort.lower() not in ("low", "medium", "high"):
            raise APIError(f"Invalid agy effort: {effort} (use low|medium|high)", provider=self.name)

        # Rebuild one prompt from history: newest message last. agy is stateless
        # per invocation; including history keeps multi-turn context intact.
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
            raise APIError("Empty prompt for agy", provider=self.name)

        self._last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        # stream-json yields NDJSON events with incremental text_delta chunks
        # and real usage metadata (never fabricated).
        proc = await asyncio.create_subprocess_exec(
            self.cli_path,
            f"--print={prompt_text}",
            f"--model={chosen_model}",
            f"--print-timeout={AGY_TURN_TIMEOUT}s",
            "--output-format=stream-json",
            *((f"--effort={effort}",) if effort else ()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        emitted = False
        try:
            assert proc.stdout is not None
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=AGY_TURN_TIMEOUT + 30)
                if not line:
                    break
                line_str = line.decode("utf-8", "replace").strip()
                if not line_str:
                    continue
                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                ev_type = event.get("event", "")
                if ev_type == "step_update":
                    su = event.get("step_update", {})
                    if su.get("step_type") != "agent_response":
                        continue
                    if "text_delta" in su and su["text_delta"]:
                        emitted = True
                        yield su["text_delta"]
                    if "usage" in su and su["usage"]:
                        u = su["usage"]
                        self._last_usage = {
                            "prompt_tokens": u.get("input_tokens", 0),
                            "completion_tokens": u.get("output_tokens", 0),
                            "total_tokens": u.get("total_tokens", 0),
                            "cost": 0.0,
                        }
                elif ev_type == "result":
                    res = event.get("result", {})
                    if res.get("status") != "SUCCESS":
                        err_msg = res.get("error") or res.get("status", "unknown error")
                        raise APIError(f"agy: {err_msg}", provider=self.name)
                    if "usage" in res and res["usage"]:
                        u = res["usage"]
                        self._last_usage = {
                            "prompt_tokens": u.get("input_tokens", 0),
                            "completion_tokens": u.get("output_tokens", 0),
                            "total_tokens": u.get("total_tokens", 0),
                            "cost": 0.0,
                        }
                    if not emitted:
                        resp = res.get("response", "")
                        if resp:
                            yield resp
                    return
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise APIError(f"agy timed out after {AGY_TURN_TIMEOUT}s", provider=self.name)
        finally:
            # drain pipes to avoid resource warnings
            try:
                await proc.wait()
            except Exception:
                pass

        stderr = (await proc.stderr.read()).decode("utf-8", "replace") if proc.stderr else ""
        if proc.returncode not in (0, None) and not emitted:
            err_s = stderr.strip()
            if "eligibility" in err_s.lower() or "503" in err_s or "unavailable" in err_s.lower():
                raise APIError("Antigravity service unavailable", provider=self.name)
            if "auth" in err_s.lower() or "login" in err_s.lower():
                raise AuthError(f"agy authentication issue: {err_s[:120]}", provider=self.name)
            raise APIError(f"agy failed: {err_s[:120] or 'unknown error'}", provider=self.name)

    async def get_usage(self) -> dict[str, Any]:
        # agy stream-json reports real usage; zeros when absent. Never invent.
        return dict(self._last_usage)
