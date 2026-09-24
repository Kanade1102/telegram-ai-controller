"""Local SQLite database manager for API conversations, messages, sessions, and usage stats.

Does NOT store API keys or passwords.
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "controller.db"


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    tokens INTEGER DEFAULT 0,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS provider_settings (
                    provider TEXT PRIMARY KEY,
                    selected_model TEXT NOT NULL,
                    options TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS selected_sessions (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    # --- Conversations ---

    def create_conversation(self, name: str, provider: str, model: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (name, provider, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, provider, model, now, now)
            )
            conn.commit()
            return cursor.lastrowid

    def get_conversation(self, conv_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_conversations(self, limit: int = 50) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def rename_conversation(self, conv_id: int, new_name: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE conversations SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, conv_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- Messages ---

    def add_message(self, conversation_id: int, role: str, content: str, tokens: int = 0) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, tokens) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, now, tokens)
            )
            cursor.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            conn.commit()
            return cursor.lastrowid

    def get_messages(self, conversation_id: int, limit: int = 50) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC LIMIT ?",
                (conversation_id, limit)
            )
            return [dict(r) for r in cursor.fetchall()]

    # --- Provider Settings ---

    def get_provider_model(self, provider: str) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT selected_model FROM provider_settings WHERE provider = ?", (provider,))
            row = cursor.fetchone()
            return row["selected_model"] if row else None

    def set_provider_model(self, provider: str, model: str, options: Optional[dict] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        opt_json = json.dumps(options or {})
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO provider_settings (provider, selected_model, options, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    selected_model = excluded.selected_model,
                    options = excluded.options,
                    updated_at = excluded.updated_at
            """, (provider, model, opt_json, now))
            conn.commit()

    # --- Selected Sessions / Global State ---

    def get_session_val(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM selected_sessions WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_session_val(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO selected_sessions (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (key, value, now))
            conn.commit()

    def delete_session_val(self, key: str) -> None:
        with self._get_connection() as conn:
            conn.cursor().execute("DELETE FROM selected_sessions WHERE key = ?", (key,))
            conn.commit()

    # --- Usage Stats ---

    def record_usage(
        self,
        conversation_id: Optional[int],
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float = 0.0
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        total = prompt_tokens + completion_tokens
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO usage_stats (conversation_id, provider, model, prompt_tokens, completion_tokens, total_tokens, cost, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (conversation_id, provider, model, prompt_tokens, completion_tokens, total, cost, now))
            conn.commit()

    def get_usage_summary(self, conversation_id: Optional[int] = None) -> dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if conversation_id:
                cursor.execute("""
                    SELECT
                        COUNT(*) as request_count,
                        COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                        COALESCE(SUM(total_tokens), 0) as total_tokens,
                        COALESCE(SUM(cost), 0.0) as total_cost
                    FROM usage_stats
                    WHERE conversation_id = ?
                """, (conversation_id,))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as request_count,
                        COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                        COALESCE(SUM(total_tokens), 0) as total_tokens,
                        COALESCE(SUM(cost), 0.0) as total_cost
                    FROM usage_stats
                """)
            row = cursor.fetchone()
            return dict(row) if row else {
                "request_count": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_cost": 0.0
            }


db = Database()
