"""Injection of a user prompt into the live interactive hermes REPL.

When a native hermes session is active (selected via /resume), a plain-text
Telegram message is typed into the user's hermes REPL window on the desktop:
the workspace is focused (Hyprland), then the text is sent with wtype and the
Enter key pressed. The REPL processes the prompt in the session's own context,
so history, memory and skills all apply — exactly "continue the CLI session
from Telegram".

Safety gates: only the owner's machine (localhost), only when the bot's state
has an active native hermes session, only the hermes window (matched by kitty
title substring), and only when wtype + hyprctl are present.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

INJECT_TIMEOUT_S = 15.0


def _hypr_eval(code: str) -> None:
    """Dispatch a Hyprland eval command (dots-hyprland Lua dispatcher)."""
    if not shutil.which("hyprctl"):
        return
    asyncio.create_subprocess_exec(
        "hyprctl", "eval", code,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def find_hermes_window() -> Optional[int]:
    """Workspace id of the kitty window titled 'hermes', or None."""
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
    for c in clients:
        if "hermes" in (c.get("title") or "").lower():
            return (c.get("workspace") or {}).get("id")
    return None


async def inject_prompt_into_repl(prompt_text: str) -> bool:
    """Focus the hermes workspace and type the prompt + Enter.

    Returns True when the keystrokes were delivered (wtype exit 0). The REPL
    itself may still refuse (busy turn, approval panel open) — that shows up
    as no new activity, not as an injection failure.
    """
    if not shutil.which("wtype"):
        logger.warning("wtype missing — cannot inject into hermes REPL")
        return False
    ws = await find_hermes_window()
    if ws is None:
        logger.info("No hermes window on the desktop — skipping injection")
        return False

    if ws is not None:
        proc = await asyncio.create_subprocess_exec(
            "hyprctl", "eval",
            f"return hl.dispatch(hl.dsp.focus({{ workspace = {int(ws)} }}))",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        await asyncio.sleep(0.6)  # let the workspace switch render

    # wtype types literally; -M ctrl/j/k = paste-safe? No: keep it simple.
    # Single line only: the prompt is sent as-is (newlines would split into
    # multiple REPL submits; the REPL submits on Enter).
    one_line = prompt_text.replace("\n", " ").strip()
    if not one_line:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "wtype", "-s", "12", "--", one_line,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=INJECT_TIMEOUT_S)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("wtype failed: %s", e)
        return False
    if proc.returncode != 0:
        logger.warning("wtype exit %s", proc.returncode)
        return False

    # -k = type (press+release) the named key; -s = ms delay before it.
    # Key name must be xkb "Return" — "enter" is an unknown key (exit 1).
    try:
        proc = await asyncio.create_subprocess_exec(
            "wtype", "-k", "Return",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=INJECT_TIMEOUT_S)
    except (asyncio.TimeoutError, Exception):
        logger.warning("wtype Return tap failed — prompt pasted but NOT sent")
        return False
    if proc.returncode != 0:
        logger.warning("wtype Return tap exit %s — prompt pasted but NOT sent", proc.returncode)
        return False
    return True
