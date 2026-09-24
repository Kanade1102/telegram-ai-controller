"""Detect locally running interactive Claude Code TUI sessions.

The bot's own `claude -p` print-mode runs are excluded (they are tracked by
the task manager instead). Only interactive TUI sessions (no -p flag in
/proc cmdline) with a session jsonl under ~/.claude/projects are reported.

ponytail: session discovery is a glob over ~/.claude/projects/*/*.jsonl.
Upgrade path: `claude status` JSON if Claude ever exposes live session state.
"""

import glob
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
TAIL_BYTES = 65536


def _interactive_claude_pids() -> list[int]:
    """PIDs of interactive claude TUI processes (print-mode -p runs excluded)."""
    pids: list[int] = []
    for entry in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(entry, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        argv = raw.split(b"\0")
        if not argv or b"claude" not in argv[0]:
            continue
        if b"-p" in argv:
            continue  # print mode: bot/CI run, tracked by the task manager
        try:
            pids.append(int(entry.split("/")[2]))
        except ValueError:
            continue
    return pids


def _msg_text(msg) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    parts.append(b["text"])
                elif b.get("type") == "tool_result" and b.get("content"):
                    c = b["content"]
                    parts.append(c if isinstance(c, str) else json.dumps(c)[:200])
            return " ".join(parts)
    return ""


def _parse_ts(ts) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def tail_event(path: str) -> dict:
    """Last user/assistant event timestamps, texts and cwd from a jsonl tail."""
    result = {"user_ts": None, "user_text": "", "asst_ts": None, "asst_text": "", "cwd": ""}
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return result
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("cwd"):
            result["cwd"] = ev["cwd"]
        t = ev.get("type")
        ts = _parse_ts(ev.get("timestamp"))
        if t == "user":
            result["user_ts"] = ts
            result["user_text"] = _msg_text(ev.get("message"))
        elif t == "assistant":
            result["asst_ts"] = ts
            result["asst_text"] = _msg_text(ev.get("message"))
    return result


def decide_status(ev: dict, now: Optional[float] = None) -> tuple[str, Optional[float]]:
    """('GENERATING'|'IDLE', elapsed_seconds) from a tail_event result."""
    now = now if now is not None else time.time()
    generating = bool(ev.get("user_ts")) and (
        not ev.get("asst_ts") or ev["user_ts"] > ev["asst_ts"]
    )
    if generating:
        return "GENERATING", now - ev["user_ts"]
    return "IDLE", None


def get_local_claude_session() -> Optional[dict]:
    """Live interactive Claude Code session info, or None."""
    if not _interactive_claude_pids():
        return None
    files = glob.glob(str(CLAUDE_PROJECTS_DIR / "*" / "*.jsonl"))
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    ev = tail_event(newest)
    if not ev["user_ts"] and not ev["asst_ts"]:
        return None
    status, elapsed = decide_status(ev)
    snippet = ev["user_text"] if status == "GENERATING" else ev["asst_text"]
    if not snippet:
        snippet = ev["asst_text"] or ev["user_text"]
    return {
        "status": status,
        "elapsed": elapsed,
        "prompt": snippet,
        "cwd": ev["cwd"],
        "file": newest,
    }


def format_local_claude(info: dict) -> str:
    """Telegram markdown report for a local claude session."""
    status = info["status"]
    lines = [
        "📊 *Claude Code (local session)*",
        "",
        f"*Status:* {status}",
    ]
    if info.get("cwd"):
        lines.append(f"*Dir:* `{info['cwd']}`")
    if status == "GENERATING" and info.get("elapsed"):
        m, s = divmod(int(info["elapsed"]), 60)
        lines += ["", f"*Elapsed:* {m}m {s:02d}s"]
    snippet = (info.get("prompt") or "").replace("`", "'")[:300]
    label = "*Prompt:*" if status == "GENERATING" else "*Last answer:*"
    lines += ["", f"{label} `{snippet or '—'}`"]
    return "\n".join(lines)
