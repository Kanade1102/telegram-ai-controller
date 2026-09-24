"""Official Google Gemini API provider using REST interface."""

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

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAPIProvider(APIProvider):
    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.name = "gemini_api"
        self.friendly_name = "Gemini API"
        self.api_key = api_key or settings.gemini_api_key or ""
        self.default_model = default_model or settings.gemini_default_model or "gemini-3.6-flash"
        self._cached_models: list[str] = []
        self._cache_time: float = 0
        self._last_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0
        }

    def _normalize_model_name(self, model: str) -> str:
        """Strip 'models/' prefix if provided."""
        if model.startswith("models/"):
            return model[7:]
        return model

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
            raise AuthError(f"HTTP {status} — Gemini authentication failed: {err_msg}", status_code=status, provider=self.name)
        elif status == 429:
            raise RateLimitError(f"HTTP 429 — Gemini rate limit exceeded: {err_msg}", status_code=status, provider=self.name)
        elif status == 404:
            raise ModelNotFoundError(f"HTTP 404 — Gemini model not found: {err_msg}", status_code=status, provider=self.name)
        elif status >= 500:
            raise ServerError(f"HTTP {status} — Gemini server error: {err_msg}", status_code=status, provider=self.name)
        else:
            raise APIError(f"HTTP {status} — Gemini error: {err_msg}", status_code=status, provider=self.name)

    async def test_connection(self) -> tuple[bool, str, float]:
        start = time.perf_counter()
        if not self.api_key:
            return False, "GEMINI_API_KEY not configured", 0.0

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    f"{GEMINI_BASE_URL}/models",
                    headers={"x-goog-api-key": self.api_key}
                )
                latency = (time.perf_counter() - start) * 1000
                if res.status_code == 200:
                    return True, "Connected", latency
                elif res.status_code in (400, 401, 403):
                    raise AuthError("Invalid Gemini API key", status_code=res.status_code, provider=self.name)
                elif res.status_code == 429:
                    raise RateLimitError("Gemini quota/rate limit exceeded", status_code=res.status_code, provider=self.name)
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
        if not refresh and self._cached_models and (now - self._cache_time) < settings.model_cache_seconds:
            return self._cached_models

        if not self.api_key:
            return [self.default_model]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(
                    f"{GEMINI_BASE_URL}/models",
                    headers={"x-goog-api-key": self.api_key}
                )
                if res.status_code != 200:
                    self._handle_http_error(res)

                data = res.json()
                models = []
                for item in data.get("models", []):
                    # Filter models supporting generateContent
                    methods = item.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        name = item.get("name", "")
                        clean_name = self._normalize_model_name(name)
                        if clean_name:
                            models.append(clean_name)

                if models:
                    self._cached_models = sorted(models)
                    self._cache_time = now
                    return self._cached_models
        except Exception as e:
            logger.warning("Failed to list Gemini models: %s", e)
            if self._cached_models:
                return self._cached_models
            if self.default_model:
                return [self.default_model]
            raise

        return [self.default_model]

    async def send_message(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        **options: Any
    ) -> AsyncGenerator[str, None]:
        if not self.api_key:
            raise AuthError("GEMINI_API_KEY is not configured", provider=self.name)

        chosen_model = self._normalize_model_name(model or self.default_model)
        if not chosen_model:
            raise APIError("No Gemini model specified", provider=self.name)

        # Convert standard OpenAI-style messages to Gemini contents structure
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content_text = msg.get("content", "")
            # Gemini accepts 'user' and 'model'
            gemini_role = "model" if role in ("assistant", "model") else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content_text}]
            })

        payload = {
            "contents": contents,
            **options
        }

        self._last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        endpoint = f"{GEMINI_BASE_URL}/models/{chosen_model}:streamGenerateContent?alt=sse"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.api_key
                    },
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
                                # Extract token usage
                                if "usageMetadata" in chunk:
                                    um = chunk["usageMetadata"]
                                    self._last_usage = {
                                        "prompt_tokens": um.get("promptTokenCount", 0),
                                        "completion_tokens": um.get("candidatesTokenCount", 0),
                                        "total_tokens": um.get("totalTokenCount", 0),
                                        "cost": 0.0
                                    }

                                # Extract candidates
                                candidates = chunk.get("candidates", [])
                                if candidates:
                                    content = candidates[0].get("content", {})
                                    parts = content.get("parts", [])
                                    for part in parts:
                                        text = part.get("text", "")
                                        if text:
                                            yield text
                            except json.JSONDecodeError:
                                continue
        except (AuthError, RateLimitError, ModelNotFoundError, ServerError):
            raise
        except httpx.TimeoutException:
            raise APIError("Gemini request timed out", provider=self.name)
        except Exception as e:
            raise APIError(f"Gemini API error: {e}", provider=self.name)

    async def get_usage(self) -> dict[str, Any]:
        return dict(self._last_usage)
