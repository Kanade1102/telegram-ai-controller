"""Progress checker formatting progress for browser, API task and local CLIs.

One section per provider: bot's own task, local interactive claude REPL,
local interactive hermes REPL, and the active browser tab. No merging —
each section keeps its own provider name, status and detail.
"""

import logging
from typing import Any
from browser.manager import browser_manager
from browser.detector import ProgressState, get_provider_display_name
from services.screenshot import screenshot_service
from services.task_manager import task_manager
from services.session_manager import session_manager
from services.model_manager import model_manager
from services import claude_local
from services import hermes_local

logger = logging.getLogger(__name__)


class ProgressService:
    async def get_progress(self) -> dict[str, Any]:
        """Collect per-provider progress sections and join them for Telegram."""
        sections: list[str] = []
        shot_path = None
        state = session_manager.state

        # 1. Bot's own running task (API or browser prompt).
        active_task = task_manager.get_active_task()
        if active_task:
            tokens_info = ""
            usage = active_task.usage
            if usage.get("prompt_tokens") or usage.get("completion_tokens"):
                tokens_info = (
                    f"\n*Tokens:* Input {usage.get('prompt_tokens', 0):,} / "
                    f"Output {usage.get('completion_tokens', 0):,}"
                )
            last_snippet = active_task.latest_output[-300:] if active_task.latest_output else "None yet"
            last_snippet = last_snippet.replace("`", "'")
            sections.append(
                f"🤖 *Bot task — {get_provider_display_name(active_task.provider)}*\n"
                f"*Status:* {active_task.status.value}\n"
                f"*Elapsed:* {active_task.elapsed_formatted}\n"
                f"*Received:* {len(active_task.latest_output):,} chars{tokens_info}\n"
                f"*Output:* `{last_snippet}`"
            )

        # 2. Local interactive Claude Code TUI session.
        try:
            cl_info = claude_local.get_local_claude_session()
        except Exception as e:
            logger.warning("Local claude session check failed: %s", e)
            cl_info = None
        if cl_info:
            sections.append(claude_local.format_local_claude(cl_info))

        # 3. Local interactive Hermes REPL session.
        try:
            hm_info = hermes_local.get_local_hermes_session()
        except Exception as e:
            logger.warning("Local hermes session check failed: %s", e)
            hm_info = None
        if hm_info:
            sections.append(hermes_local.format_local_hermes(hm_info))

        # 4. Browser backend: active AI tab.
        try:
            active_session = await browser_manager.get_active_session()
        except Exception as e:
            logger.warning("Browser session check failed: %s", e)
            active_session = None
        if active_session:
            page = active_session["page"]
            provider = active_session["provider"]
            title = active_session["title"]
            # Switch to this provider's tab before capturing, so the screenshot
            # always shows the tab whose progress we are reporting.
            try:
                await page.bring_to_front()
            except Exception as e:
                logger.debug("Could not focus tab for screenshot: %s", e)
            shot_path = await screenshot_service.capture(page=page)
            try:
                status = await provider.get_status(page)
            except Exception:
                status = ProgressState.UNKNOWN.value
            try:
                last_resp = await provider.get_last_response(page)
            except Exception:
                last_resp = ""
            activity_desc = "Ready for input."
            if status == ProgressState.GENERATING.value:
                activity_desc = "The AI is currently producing a response."
            elif status == ProgressState.ERROR.value:
                activity_desc = "An error banner or issue was detected on the page."
            snippet = (last_resp[:300] + "...") if len(last_resp) > 300 else last_resp
            snippet = snippet.replace("`", "'")
            sections.append(
                f"🌐 *Browser — {active_session['provider_name']}*\n"
                f"*Status:* {status}\n"
                f"*Session:* {title}\n"
                f"*Activity:* {activity_desc}\n"
                f"*Last visible:* `{snippet or 'No response text visible yet.'}`"
            )

        # 5. Fallback: nothing running anywhere.
        if not sections:
            sections.append(
                "📊 *AI Progress*\n\n"
                f"*Backend:* {get_provider_display_name(state.active_provider)}\n"
                f"*Model:* `{model_manager.get_selected_model(state.active_provider)}`\n"
                "*Status:* IDLE\n\n"
                "No prompt is currently running."
            )

        text = "\n\n".join(sections)
        # Screenshot only when the browser section alone produced one (Telegram
        # allows a single photo per message; multi-provider views stay text).
        if len(sections) > 1:
            shot_path = None
        return {
            "backend": "multi",
            "status": "ACTIVE",
            "screenshot_path": shot_path,
            "text": text,
        }


progress_service = ProgressService()
