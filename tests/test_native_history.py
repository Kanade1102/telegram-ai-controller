"""fetch_native_history: hermes DB + claude jsonl history extraction (isolated)."""

import json
import sqlite3

from services import native_sessions as ns


def test_fetch_agy_returns_empty():
    # agy has protobuf blobs, no plaintext history — by design.
    assert ns.fetch_native_history("agy", "whatever") == []


def test_fetch_unknown_provider_returns_empty():
    assert ns.fetch_native_history("nope", "x") == []


def test_hermes_history_tmp_db(tmp_path):
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    db = hermes_dir / "state.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
        "role TEXT, content TEXT, timestamp REAL)"
    )
    con.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
        [
            ("s1", "user", "hello", 1.0),
            ("s1", "tool", "internal", 2.0),
            ("s1", "assistant", "", 3.0),
            ("s1", "assistant", "hi there", 4.0),
        ],
    )
    con.commit()
    con.close()

    orig = ns.HOME
    ns.HOME = tmp_path
    try:
        h = ns.fetch_native_history("hermes", "s1", limit=3)
    finally:
        ns.HOME = orig
    assert h == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi there"}]


def test_claude_history_jsonl(tmp_path, monkeypatch):
    projects = tmp_path / ".claude" / "projects" / "proj1"
    projects.mkdir(parents=True)
    session = "abc-123"
    events = [
        {"type": "user", "timestamp": 1, "message": {"content": "<local-command>cd /tmp</local-command>"}},
        {"type": "user", "timestamp": 2, "message": {"content": "make a file"}},
        {"type": "assistant", "timestamp": 3, "message": {"content": [
            {"type": "tool_use", "name": "Write"},
            {"type": "text", "text": "Done, file created."},
        ]}},
        {"type": "summary", "timestamp": 4, "summary": "ignored"},
    ]
    with (projects / f"{session}.jsonl").open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    orig = ns.HOME
    ns.HOME = tmp_path
    try:
        h = ns.fetch_native_history("claudecode", session, limit=3)
    finally:
        ns.HOME = orig
    assert h == [
        {"role": "user", "content": "make a file"},
        {"role": "assistant", "content": "Done, file created."},
    ]


def test_claude_missing_session_returns_empty(tmp_path):
    orig = ns.HOME
    ns.HOME = tmp_path
    try:
        assert ns.fetch_native_history("claudecode", "missing") == []
    finally:
        ns.HOME = orig
