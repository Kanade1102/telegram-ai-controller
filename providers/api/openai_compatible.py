"""Reusable OpenAI-compatible API provider.

Supports OpenRouter, 9Router, DeepSeek, Local LM Studio, vLLM, LiteLLM, and generic endpoints.
"""

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


class OpenAICompatibleProvider(APIProvider):
    def __init__(
        self,
        name: str,
        friendly_name: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        default_model: str = "gpt-4o",
        custom_headers: Optional[dict[str, str]] = None,
        timeout: float = 60.0,
        extra_body: Optional[dict[str, Any]] = None
    ):
        self.name = name
        self.friendly_name = friendly_name or name.title()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.default_model = default_model
        self.custom_headers = custom_headers or {}
        self.timeout = timeout
        self.extra_body = extra_body or {}

        self._cached_models: list[str] = []
        self._cache_time: float = 0
        self._last_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0
        }

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            **self.custom_headers
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _handle_http_error(self, response: httpx.Response) -> None:
        status = response.status_code
        try:
            err_data = response.json()
            err_msg = err_data.get("error", {}).get("message", response.text)
        except Exception:
            err_msg = response.text or f"HTTP {status}"

        # Clean any raw secrets that might be reflected
        if self.api_key and self.api_key in err_msg:
            err_msg = err_msg.replace(self.api_key, mask_secret(self.api_key))

        if status in (401, 403):
            raise AuthError(f"HTTP {status} — Authentication failed: {err_msg}", status_code=status, provider=self.name)
        elif status == 429:
            raise RateLimitError(f"HTTP 429 — Rate limit exceeded or quota exhausted: {err_msg}", status_code=status, provider=self.name)
        elif status == 404:
            raise ModelNotFoundError(f"HTTP 404 — Model or endpoint not found: {err_msg}", status_code=status, provider=self.name)
        elif status >= 500:
            raise ServerError(f"HTTP {status} — Provider internal server error: {err_msg}", status_code=status, provider=self.name)
        else:
            raise APIError(f"HTTP {status} — Request error: {err_msg}", status_code=status, provider=self.name)

    async def test_connection(self) -> tuple[bool, str, float]:
        start = time.perf_counter()
        if not self.api_key and "127.0.0.1" not in self.base_url and "localhost" not in self.base_url:
            return False, "API key not configured", 0.0

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{self.base_url}/models", headers=self._get_headers())
                latency = (time.perf_counter() - start) * 1000
                if res.status_code == 200:
                    return True, "Connected", latency
                elif res.status_code in (401, 403):
                    raise AuthError("Invalid API key or unauthorized", status_code=res.status_code, provider=self.name)
                elif res.status_code == 429:
                    raise RateLimitError("Rate limit exceeded", status_code=res.status_code, provider=self.name)
                else:
                    return False, f"HTTP {res.status_code}", latency
        except httpx.TimeoutException:
            return False, "Connection timeout", (time.perf_counter() - start) * 1000
        except (httpx.ConnectError, httpx.NetworkError) as e:
            return False, f"Connection failed: {e.__class__.__name__}", (time.perf_counter() - start) * 1000
        except (AuthError, RateLimitError):
            raise
        except Exception as e:
            return False, f"Error: {e}", (time.perf_counter() - start) * 1000

    async def list_models(self, refresh: bool = False) -> list[str]:
        now = time.time()
        if not refresh and self._cached_models and (now - self._cache_time) < settings.model_cache_seconds:
            return self._cached_models

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(f"{self.base_url}/models", headers=self._get_headers())
                if res.status_code != 200:
                    self._handle_http_error(res)
                data = res.json()
                models: list[str] = []
                if "data" in data and isinstance(data["data"], list):
                    models = [m["id"] for m in data["data"] if "id" in m]
                elif isinstance(data, list):
                    models = [m.get("id", str(m)) for m in data]

                if models:
                    self._cached_models = sorted(models)
                    self._cache_time = now
                    return self._cached_models
        except Exception as e:
            logger.warning("Failed to fetch models for %s: %s", self.name, e)
            if self._cached_models:
                return self._cached_models
            if self.default_model:
                return [self.default_model]
            raise

        return [self.default_model] if self.default_model else []

    async def send_message(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        **options: Any
    ) -> AsyncGenerator[str, None]:
        chosen_model = model or self.default_model
        if not chosen_model:
            raise APIError("No model specified and no default model configured", provider=self.name)

        payload = {
            "model": chosen_model,
            "messages": messages,
            "stream": stream,
            **self.extra_body,
            **options
        }

        # Include stream_options if provider supports token reporting
        if stream:
            payload["stream_options"] = {"include_usage": True}

        self._last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload
                ) as response:
                    if response.status_code != 200:
                        # Read body for error description
                        await response.aread()
                        self._handle_http_error(response)

                    if not stream:
                        body = await response.aread()
                        data = json.loads(body.decode("utf-8"))
                        if "usage" in data:
                            u = data["usage"]
                            self._last_usage = {
                                "prompt_tokens": u.get("prompt_tokens", 0),
                                "completion_tokens": u.get("completion_tokens", 0),
                                "total_tokens": u.get("total_tokens", 0),
                                "cost": 0.0
                            }
                        choices = data.get("choices", [])
                        if choices:
                            yield choices[0].get("message", {}).get("content", "")
                        return

                    # Process SSE Stream
                    buffer = ""
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line_str = line.strip()
                        if line_str.startswith("data: "):
                            data_str = line_str[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                # Extract usage if included in chunk
                                if "usage" in chunk and chunk["usage"]:
                                    u = chunk["usage"]
                                    self._last_usage = {
                                        "prompt_tokens": u.get("prompt_tokens", 0),
                                        "completion_tokens": u.get("completion_tokens", 0),
                                        "total_tokens": u.get("total_tokens", 0),
                                        "cost": chunk.get("usage", {}).get("total_cost", 0.0)
                                    }
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                continue
        except (AuthError, RateLimitError, ModelNotFoundError, ServerError):
            raise
        except httpx.TimeoutException as e:
            raise APIError(f"Request timed out after {self.timeout}s", provider=self.name)
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise APIError(f"Network connection failed: {e}", provider=self.name)
        except Exception as e:
            raise APIError(f"Error communicating with {self.name}: {e}", provider=self.name)

    async def get_usage(self) -> dict[str, Any]:
        return dict(self._last_usage)
