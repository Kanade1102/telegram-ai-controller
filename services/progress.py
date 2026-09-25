"""Progress checker formatting progress for browser, API task and local CLIs.

One section per provider: bot's own task, local interactive claude REPL,
local interactive hermes REPL, and every open browser AI tab. No merging —
each section keeps its own provider name, status and detail.

Screenshot policy: the browser tab whose status is GENERATING gets focused
(bring_to_front) and captured; if none is generating, the active tab is
captured. The photo is returned even when other sections exist, so Telegram
always shows the provider whose progress the user asked about.
"""

import logging
import asyncio
import json
import shutil
from typing import Any, Optional
from browser.manager import browser_manager
from browser.detector import ProgressState, get_provider_display_name
from services.screenshot import screenshot_service
from services.task_manager import task_manager
from services.session_manager import session_manager
from services.model_manager import model_manager
from services import claude_local
from services import hermes_local

logger = logging.getLogger(__name__)


def pick_hypr_window(clients: list[dict], title_part: str) -> Optional[dict]:
    """Find a Hyprland client window whose title contains title_part."""
    for c in clients:
        if title_part in (c.get("title") or "").lower():
            return c
    return None


async def _focus_workspace(ws_id: int) -> bool:
    """Focus a Hyprland workspace via hyprctl eval (dots-hyprland Lua dispatcher)."""
    if not shutil.which("hyprctl"):
        return False
    code = f"hl.dispatch(hl.dsp.focus({{ workspace = {int(ws_id)} }}))"
    try:
        proc = await asyncio.create_subprocess_exec(
            "hyprctl", "eval", code,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        return True
    except Exception as e:
        logger.debug("hyprctl workspace focus failed: %s", e)
        return False


async def screenshot_cli_window(title_part: str) -> Optional[str]:
    """Switch to the workspace of the terminal window running title_part
    (e.g. 'hermes' or 'claude') and capture the screen with grim."""
    if not shutil.which("hyprctl"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "hyprctl", "clients", "-j",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        clients = json.loads(out or b"[]")
    except Exception as e:
        logger.debug("hyprctl clients failed: %s", e)
        return None
    win = pick_hypr_window(clients, title_part)
    if not win:
        return None
    ws = (win.get("workspace") or {}).get("id")
    if ws is not None:
        await _focus_workspace(ws)
        await asyncio.sleep(0.8)  # let the workspace switch render
    return await screenshot_service.capture(page=None, force_mode="desktop")


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

        # Screenshot target #1: the CLI terminal window, whenever a local
        # session exists — GENERATING gets priority over IDLE, and a
        # generating CLI beats the browser. Switching workspaces is the
        # Hyprland equivalent of switching tabs.
        cli_shot = None
        if hm_info and hm_info["status"] == "GENERATING":
            cli_shot = await screenshot_cli_window("hermes")
        if not cli_shot and cl_info and cl_info["status"] == "GENERATING":
            cli_shot = await screenshot_cli_window("claude")
        if not cli_shot and hm_info:
            cli_shot = await screenshot_cli_window("hermes")
        if not cli_shot and cl_info:
            cli_shot = await screenshot_cli_window("claude")

        # 4. Browser backend: every open AI tab, one section each.
        #    Screenshot target = the tab that is GENERATING; else active tab.
        sessions = []
        try:
            sessions = await browser_manager.get_ai_sessions()
        except Exception as e:
            logger.warning("Browser session check failed: %s", e)
        shot_target = None
        for s in sessions:
            page = s["page"]
            title = s["title"]
            try:
                status = await s["provider"].get_status(page)
            except Exception:
                status = ProgressState.UNKNOWN.value
            s["_status"] = status  # kept for the aggregate status below
            try:
                last_resp = await s["provider"].get_last_response(page)
            except Exception:
                last_resp = ""
            activity_desc = "Ready for input."
            if status == ProgressState.GENERATING.value:
                activity_desc = "The AI is currently producing a response."
                if shot_target is None:
                    shot_target = s
            elif status == ProgressState.ERROR.value:
                activity_desc = "An error banner or issue was detected on the page."
            snippet = (last_resp[:300] + "...") if len(last_resp) > 300 else last_resp
            snippet = snippet.replace("`", "'")
            sections.append(
                f"🌐 *Browser — {s['provider_name']}*\n"
                f"*Status:* {status}\n"
                f"*Session:* {title}\n"
                f"*Activity:* {activity_desc}\n"
                f"*Last visible:* `{snippet or 'No response text visible yet.'}`"
            )
        if shot_target is None:
            for s in sessions:
                if s.get("active"):
                    shot_target = s
                    break
        if shot_target is None and sessions:
            shot_target = sessions[0]

        # Screenshot: switch to the target provider's tab before capturing so
        # the photo always shows the tab whose progress is being reported.
        # A CLI shot wins: the desktop is already showing the CLI terminal.
        if shot_target and not cli_shot:
            try:
                await shot_target["page"].bring_to_front()
            except Exception as e:
                logger.debug("Could not focus tab for screenshot: %s", e)
            shot_path = await screenshot_service.capture(page=shot_target["page"])
        elif cli_shot:
            shot_path = cli_shot

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
        # Real status, not a constant: the /watch loop gates on this and
        # "ACTIVE" never matched its GENERATING check (notifications never
        # fired). GENERATING = bot task running OR a local CLI session
        # generating OR any browser tab generating.
        status = "IDLE"
        if active_task and active_task.status.value == "GENERATING":
            status = "GENERATING"
        elif (hm_info and hm_info["status"] == "GENERATING") or (
            cl_info and cl_info["status"] == "GENERATING"
        ):
            status = "GENERATING"
        else:
            for s in sessions:
                if s.get("_status") == ProgressState.GENERATING.value:
                    status = "GENERATING"
                    break
        if status == "IDLE" and (sections and not sections[-1].startswith("📊")):
            status = "ACTIVE"
        return {
            "backend": "multi",
            "status": status,
            "screenshot_path": shot_path,
            "text": text,
        }


progress_service = ProgressService()
