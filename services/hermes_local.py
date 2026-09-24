"""Detect locally running interactive Hermes REPL sessions.

The bot's own `hermes chat --oneshot` runs are excluded (they are tracked by
the task manager instead). Only interactive REPL processes (argv = [python,
.../hermes] with nothing else) are considered. Live status comes from
state.db's session_turn_leases table: a lease whose expires_at is in the
future means a turn is generating right now.

ponytail: detection keys on the exact interactive argv shape. Upgrade path:
`hermes status` JSON if Hermes ever exposes live turn state non-interactively.
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATE_DB_DEFAULT = Path.home() / ".hermes" / "state.db"


def _interactive_hermes_pids() -> list[int]:
    """PIDs of interactive hermes REPLs (no subcommand, no gateway/chat)."""
    pids: list[int] = []
    for entry in sorted(Path("/proc").glob("[0-9]*/cmdline")):
        try:
            raw = entry.read_bytes()
        except OSError:
            continue
        argv = [a for a in raw.split(b"\0") if a]
        if len(argv) != 2:
            continue
        if not argv[1].endswith(b"/hermes"):
            continue
        try:
            pids.append(int(entry.parent.name))
        except ValueError:
            continue
    return pids


def _msg_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and b.get("text"):
                parts.append(b["text"])
            elif t == "tool_result" and b.get("content"):
                c = b["content"]
                parts.append(c if isinstance(c, str) else json.dumps(c)[:200])
        return " ".join(parts)
    return ""


def _live_lease(con: sqlite3.Connection, pids: list[int], now: float) -> Optional[tuple[str, float]]:
    """(session_id, acquired_at) of the live turn lease held by an interactive pid."""
    if not pids:
        return None
    rows = con.execute(
        "SELECT conversation_id, holder, acquired_at, expires_at FROM session_turn_leases"
    ).fetchall()
    for conv_id, holder, acquired, expires in rows:
        try:
            held_pid = int(str(holder).split("pid=", 1)[1].split(":", 1)[0])
        except (IndexError, ValueError):
            continue
        if held_pid not in pids:
            continue
        if expires and expires > now:
            return conv_id, acquired
    return None


def _session_info(con: sqlite3.Connection, session_id: str, want_user: bool = False) -> dict:
    row = con.execute(
        "SELECT title, cwd FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    title = (row[0] if row else "") or ""
    cwd = (row[1] if row and len(row) > 1 else "") or ""
    if want_user:
        last = con.execute(
            "SELECT role, content FROM messages WHERE session_id = ? AND active = 1 "
            "AND role = 'user' ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    else:
        last = con.execute(
            "SELECT role, content FROM messages WHERE session_id = ? AND active = 1 "
            "ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return {"title": title, "cwd": cwd, "role": last[0] if last else "", "text": _msg_text(last[1]) if last else ""}


def get_local_hermes_session(
    pids: Optional[list[int]] = None,
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    """Live interactive Hermes REPL session info, or None."""
    now = time.time()
    if pids is None:
        pids = _interactive_hermes_pids()
    if not pids:
        return None
    path = db_path or STATE_DB_DEFAULT
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        logger.warning("Hermes state.db open failed: %s", e)
        return None
    try:
        lease = _live_lease(con, pids, now)
        if lease:
            session_id, acquired = lease
            info = _session_info(con, session_id, want_user=True)
            return {
                "status": "GENERATING",
                "elapsed": max(0.0, now - float(acquired or now)),
                "prompt": info["text"] if info["role"] == "user" else "",
                "title": info["title"],
                "cwd": info["cwd"],
                "session_id": session_id,
            }
        # REPL open but no live turn: report idle + last visible content.
        row = con.execute(
            "SELECT id, title, cwd, last_activity_at FROM sessions "
            "WHERE source = 'cli' AND ended_at IS NULL "
            "ORDER BY last_activity_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        session_id = row[0]
        info = _session_info(con, session_id)
        return {
            "status": "IDLE",
            "elapsed": None,
            "prompt": info["text"] or info["title"],
            "title": info["title"],
            "cwd": info["cwd"],
            "session_id": session_id,
        }
    finally:
        con.close()


def format_local_hermes(info: dict) -> str:
    """Telegram markdown report for a local hermes session."""
    status = info["status"]
    lines = ["📊 *Hermes (local session)*", "", f"*Status:* {status}"]
    if info.get("title"):
        lines.append(f"*Session:* {info['title'][:80]}")
    if info.get("cwd"):
        lines.append(f"*Dir:* `{info['cwd']}`")
    if status == "GENERATING" and info.get("elapsed"):
        m, s = divmod(int(info["elapsed"]), 60)
        lines += ["", f"*Elapsed:* {m}m {s:02d}s"]
    snippet = (info.get("prompt") or "").replace("`", "'")[:300]
    label = "*Prompt:*" if status == "GENERATING" else "*Last output:*"
    lines += ["", f"{label} `{snippet or '—'}`"]
    return "\n".join(lines)
