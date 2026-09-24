"""API conversation manager providing persistent multi-turn history."""

import logging
from typing import Optional, Any
from services.database import db

logger = logging.getLogger(__name__)


class ConversationManager:
    def create_conversation(self, name: str, provider: str, model: str) -> dict[str, Any]:
        conv_id = db.create_conversation(name, provider, model)
        return {
            "id": conv_id,
            "name": name,
            "provider": provider,
            "model": model
        }

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        return db.list_conversations(limit=limit)

    def get_conversation(self, conv_id: int) -> Optional[dict[str, Any]]:
        return db.get_conversation(conv_id)

    def rename_conversation(self, conv_id: int, new_name: str) -> bool:
        return db.rename_conversation(conv_id, new_name)

    def delete_conversation(self, conv_id: int) -> bool:
        return db.delete_conversation(conv_id)

    def add_user_message(self, conv_id: int, content: str) -> int:
        return db.add_message(conv_id, "user", content)

    def add_assistant_message(self, conv_id: int, content: str, tokens: int = 0) -> int:
        return db.add_message(conv_id, "assistant", content, tokens=tokens)

    def get_history_for_api(self, conv_id: int, limit: int = 30) -> list[dict[str, str]]:
        messages = db.get_messages(conv_id, limit=limit)
        return [{"role": m["role"], "content": m["content"]} for m in messages]


conversation_manager = ConversationManager()
