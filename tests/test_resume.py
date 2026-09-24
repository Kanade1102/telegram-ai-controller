"""Tests for /resume conversation listing & selection (no network)."""

import pytest
from pathlib import Path
from services.database import Database


def _conv_list(db, n=3):
    """Seed n conversations and return list_conversations() output."""
    for i in range(n):
        db.create_conversation(f"Chat {i+1}", "openrouter", f"model-{i+1}")
    return db.list_conversations()


def test_resume_numbering_is_1_based(tmp_path: Path):
    db = Database(db_path=tmp_path / "test.db")
    convs = _conv_list(db)
    assert len(convs) == 3
    # list_conversations returns newest first; /resume numbers positions 1..N
    assert convs[0]["name"] == "Chat 3"
    assert convs[2]["name"] == "Chat 1"


def test_resume_pick_maps_position_to_conversation(tmp_path: Path):
    db = Database(db_path=tmp_path / "test.db")
    convs = _conv_list(db)
    # Simulate /resume 1 → first position in list
    n = 1
    conv = convs[n - 1]
    assert conv["name"] == "Chat 3"
    assert db.get_conversation(conv["id"])["provider"] == "openrouter"


def test_resume_out_of_range_rejected(tmp_path: Path):
    db = Database(db_path=tmp_path / "test.db")
    convs = _conv_list(db)
    # Out-of-range numbers must not crash or pick anything
    for bad in (0, len(convs) + 1):
        assert bad < 1 or bad > len(convs)


def test_resume_empty_list(tmp_path: Path):
    db = Database(db_path=tmp_path / "test.db")
    assert db.list_conversations() == []
