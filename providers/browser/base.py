"""Base interface for browser-based AI providers."""

from abc import ABC, abstractmethod
import logging
from typing import Optional
from browser.detector import ProgressState

logger = logging.getLogger(__name__)


class BrowserAIProvider(ABC):
    name: str = ""
    friendly_name: str = ""
    login_url: str = ""

    @abstractmethod
    def matches_url(self, url: str) -> bool:
        """Return True if this provider manages the given URL."""
        pass

    @abstractmethod
    async def get_session_title(self, page) -> str:
        """Extract the current conversation or session title from the page."""
        pass

    @abstractmethod
    async def get_status(self, page) -> str:
        """Inspect page DOM and indicators to return ProgressState."""
        pass

    @abstractmethod
    async def send_prompt(self, page, text: str) -> bool:
        """Send prompt into the active chat input and submit."""
        pass

    @abstractmethod
    async def get_last_response(self, page) -> str:
        """Return the latest visible response from the assistant."""
        pass

    @abstractmethod
    async def stop_generating(self, page) -> bool:
        """Click stop button if currently generating."""
        pass

    @abstractmethod
    async def check_login_status(self, page) -> bool:
        """Check whether user is currently authenticated and ready to prompt."""
        pass
