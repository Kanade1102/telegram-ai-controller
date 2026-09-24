"""Tests for SQLite database CRUD and usage operations."""

import pytest
from pathlib import Path
from services.database import Database


def test_database_conversation_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test.db"
    db = Database(db_path=db_file)

    # 1. Create
    conv_id = db.create_conversation("My Chat", "openrouter", "llama-3")
    assert conv_id > 0

    # 2. Get
    c = db.get_conversation(conv_id)
    assert c is not None
    assert c["name"] == "My Chat"
    assert c["provider"] == "openrouter"

    # 3. Rename
    renamed = db.rename_conversation(conv_id, "Renamed Chat")
    assert renamed is True
    assert db.get_conversation(conv_id)["name"] == "Renamed Chat"

    # 4. List
    convs = db.list_conversations()
    assert len(convs) == 1

    # 5. Delete
    deleted = db.delete_conversation(conv_id)
    assert deleted is True
    assert db.get_conversation(conv_id) is None


def test_database_messages(tmp_path: Path):
    db_file = tmp_path / "test.db"
    db = Database(db_path=db_file)
    conv_id = db.create_conversation("Chat", "openai", "gpt-4o")

    db.add_message(conv_id, "user", "Hello AI", tokens=5)
    db.add_message(conv_id, "assistant", "Hello human!", tokens=10)

    messages = db.get_messages(conv_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello AI"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hello human!"


def test_database_usage_stats(tmp_path: Path):
    db_file = tmp_path / "test.db"
    db = Database(db_path=db_file)
    conv_id = db.create_conversation("Chat", "openai", "gpt-4o")

    db.record_usage(conv_id, "openai", "gpt-4o", prompt_tokens=100, completion_tokens=50, cost=0.002)
    db.record_usage(conv_id, "openai", "gpt-4o", prompt_tokens=200, completion_tokens=100, cost=0.004)

    summary = db.get_usage_summary(conversation_id=conv_id)
    assert summary["request_count"] == 2
    assert summary["total_prompt_tokens"] == 300
    assert summary["total_completion_tokens"] == 150
    assert summary["total_tokens"] == 450
    assert pytest.approx(summary["total_cost"], 0.0001) == 0.006


def test_database_provider_model_preferences(tmp_path: Path):
    db_file = tmp_path / "test.db"
    db = Database(db_path=db_file)

    db.set_provider_model("openai", "gpt-4o-mini")
    db.set_provider_model("openrouter", "anthropic/claude-3.5-sonnet")

    assert db.get_provider_model("openai") == "gpt-4o-mini"
    assert db.get_provider_model("openrouter") == "anthropic/claude-3.5-sonnet"
    assert db.get_provider_model("nonexistent") is None
