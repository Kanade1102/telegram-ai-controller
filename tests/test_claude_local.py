"""Tests for local Claude Code session detection (no real claude execution)."""

import time
from services.claude_local import decide_status, _msg_text, _parse_ts, format_local_claude


def test_parse_ts_zulu():
    from datetime import datetime, timezone
    ts = _parse_ts("2026-09-24T15:51:05.374Z")
    expected = datetime(2026, 9, 24, 15, 51, 5, 374000, tzinfo=timezone.utc).timestamp()
    assert ts is not None
    assert abs(ts - expected) < 0.001


def test_parse_ts_bad():
    assert _parse_ts("not-a-date") is None
    assert _parse_ts(None) is None


def test_msg_text_string():
    assert _msg_text("hello") == "hello"


def test_msg_text_content_list():
    assert _msg_text({
        "content": [
            {"type": "text", "text": "part1"},
            {"type": "tool_use", "id": "x"},
            {"type": "text", "text": "part2"},
        ]
    }) == "part1 part2"


def test_decide_generating_when_user_newer_than_assistant():
    now = time.time()
    ev = {"user_ts": now - 30, "asst_ts": now - 300}
    status, elapsed = decide_status(ev, now=now)
    assert status == "GENERATING"
    assert 25 <= elapsed <= 35


def test_decide_generating_when_no_assistant_reply():
    now = time.time()
    ev = {"user_ts": now - 60, "asst_ts": None}
    status, elapsed = decide_status(ev, now=now)
    assert status == "GENERATING"
    assert 55 <= elapsed <= 65


def test_decide_idle_when_assistant_newer():
    now = time.time()
    ev = {"user_ts": now - 100, "asst_ts": now - 10}
    status, elapsed = decide_status(ev, now=now)
    assert status == "IDLE"
    assert elapsed is None


def test_format_generating():
    text = format_local_claude({
        "status": "GENERATING",
        "elapsed": 125.0,
        "prompt": "Fix the fstab in `boot.img`",
        "cwd": "/home/user/project",
    })
    assert "GENERATING" in text
    assert "2m 05s" in text
    assert "/home/user/project" in text
    # backticks stripped from snippet (markdown safety)
    assert "`Fix the fstab in 'boot.img'`" in text


def test_format_idle():
    text = format_local_claude({
        "status": "IDLE",
        "elapsed": None,
        "prompt": "Done. Next step: flash.",
        "cwd": "",
    })
    assert "IDLE" in text
    assert "Last answer" in text
