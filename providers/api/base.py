"""Base class and common exceptions for direct API providers."""

from abc import ABC, abstractmethod
import time
import logging
from typing import AsyncGenerator, Optional, Any

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base API exception."""
    def __init__(self, message: str, status_code: Optional[int] = None, provider: str = ""):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.provider = provider


class AuthError(APIError):
    """Authentication or authorization failure (HTTP 401/403)."""
    pass


class RateLimitError(APIError):
    """Rate limit or quota exhaustion (HTTP 429)."""
    pass


class ModelNotFoundError(APIError):
    """Requested model not found (HTTP 404)."""
    pass


class ServerError(APIError):
    """Provider internal server error (HTTP 500+)."""
    pass


class APIProvider(ABC):
    name: str = ""
    friendly_name: str = ""
    default_model: str = ""

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str, float]:
        """Test connection to provider. Returns (success, status_message, latency_ms)."""
        pass

    @abstractmethod
    async def list_models(self, refresh: bool = False) -> list[str]:
        """List available models for this provider."""
        pass

    @abstractmethod
    async def send_message(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
        **options: Any
    ) -> AsyncGenerator[str, None]:
        """Send chat messages and yield streamed chunks of text."""
        pass

    @abstractmethod
    async def get_usage(self) -> dict[str, Any]:
        """Return the latest usage stats (prompt_tokens, completion_tokens, etc.)."""
        pass

    async def health(self) -> dict[str, Any]:
        """Comprehensive health report."""
        start = time.perf_counter()
        try:
            success, msg, latency = await self.test_connection()
            status = "AVAILABLE" if success else "UNAVAILABLE"
            return {
                "provider": self.name,
                "friendly_name": self.friendly_name,
                "status": status,
                "latency_ms": latency,
                "message": msg
            }
        except AuthError as e:
            return {
                "provider": self.name,
                "friendly_name": self.friendly_name,
                "status": "AUTH_ERROR",
                "latency_ms": (time.perf_counter() - start) * 1000,
                "message": str(e)
            }
        except Exception as e:
            return {
                "provider": self.name,
                "friendly_name": self.friendly_name,
                "status": "UNAVAILABLE",
                "latency_ms": (time.perf_counter() - start) * 1000,
                "message": str(e)
            }
