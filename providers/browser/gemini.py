"""Browser automation adapter for Gemini Web (gemini.google.com)."""

import asyncio
import logging
from typing import Optional
from providers.browser.base import BrowserAIProvider
from browser.detector import ProgressState

logger = logging.getLogger(__name__)


class GeminiWebProvider(BrowserAIProvider):
    name = "gemini_web"
    friendly_name = "Gemini Web"
    login_url = "https://gemini.google.com/"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        return "gemini.google.com" in url.lower()

    async def get_session_title(self, page) -> str:
        try:
            title = await page.title()
            title = title.replace("Gemini", "").replace("Google", "").replace(" - ", "").strip()
            if not title:
                # Try reading active item in chat list
                active_tab = await page.locator("div[role='navigation'] li.selected, .conversation-title.selected").first.text_content(timeout=1000)
                if active_tab:
                    title = active_tab.strip()
            return title or "Active Gemini Session"
        except Exception:
            return "Active Gemini Session"

    async def get_status(self, page) -> str:
        try:
            # Check for visible stop button
            stop_btn = page.locator(
                "button[aria-label*='Stop'], button[aria-label*='Dừng'], button.stop-button"
            )
            if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
                return ProgressState.GENERATING.value

            # Check for loading spinner / progress indicators
            spinner = page.locator(
                "mat-progress-bar, div[role='progressbar'], .spark-spinner, .loading-indicator"
            )
            if await spinner.count() > 0 and await spinner.first.is_visible():
                return ProgressState.GENERATING.value

            # Check error state
            error_el = page.locator(".error-message, div[role='alert']")
            if await error_el.count() > 0 and await error_el.first.is_visible():
                err_text = await error_el.first.text_content()
                if err_text and ("error" in err_text.lower() or "something went wrong" in err_text.lower()):
                    return ProgressState.ERROR.value

            # Check for input area
            editor = page.locator("div.ql-editor, rich-textarea, div[contenteditable='true']")
            if await editor.count() > 0 and await editor.first.is_visible():
                return ProgressState.IDLE.value

            return ProgressState.UNKNOWN.value
        except Exception as e:
            logger.warning("Error detecting Gemini status: %s", e)
            return ProgressState.UNKNOWN.value

    async def send_prompt(self, page, text: str) -> bool:
        try:
            selectors = [
                "rich-textarea div.ql-editor",
                "div.ql-editor",
                "rich-textarea div[contenteditable='true']",
                "div[contenteditable='true'][aria-label*='prompt']",
                "div[contenteditable='true']",
                "textarea[aria-label*='prompt']"
            ]
            input_loc = None
            for sel in selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    input_loc = loc
                    break

            if not input_loc:
                logger.error("Gemini input area not found")
                return False

            await input_loc.click()
            await page.wait_for_timeout(100)

            # Insert text safely without touching system clipboard
            try:
                await input_loc.fill(text)
            except Exception:
                await page.keyboard.insert_text(text)

            await page.wait_for_timeout(200)

            send_btn = page.locator(
                "button[aria-label*='Send'], button[aria-label*='Gửi'], button.send-button"
            ).first

            if await send_btn.count() > 0 and await send_btn.is_visible() and await send_btn.is_enabled():
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")

            return True
        except Exception as e:
            logger.error("Failed to send prompt to Gemini Web: %s", e)
            return False

    async def get_last_response(self, page) -> str:
        try:
            selectors = [
                "message-content",
                ".model-response-text",
                ".response-container-content",
                "div.markdown",
                "model-response"
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
            logger.warning("Error fetching last Gemini response: %s", e)
            return ""

    async def stop_generating(self, page) -> bool:
        try:
            stop_btn = page.locator(
                "button[aria-label*='Stop'], button[aria-label*='Dừng'], button.stop-button"
            ).first
            if await stop_btn.count() > 0 and await stop_btn.is_visible():
                await stop_btn.click()
                return True
            return False
        except Exception as e:
            logger.error("Error stopping Gemini generation: %s", e)
            return False

    async def check_login_status(self, page) -> bool:
        try:
            # Check for input area
            editor = page.locator("div.ql-editor, rich-textarea")
            if await editor.count() > 0 and await editor.first.is_visible():
                return True

            # Check for sign-in link
            signin_btn = page.locator("a[href*='accounts.google.com'], button:has-text('Sign in'), button:has-text('Đăng nhập')")
            if await signin_btn.count() > 0 and await signin_btn.first.is_visible():
                return False

            return "gemini.google.com" in page.url
        except Exception:
            return False
