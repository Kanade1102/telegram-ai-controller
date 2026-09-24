"""Browser automation adapter for Claude Web (claude.ai)."""

import asyncio
import logging
from typing import Optional
from providers.browser.base import BrowserAIProvider
from browser.detector import ProgressState

logger = logging.getLogger(__name__)


class ClaudeWebProvider(BrowserAIProvider):
    name = "claude_web"
    friendly_name = "Claude Web"
    login_url = "https://claude.ai/"

    def matches_url(self, url: str) -> bool:
        return bool(url and "claude.ai" in url.lower())

    async def get_session_title(self, page) -> str:
        try:
            title = await page.title()
            title = title.replace("Claude", "").replace(" - ", "").strip()
            return title or "Active Claude session"
        except Exception:
            return "Active Claude session"

    async def get_status(self, page) -> str:
        try:
            stop_btn = page.locator(
                "button[aria-label*='Stop response'], button[aria-label*='Stop generating'], button:has-text('Stop')"
            )
            if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
                return ProgressState.GENERATING.value

            streaming = page.locator("[data-is-streaming='true'], .animate-spin")
            if await streaming.count() > 0 and await streaming.first.is_visible():
                return ProgressState.GENERATING.value

            prompt_input = page.locator("div[contenteditable='true'], fieldset div[contenteditable='true']")
            if await prompt_input.count() > 0 and await prompt_input.first.is_visible():
                return ProgressState.IDLE.value

            return ProgressState.UNKNOWN.value
        except Exception as e:
            logger.warning("Error detecting Claude status: %s", e)
            return ProgressState.UNKNOWN.value

    async def send_prompt(self, page, text: str) -> bool:
        try:
            selectors = [
                "fieldset div[contenteditable='true']",
                "div[contenteditable='true']",
                "div[role='textbox']"
            ]
            input_loc = None
            for sel in selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    input_loc = loc
                    break

            if not input_loc:
                logger.error("Claude input area not found")
                return False

            await input_loc.click()
            await page.wait_for_timeout(100)

            try:
                await input_loc.fill(text)
            except Exception:
                await page.keyboard.insert_text(text)

            await page.wait_for_timeout(200)

            send_btn = page.locator("button[aria-label*='Send Message'], button:has(svg.lucide-arrow-up)").first
            if await send_btn.count() > 0 and await send_btn.is_visible() and await send_btn.is_enabled():
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")

            return True
        except Exception as e:
            logger.error("Failed to send prompt to Claude: %s", e)
            return False

    async def get_last_response(self, page) -> str:
        try:
            selectors = [
                "div.font-claude-message",
                "div[data-is-streaming]",
                "div.standard-markdown"
            ]
            for sel in selectors:
                loc = page.locator(sel)
                count = await loc.count()
                if count > 0:
                    last_el = loc.nth(count - 1)
                    text = await last_el.text_content()
                    if text and text.strip():
                        return text.strip()
            return ""
        except Exception as e:
            logger.warning("Error fetching last Claude response: %s", e)
            return ""

    async def stop_generating(self, page) -> bool:
        try:
            stop_btn = page.locator(
                "button[aria-label*='Stop response'], button[aria-label*='Stop generating']"
            ).first
            if await stop_btn.count() > 0 and await stop_btn.is_visible():
                await stop_btn.click()
                return True
            return False
        except Exception as e:
            logger.error("Error stopping Claude: %s", e)
            return False

    async def check_login_status(self, page) -> bool:
        try:
            input_loc = page.locator("div[contenteditable='true']")
            if await input_loc.count() > 0 and await input_loc.first.is_visible():
                return True
            return "claude.ai" in page.url and "/login" not in page.url
        except Exception:
            return False
