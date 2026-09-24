"""Security verification module for Telegram updates.

Ensures DENY-BY-DEFAULT policy: Only user IDs explicitly present in
TELEGRAM_ALLOWED_USERS can execute any bot commands or receive data.
"""

import logging
from functools import wraps
from typing import Callable, Any
from telegram import Update
from telegram.ext import ContextTypes
from config import settings

logger = logging.getLogger(__name__)


def is_authorized(user_id: int) -> bool:
    """Check if Telegram user_id is authorized."""
    return settings.is_user_allowed(user_id)


def restricted(func: Callable) -> Callable:
    """Decorator for Telegram handlers to enforce authorization."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any) -> Any:
        if not update or not update.effective_user:
            logger.warning("Received update without effective user. Ignoring.")
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"

        if not is_authorized(user_id):
            logger.warning(
                "SECURITY ALERT: Unauthorized access attempt by user_id=%s, username=@%s",
                user_id, username
            )
            # Safe response: never reveal system info, never leak secrets
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Unauthorized. Access denied.\nYour Telegram User ID is: `{user_id}`\n"
                    "Add this ID to TELEGRAM_ALLOWED_USERS in your controller configuration.",
                    parse_mode="Markdown"
                )
            return

        return await func(update, context, *args, **kwargs)

    return wrapped
