"""Tests for local Hermes REPL session detection (no real hermes execution)."""

import tempfile
import time
from pathlib import Path

from services.hermes_local import (
    _msg_text,
    _live_lease,
    _session_info,
    get_local_hermes_session,
    format_local_hermes,
)


def test_msg_text_string():
    assert _msg_text("hello") == "hello"


def test_msg_text_content_list():
    assert _msg_text([
        {"type": "text", "text": "part1"},
        {"type": "tool_result", "content": "out"},
        {"type": "text", "text": "part2"},
    ]) == "part1 out part2"


def make_db(path: Path, holder_pid: int, lease_ts: float, expires_ts: float,
            last_msg: tuple) -> None:
    import sqlite3
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE session_turn_leases (conversation_id TEXT, holder TEXT, acquired_at REAL, expires_at REAL)")
    con.execute("CREATE TABLE sessions (id TEXT, source TEXT, title TEXT, cwd TEXT, last_activity_at REAL, ended_at REAL)")
    con.execute("CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, timestamp REAL, active INTEGER)")
    con.execute("INSERT INTO session_turn_leases VALUES ('s1', ?, ?, ?)",
                (f"pid={holder_pid}:turn=x:platform=cli", lease_ts, expires_ts))
    con.execute("INSERT INTO sessions VALUES ('s1', 'cli', 'My session', '/tmp/x', ?, NULL)", (lease_ts,))
    con.execute("INSERT INTO messages VALUES ('s1', ?, ?, ?, 1)", (*last_msg, lease_ts))
    con.commit()
    con.close()


def test_live_lease_generating():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "s.db"
        now = time.time()
        make_db(db, holder_pid=4242, lease_ts=now - 30, expires_ts=now + 300,
                last_msg=("user", "fix the build"))
        info = get_local_hermes_session(pids=[4242], db_path=db)
        assert info is not None
        assert info["status"] == "GENERATING"
        assert 25 <= info["elapsed"] <= 35
        assert info["prompt"] == "fix the build"
        assert info["session_id"] == "s1"


def test_expired_lease_is_idle():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "s.db"
        now = time.time()
        make_db(db, holder_pid=4242, lease_ts=now - 900, expires_ts=now - 600,
                last_msg=("assistant", "build fixed"))
        info = get_local_hermes_session(pids=[4242], db_path=db)
        assert info is not None
        assert info["status"] == "IDLE"
        assert info["elapsed"] is None
        assert info["prompt"] == "build fixed"


def test_no_pids_returns_none():
    assert get_local_hermes_session(pids=[], db_path=Path("/nonexistent")) is None


def test_non_interactive_holder_ignored():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "s.db"
        now = time.time()
        # lease held by a pid NOT in pids list -> no live turn reported
        make_db(db, holder_pid=9999, lease_ts=now - 10, expires_ts=now + 300,
                last_msg=("user", "hi"))
        info = get_local_hermes_session(pids=[4242], db_path=db)
        assert info is None or info["status"] == "IDLE"


def test_format_generating():
    text = format_local_hermes({
        "status": "GENERATING",
        "elapsed": 125.0,
        "prompt": "Explain `state.db`",
        "title": "My session",
        "cwd": "/home/user/project",
    })
    assert "GENERATING" in text
    assert "2m 05s" in text
    assert "My session" in text
    assert "/home/user/project" in text
    assert "`Explain 'state.db'`" in text
