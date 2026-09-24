"""Browser automation adapter for DeepSeek Web (chat.deepseek.com)."""

import asyncio
import logging
from typing import Optional
from providers.browser.base import BrowserAIProvider
from browser.detector import ProgressState

logger = logging.getLogger(__name__)


class DeepSeekWebProvider(BrowserAIProvider):
    name = "deepseek_web"
    friendly_name = "DeepSeek Web"
    login_url = "https://chat.deepseek.com/"

    def matches_url(self, url: str) -> bool:
        return bool(url and "chat.deepseek.com" in url.lower())

    async def get_session_title(self, page) -> str:
        try:
            title = await page.title()
            title = title.replace("DeepSeek", "").replace(" - ", "").strip()
            return title or "Active DeepSeek session"
        except Exception:
            return "Active DeepSeek session"

    async def get_status(self, page) -> str:
        try:
            # Check for stop generating button
            stop_btn = page.locator("div[role='button']:has-text('Stop'), button:has-text('Stop')")
            if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
                return ProgressState.GENERATING.value

            # Check for thinking / streaming element
            thinking = page.locator(".ds-think-content, .ds-loading")
            if await thinking.count() > 0 and await thinking.first.is_visible():
                return ProgressState.GENERATING.value

            # Check input presence
            input_box = page.locator("textarea#chat-input, textarea[placeholder*='DeepSeek']")
            if await input_box.count() > 0 and await input_box.first.is_visible():
                return ProgressState.IDLE.value

            return ProgressState.UNKNOWN.value
        except Exception as e:
            logger.warning("Error detecting DeepSeek status: %s", e)
            return ProgressState.UNKNOWN.value

    async def send_prompt(self, page, text: str) -> bool:
        try:
            selectors = [
                "textarea#chat-input",
                "textarea[placeholder*='DeepSeek']",
                "textarea"
            ]
            input_loc = None
            for sel in selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    input_loc = loc
                    break

            if not input_loc:
                logger.error("DeepSeek input area not found")
                return False

            await input_loc.click()
            await page.wait_for_timeout(100)
            await input_loc.fill(text)
            await page.wait_for_timeout(200)

            # Look for send button or enter
            send_btn = page.locator("div[role='button']:has(svg):not(:has-text('Stop'))").last
            if await send_btn.count() > 0 and await send_btn.is_visible():
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")

            return True
        except Exception as e:
            logger.error("Failed to send prompt to DeepSeek: %s", e)
            return False

    async def get_last_response(self, page) -> str:
        try:
            selectors = [
                ".ds-markdown",
                ".chat-message-assistant",
                "div[data-role='assistant']"
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
            logger.warning("Error fetching last DeepSeek response: %s", e)
            return ""

    async def stop_generating(self, page) -> bool:
        try:
            stop_btn = page.locator("div[role='button']:has-text('Stop'), button:has-text('Stop')").first
            if await stop_btn.count() > 0 and await stop_btn.is_visible():
                await stop_btn.click()
                return True
            return False
        except Exception as e:
            logger.error("Error stopping DeepSeek: %s", e)
            return False

    async def check_login_status(self, page) -> bool:
        try:
            input_box = page.locator("textarea#chat-input")
            return await input_box.count() > 0 and await input_box.first.is_visible()
        except Exception:
            return False
