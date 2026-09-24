"""Anthropic Claude API provider."""

import json
import time
import httpx
import logging
from typing import AsyncGenerator, Optional, Any
from providers.api.base import (
    APIProvider, APIError, AuthError, RateLimitError, ModelNotFoundError, ServerError
)
from services.credential_manager import mask_secret
from config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(APIProvider):
    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.name = "anthropic"
        self.friendly_name = "Anthropic"
        self.api_key = api_key or settings.anthropic_api_key or ""
        self.default_model = default_model or settings.anthropic_default_model or "claude-3-5-sonnet-20241022"
        self._cached_models: list[str] = [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229"
        ]
        self._cache_time: float = 0
        self._last_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0
        }

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json"
        }
        return headers

    def _handle_http_error(self, response: httpx.Response) -> None:
        status = response.status_code
        try:
            err_data = response.json()
            err_msg = err_data.get("error", {}).get("message", response.text)
        except Exception:
            err_msg = response.text or f"HTTP {status}"

        if self.api_key and self.api_key in err_msg:
            err_msg = err_msg.replace(self.api_key, mask_secret(self.api_key))

        if status in (401, 403):
            raise AuthError(f"HTTP {status} — Anthropic authentication failed: {err_msg}", status_code=status, provider=self.name)
        elif status == 429:
            raise RateLimitError(f"HTTP 429 — Anthropic rate limit exceeded: {err_msg}", status_code=status, provider=self.name)
        elif status == 404:
            raise ModelNotFoundError(f"HTTP 404 — Anthropic model not found: {err_msg}", status_code=status, provider=self.name)
        elif status >= 500:
            raise ServerError(f"HTTP {status} — Anthropic server error: {err_msg}", status_code=status, provider=self.name)
        else:
            raise APIError(f"HTTP {status} — Anthropic error: {err_msg}", status_code=status, provider=self.name)

    async def test_connection(self) -> tuple[bool, str, float]:
        start = time.perf_counter()
        if not self.api_key:
            return False, "ANTHROPIC_API_KEY not configured", 0.0

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{ANTHROPIC_BASE_URL}/models", headers=self._get_headers())
                latency = (time.perf_counter() - start) * 1000
                if res.status_code == 200:
                    return True, "Connected", latency
                elif res.status_code in (401, 403):
                    raise AuthError("Invalid Anthropic API key", status_code=res.status_code, provider=self.name)
                elif res.status_code == 429:
                    raise RateLimitError("Anthropic rate limit exceeded", status_code=res.status_code, provider=self.name)
                else:
                    return False, f"HTTP {res.status_code}", latency
        except httpx.TimeoutException:
            return False, "Connection timeout", (time.perf_counter() - start) * 1000
        except (AuthError, RateLimitError):
            raise
        except Exception as e:
            return False, f"Error: {e}", (time.perf_counter() - start) * 1000

    async def list_models(self, refresh: bool = False) -> list[str]:
        now = time.time()
        if not refresh and (now - self._cache_time) < settings.model_cache_seconds and self._cached_models:
            return self._cached_models

        if not self.api_key:
            return self._cached_models

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(f"{ANTHROPIC_BASE_URL}/models", headers=self._get_headers())
                if res.status_code == 200:
                    data = res.json()
                    models = [m["id"] for m in data.get("data", []) if "id" in m]
                    if models:
                        self._cached_models = sorted(models)
                        self._cache_time = now
                        return self._cached_models
        except Exception as e:
            logger.debug("Could not query Anthropic models API: %s", e)

        return self._cached_models

    async def send_message(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        **options: Any
    ) -> AsyncGenerator[str, None]:
        if not self.api_key:
            raise AuthError("ANTHROPIC_API_KEY is not configured", provider=self.name)

        chosen_model = model or self.default_model

        # Anthropic messages format: extract system message if present
        system_text = ""
        claude_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_text += content + "\n"
            else:
                claude_messages.append({"role": role, "content": content})

        payload = {
            "model": chosen_model,
            "messages": claude_messages,
            "max_tokens": options.get("max_tokens", 4096),
            "stream": stream,
        }
        if system_text.strip():
            payload["system"] = system_text.strip()

        self._last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{ANTHROPIC_BASE_URL}/messages",
                    headers=self._get_headers(),
                    json=payload
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        self._handle_http_error(response)

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line_str = line.strip()
                        if line_str.startswith("data: "):
                            data_str = line_str[6:].strip()
                            try:
                                chunk = json.loads(data_str)
                                event_type = chunk.get("type")

                                if event_type == "message_start":
                                    usage = chunk.get("message", {}).get("usage", {})
                                    self._last_usage["prompt_tokens"] = usage.get("input_tokens", 0)
                                elif event_type == "message_delta":
                                    usage = chunk.get("usage", {})
                                    self._last_usage["completion_tokens"] = usage.get("output_tokens", 0)
                                    self._last_usage["total_tokens"] = self._last_usage["prompt_tokens"] + self._last_usage["completion_tokens"]
                                elif event_type == "content_block_delta":
                                    delta = chunk.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        yield delta.get("text", "")
                            except json.JSONDecodeError:
                                continue
        except (AuthError, RateLimitError, ModelNotFoundError, ServerError):
            raise
        except httpx.TimeoutException:
            raise APIError("Anthropic request timed out", provider=self.name)
        except Exception as e:
            raise APIError(f"Anthropic API error: {e}", provider=self.name)

    async def get_usage(self) -> dict[str, Any]:
        return dict(self._last_usage)
