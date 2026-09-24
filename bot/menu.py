"""Telegram bot command menu (BotFather-style list) registration.

The command list users see when typing "/" in Telegram is set via BotFather
"Edit Commands" OR programmatically via Telegram's setMyCommands API. Doing it
here keeps the menu in sync with the bot's actual handler set automatically.
"""

import logging
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError

from config import settings

logger = logging.getLogger(__name__)

COMMANDS = [
    # (command, description)
    ("start", "Bot info & status"),
    ("help", "Show available commands"),
    ("status", "Controller status"),
    ("sessions", "List AI browser tabs"),
    ("use", "Select browser tab"),
    ("provider", "Select AI provider"),
    ("providers", "List all backends"),
    ("mode", "Set mode: browser/api/auto"),
    ("api", "Switch to API mode"),
    ("web", "Switch to browser mode"),
    ("models", "List provider models"),
    ("model", "Select model"),
    ("effort", "Set reasoning effort"),
    ("progress", "Check AI progress"),
    ("shot", "Screenshot active tab/desktop"),
    ("last", "Latest AI response"),
    ("stop", "Stop generation"),
    ("watch", "Periodic progress"),
    ("unwatch", "Stop periodic progress"),
    ("conversations", "List API chats"),
    ("resume", "Resume saved chat by number"),
    ("newchat", "New API chat"),
    ("usechat", "Switch API chat"),
    ("renamechat", "Rename API chat"),
    ("deletechat", "Delete API chat"),
    ("fallback", "Fallback routing"),
    ("login", "Browser login help"),
    ("health", "Provider health check"),
    ("usage", "Token usage"),
]


async def register_commands(bot: Bot) -> bool:
    """Push the command menu to Telegram (overwrites BotFather menu)."""
    if not settings.telegram_bot_token:
        return False
    try:
        await bot.set_my_commands(COMMANDS)
        logger.info("Telegram command menu registered (%d commands).", len(COMMANDS))
        return True
    except TelegramError as e:
        logger.warning("Failed to register Telegram command menu: %s", e)
        return False
