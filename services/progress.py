"""Progress checker formatting progress for both browser and API sessions."""

import logging
from typing import Optional, Any
from browser.manager import browser_manager
from browser.detector import ProgressState, get_provider_display_name
from services.screenshot import screenshot_service
from services.task_manager import task_manager, TaskStatus
from services.session_manager import session_manager
from services.model_manager import model_manager

logger = logging.getLogger(__name__)


class ProgressService:
    async def get_progress(self) -> dict[str, Any]:
        """Collect current progress across active browser tab or active API task."""
        active_task = task_manager.get_active_task()
        state = session_manager.state

        # 1. API Backend Progress
        if state.active_mode == "api" or (active_task and active_task.backend == "api"):
            if not active_task:
                return {
                    "backend": "api",
                    "status": "IDLE",
                    "screenshot_path": None,
                    "text": (
                        "📊 *AI Progress*\n\n"
                        f"*Backend:* {get_provider_display_name(state.active_provider)}\n"
                        f"*Model:* `{model_manager.get_selected_model(state.active_provider)}`\n"
                        "*Status:* IDLE\n\n"
                        "No prompt is currently running."
                    )
                }

            tokens_info = ""
            usage = active_task.usage
            if usage.get("prompt_tokens") or usage.get("completion_tokens"):
                tokens_info = (
                    f"\n\n*Tokens:*\n"
                    f"Input: {usage.get('prompt_tokens', 0):,}\n"
                    f"Output: {usage.get('completion_tokens', 0):,}"
                )

            last_snippet = active_task.latest_output[-300:] if active_task.latest_output else "None yet"
            # Escape markdown special characters loosely or use quote block
            text = (
                f"📊 *AI Progress*\n\n"
                f"*Backend:* {get_provider_display_name(active_task.provider)}\n"
                f"*Model:* `{active_task.model}`\n"
                f"*Status:* {active_task.status.value}\n\n"
                f"*Elapsed:*\n{active_task.elapsed_formatted}\n\n"
                f"*Received:*\n{len(active_task.latest_output):,} characters{tokens_info}\n\n"
                f"*Latest output:*\n`{last_snippet}`"
            )

            return {
                "backend": "api",
                "status": active_task.status.value,
                "screenshot_path": None,
                "text": text
            }

        # 2. Browser Backend Progress
        active_session = await browser_manager.get_active_session()
        if not active_session:
            # Fallback desktop screenshot if configured
            shot_path = await screenshot_service.capture(page=None)
            return {
                "backend": "browser",
                "status": "UNKNOWN",
                "screenshot_path": shot_path,
                "text": (
                    "📊 *AI Progress*\n\n"
                    "Status: UNKNOWN\n\n"
                    "⚠️ No active browser AI tab found. Ensure Chrome/Chromium is running with CDP enabled."
                )
            }

        page = active_session["page"]
        provider = active_session["provider"]
        title = active_session["title"]

        # Capture screenshot
        shot_path = await screenshot_service.capture(page=page)

        # Inspect DOM status
        status = await provider.get_status(page)
        last_resp = await provider.get_last_response(page)

        activity_desc = "Ready for input."
        if status == ProgressState.GENERATING.value:
            activity_desc = "The AI is currently producing a response."
        elif status == ProgressState.ERROR.value:
            activity_desc = "An error banner or issue was detected on the page."

        snippet = (last_resp[:300] + "...") if len(last_resp) > 300 else last_resp
        if not snippet:
            snippet = "No response text visible yet."

        msg_text = (
            f"📊 *AI Progress*\n\n"
            f"*Provider:* {active_session['provider_name']}\n"
            f"*Status:* {status}\n"
            f"*Session:* {title}\n\n"
            f"*Current activity:*\n{activity_desc}\n\n"
            f"*Latest visible text:*\n`{snippet}`"
        )

        if not shot_path:
            msg_text += (
                "\n\n"
                "⚠️ Screenshot unavailable (capture failed). Use `/shot` to retry."
            )

        return {
            "backend": "browser",
            "status": status,
            "screenshot_path": shot_path,
            "text": msg_text,
            "last_response": last_resp
        }


progress_service = ProgressService()
