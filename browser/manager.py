"""Browser and CDP connection manager using Playwright.

Connects to existing user Chromium session via Chrome DevTools Protocol.
Never creates temporary browser sessions or modifies browser credentials.
"""

import asyncio
import logging
from typing import Optional, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from config import settings
from providers.browser import get_browser_provider_by_url, BROWSER_PROVIDERS
from browser.detector import ProgressState

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self, cdp_url: Optional[str] = None):
        self.cdp_url = cdp_url or settings.browser_cdp_url
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._active_page_id: Optional[str] = None
        self._lock = asyncio.Lock()

    async def is_connected(self) -> bool:
        if not self._browser:
            return False
        try:
            return self._browser.is_connected()
        except Exception:
            return False

    async def connect(self) -> bool:
        """Connect to running Chromium instance via CDP."""
        async with self._lock:
            if await self.is_connected():
                return True
            try:
                if not self._playwright:
                    self._playwright = await async_playwright().start()
                logger.info("Connecting to browser CDP at %s...", self.cdp_url)
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    endpoint_url=self.cdp_url,
                    timeout=5000
                )
                logger.info("Successfully connected to browser via CDP")
                return True
            except Exception as e:
                logger.warning("CDP connection failed (%s): %s", self.cdp_url, e)
                self._browser = None
                return False

    async def disconnect(self) -> None:
        async with self._lock:
            try:
                if self._browser:
                    await self._browser.close()
            except Exception as e:
                logger.debug("Error closing browser connection: %s", e)
            finally:
                self._browser = None
            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception as e:
                logger.debug("Error stopping playwright: %s", e)
            finally:
                self._playwright = None

    async def get_all_pages(self) -> list[Page]:
        """Get all open pages across all contexts."""
        if not await self.is_connected():
            connected = await self.connect()
            if not connected or not self._browser:
                return []
        pages = []
        for ctx in self._browser.contexts:
            pages.extend(ctx.pages)
        return pages

    async def get_ai_sessions(self) -> list[dict[str, Any]]:
        """List open tabs matching known AI providers."""
        pages = await self.get_all_pages()
        sessions = []
        for idx, page in enumerate(pages, start=1):
            try:
                url = page.url
                provider = get_browser_provider_by_url(url)
                if provider:
                    title = await provider.get_session_title(page)
                    page_id = str(id(page))
                    is_active = (self._active_page_id == page_id) or (self._active_page_id is None and len(sessions) == 0)
                    sessions.append({
                        "index": len(sessions) + 1,
                        "id": page_id,
                        "provider_key": provider.name,
                        "provider_name": provider.friendly_name,
                        "title": title,
                        "url": url,
                        "active": is_active,
                        "page": page,
                        "provider": provider,
                    })
            except Exception as e:
                logger.debug("Error inspecting page: %s", e)
        return sessions

    async def get_active_session(self) -> Optional[dict[str, Any]]:
        """Get currently selected AI tab or auto-select if only one available."""
        sessions = await self.get_ai_sessions()
        if not sessions:
            return None

        # If only one tab open, auto-select it
        if len(sessions) == 1:
            self._active_page_id = sessions[0]["id"]
            sessions[0]["active"] = True
            return sessions[0]

        # Match active page id
        if self._active_page_id:
            for s in sessions:
                if s["id"] == self._active_page_id:
                    s["active"] = True
                    return s

        # Default to first session
        self._active_page_id = sessions[0]["id"]
        sessions[0]["active"] = True
        return sessions[0]

    async def select_session(self, identifier: str) -> Optional[dict[str, Any]]:
        """Select session by 1-based index or provider name (e.g. '1', 'chatgpt')."""
        sessions = await self.get_ai_sessions()
        if not sessions:
            return None

        clean_id = identifier.strip().lower()
        # 1. By index
        if clean_id.isdigit():
            idx = int(clean_id)
            for s in sessions:
                if s["index"] == idx:
                    self._active_page_id = s["id"]
                    return s

        # 2. By provider key or name
        for s in sessions:
            if clean_id in s["provider_key"] or clean_id in s["provider_name"].lower() or clean_id in s["title"].lower():
                self._active_page_id = s["id"]
                return s

        return None

    async def open_or_focus_tab(self, url: str) -> Optional[Page]:
        """Find existing tab with matching URL domain or open a new tab."""
        if not await self.is_connected():
            connected = await self.connect()
            if not connected or not self._browser:
                return None

        pages = await self.get_all_pages()
        for p in pages:
            if url.split("/")[2] in p.url:  # Match domain
                try:
                    await p.bring_to_front()
                    self._active_page_id = str(id(p))
                    return p
                except Exception:
                    pass

        # Open in first context or create new page
        contexts = self._browser.contexts
        if contexts:
            page = await contexts[0].new_page()
        else:
            page = await self._browser.new_page()

        await page.goto(url, wait_until="domcontentloaded")
        self._active_page_id = str(id(page))
        return page

    async def take_screenshot(self, page: Page, output_path: str) -> bool:
        """Capture browser-native screenshot."""
        try:
            await page.screenshot(path=output_path, full_page=False)
            return True
        except Exception as e:
            logger.error("Failed to capture browser screenshot: %s", e)
            return False


browser_manager = BrowserManager()
