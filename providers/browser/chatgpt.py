"""Browser automation adapter for ChatGPT Web (chatgpt.com)."""

import asyncio
import logging
from typing import Optional
from providers.browser.base import BrowserAIProvider
from browser.detector import ProgressState

logger = logging.getLogger(__name__)


class ChatGPTWebProvider(BrowserAIProvider):
    name = "chatgpt_web"
    friendly_name = "ChatGPT Web"
    login_url = "https://chatgpt.com/"

    def matches_url(self, url: str) -> bool:
        if not url:
            return False
        u = url.lower()
        return "chatgpt.com" in u or "chat.openai.com" in u

    async def get_session_title(self, page) -> str:
        try:
            title = await page.title()
            title = title.replace("ChatGPT", "").replace(" - ", "").strip()
            if not title:
                # Try reading header or active nav item
                nav_item = await page.locator("nav a[aria-current='page'], nav a.active, li[data-testid*='history-item']").first.text_content(timeout=1000)
                if nav_item:
                    title = nav_item.strip()
            return title or "New chat"
        except Exception:
            return "Active ChatGPT session"

    async def get_status(self, page) -> str:
        try:
            # Check for visible stop generating button
            stop_btn = page.locator(
                "button[data-testid='stop-button'], button[aria-label*='Stop'], button[aria-label*='Dừng']"
            )
            if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
                return ProgressState.GENERATING.value

            # Check for streaming indicator in DOM
            streaming = page.locator(".result-streaming, [data-is-streaming='true'], .streaming")
            if await streaming.count() > 0 and await streaming.first.is_visible():
                return ProgressState.GENERATING.value

            # Check error banners
            error_el = page.locator(".text-red-500, div[role='alert'], .bg-red-500, [data-testid*='error']")
            if await error_el.count() > 0 and await error_el.first.is_visible():
                err_text = await error_el.first.text_content()
                if err_text and ("error" in err_text.lower() or "wrong" in err_text.lower() or "lỗi" in err_text.lower()):
                    return ProgressState.ERROR.value

            # Check for input element
            prompt_input = page.locator(
                "#prompt-textarea, div[contenteditable='true'], textarea[data-id='root']"
            )
            if await prompt_input.count() > 0 and await prompt_input.first.is_visible():
                return ProgressState.IDLE.value

            return ProgressState.UNKNOWN.value
        except Exception as e:
            logger.warning("Error detecting ChatGPT status: %s", e)
            return ProgressState.UNKNOWN.value

    async def send_prompt(self, page, text: str) -> bool:
        try:
            # Locate input
            selectors = [
                "#prompt-textarea",
                "div[contenteditable='true']#prompt-textarea",
                "div[contenteditable='true']",
                "textarea[data-id='root']",
                "textarea[placeholder*='Message']"
            ]
            input_loc = None
            for sel in selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    input_loc = loc
                    break

            if not input_loc:
                logger.error("ChatGPT prompt input area not found")
                return False

            # Focus and clear/fill input
            await input_loc.click()
            await page.wait_for_timeout(100)

            # Use fill() or insert_text() to preserve newlines, unicode, and emojis without clipboard corruption
            try:
                await input_loc.fill(text)
            except Exception:
                # If contenteditable div doesn't accept fill, use insert_text
                await page.keyboard.insert_text(text)

            await page.wait_for_timeout(200)

            # Locate send button or press Enter
            send_btn = page.locator(
                "button[data-testid='send-button'], button[aria-label*='Send'], button[aria-label*='Gửi']"
            ).first

            if await send_btn.count() > 0 and await send_btn.is_visible() and await send_btn.is_enabled():
                await send_btn.click()
            else:
                # Fallback: Enter without shift
                await page.keyboard.press("Enter")

            return True
        except Exception as e:
            logger.error("Failed to send prompt to ChatGPT: %s", e)
            return False

    async def get_last_response(self, page) -> str:
        try:
            # Select assistant responses
            selectors = [
                "[data-message-author-role='assistant']",
                "article:has([data-message-author-role='assistant'])",
                ".agent-turn",
                "div.markdown"
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
            logger.warning("Error fetching last ChatGPT response: %s", e)
            return ""

    async def stop_generating(self, page) -> bool:
        try:
            stop_btn = page.locator(
                "button[data-testid='stop-button'], button[aria-label*='Stop'], button[aria-label*='Dừng']"
            ).first
            if await stop_btn.count() > 0 and await stop_btn.is_visible():
                await stop_btn.click()
                return True
            return False
        except Exception as e:
            logger.error("Error clicking stop button on ChatGPT: %s", e)
            return False

    async def check_login_status(self, page) -> bool:
        try:
            # If prompt textarea is present, user is authenticated
            input_loc = page.locator("#prompt-textarea, div[contenteditable='true']")
            if await input_loc.count() > 0 and await input_loc.first.is_visible():
                return True

            # If login/sign-up buttons are present, user is not logged in
            auth_buttons = page.locator("button[data-testid='login-button'], a[href*='/auth/login']")
            if await auth_buttons.count() > 0 and await auth_buttons.first.is_visible():
                return False

            # Check url
            return "chatgpt.com" in page.url and "/auth/" not in page.url
        except Exception:
            return False
