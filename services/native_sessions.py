"""Discover resumable sessions owned by local CLI providers."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

HOME = Path.home()


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def list_hermes_sessions(limit: int = 100) -> list[dict[str, Any]]:
    path = HOME / ".hermes" / "state.db"
    if not path.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        rows = con.execute(
            "SELECT id, COALESCE(title, ''), COALESCE(cwd, ''), "
            "COALESCE(last_activity_at, started_at), ended_at "
            "FROM sessions WHERE source = 'cli' AND hidden = 0 AND archived = 0 "
            "ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if "con" in locals():
            con.close()
    return [
        {
            "kind": "native",
            "provider": "hermes",
            "session_id": row[0],
            "title": row[1] or "Untitled Hermes session",
            "cwd": row[2],
            "modified": float(row[3] or 0),
            "time": _fmt_time(float(row[3] or 0)),
            "current": row[4] is None,
        }
        for row in rows
    ]


def _claude_meta(path: Path) -> tuple[str, str]:
    title = ""
    cwd = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 200:
                    break
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                cwd = ev.get("cwd") or cwd
                if ev.get("type") in ("summary", "custom-title"):
                    title = ev.get("summary") or ev.get("customTitle") or ev.get("title") or title
                if not title and ev.get("type") == "user":
                    msg = ev.get("message") or {}
                    content = msg.get("content", "") if isinstance(msg, dict) else ""
                    if isinstance(content, str):
                        candidate = content.strip().splitlines()[0][:80]
                        # Claude injects these local metadata wrappers as user
                        # records; they are not useful conversation titles.
                        if candidate and not candidate.startswith("<"):
                            title = candidate
        return title or "Untitled Claude session", cwd
    except OSError:
        return "Untitled Claude session", ""


def list_claude_sessions(limit: int = 100) -> list[dict[str, Any]]:
    root = HOME / ".claude" / "projects"
    if not root.is_dir():
        return []
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    result = []
    for path in files:
        title, cwd = _claude_meta(path)
        ts = path.stat().st_mtime
        result.append({
            "kind": "native",
            "provider": "claudecode",
            "session_id": path.stem,
            "title": title,
            "cwd": cwd,
            "modified": ts,
            "time": _fmt_time(ts),
            "current": False,
        })
    if result:
        result[0]["current"] = True
    return result


def _agy_title(session_id: str) -> str:
    path = HOME / ".gemini" / "antigravity-cli" / "annotations" / f"{session_id}.pbtxt"
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("title:"):
                return line.split(":", 1)[1].strip().strip('"') or "Untitled AGY session"
    except OSError:
        pass
    return "Untitled AGY session"


def list_agy_sessions(limit: int = 100) -> list[dict[str, Any]]:
    root = HOME / ".gemini" / "antigravity-cli"
    conv_dir = root / "conversations"
    if not conv_dir.is_dir():
        return []
    current_ids: set[str] = set()
    try:
        current_ids = set(json.loads((root / "cache" / "last_conversations.json").read_text()).values())
    except (OSError, ValueError, TypeError):
        pass
    files = sorted(conv_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "kind": "native",
            "provider": "agy",
            "session_id": path.stem,
            "title": _agy_title(path.stem),
            "cwd": "",
            "modified": path.stat().st_mtime,
            "time": _fmt_time(path.stat().st_mtime),
            "current": path.stem in current_ids,
        }
        for path in files
    ]


def list_native_sessions(limit_per_provider: int = 100) -> list[dict[str, Any]]:
    """All resumable local CLI sessions, grouped by provider, newest first."""
    return (
        list_hermes_sessions(limit_per_provider)
        + list_claude_sessions(limit_per_provider)
        + list_agy_sessions(limit_per_provider)
    )
