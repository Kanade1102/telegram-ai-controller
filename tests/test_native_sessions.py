"""Tests for local CLI session discovery."""

import json
import sqlite3
from pathlib import Path

import services.native_sessions as ns


def test_list_hermes_sessions_marks_open_current(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "HOME", tmp_path)
    root = tmp_path / ".hermes"
    root.mkdir()
    con = sqlite3.connect(root / "state.db")
    con.execute(
        "CREATE TABLE sessions (id TEXT, title TEXT, cwd TEXT, last_activity_at REAL, "
        "started_at REAL, ended_at REAL, source TEXT, hidden INTEGER, archived INTEGER)"
    )
    con.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
        [
            ("current-id", "Current work", "/a", 20, 10, None, "cli"),
            ("old-id", "Old work", "/b", 10, 5, 11, "cli"),
            ("oneshot-id", "Bot run", "/c", 30, 30, 31, "oneshot"),
        ],
    )
    con.commit()
    con.close()

    rows = ns.list_hermes_sessions()
    assert [r["session_id"] for r in rows] == ["current-id", "old-id"]
    assert rows[0]["current"] is True
    assert rows[1]["current"] is False


def test_list_claude_sessions_uses_jsonl_stem_and_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "HOME", tmp_path)
    path = tmp_path / ".claude" / "projects" / "-work" / "abc-123.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"type": "mode", "sessionId": "abc-123"}) + "\n" +
        json.dumps({"type": "user", "cwd": "/work", "message": {"content": "Fix resume"}}) + "\n"
    )
    rows = ns.list_claude_sessions()
    assert rows[0]["session_id"] == "abc-123"
    assert rows[0]["title"] == "Fix resume"
    assert rows[0]["cwd"] == "/work"
    assert rows[0]["current"] is True


def test_list_agy_sessions_reads_title_and_current_map(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "HOME", tmp_path)
    root = tmp_path / ".gemini" / "antigravity-cli"
    (root / "conversations").mkdir(parents=True)
    (root / "annotations").mkdir()
    (root / "cache").mkdir()
    (root / "conversations" / "agy-id.db").write_bytes(b"x")
    (root / "annotations" / "agy-id.pbtxt").write_text('title:"AGY work"\n')
    (root / "cache" / "last_conversations.json").write_text('{"/work":"agy-id"}')

    rows = ns.list_agy_sessions()
    assert rows[0]["session_id"] == "agy-id"
    assert rows[0]["title"] == "AGY work"
    assert rows[0]["current"] is True
