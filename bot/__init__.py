"""Telegram bot setup and handler registration."""

import logging
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config import settings
from bot.handlers import (
    handle_start,
    handle_help,
    handle_status,
    handle_health,
    handle_usage,
    handle_providers,
    handle_mode,
    handle_mode_api,
    handle_mode_web,
    handle_provider,
    handle_login,
    handle_sessions,
    handle_use,
    handle_models,
    handle_model,
    handle_effort,
    handle_conversations,
    handle_resume,
    handle_newchat,
    handle_usechat,
    handle_renamechat,
    handle_deletechat,
    handle_fallback,
    handle_agent,
    handle_perm_callback,
    handle_prompt,
    handle_photo_prompt,
    handle_progress,
    handle_shot,
    handle_last,
    handle_stop,
    handle_watch,
    handle_unwatch,
)

logger = logging.getLogger(__name__)


def build_bot_app() -> Application:
    """Build and configure the Telegram bot application."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured! Please set it in .env or environment.")

    app = ApplicationBuilder().token(settings.telegram_bot_token).concurrent_updates(True).build()

    # Register handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("health", handle_health))
    app.add_handler(CommandHandler("usage", handle_usage))

    app.add_handler(CommandHandler("providers", handle_providers))
    app.add_handler(CommandHandler("mode", handle_mode))
    app.add_handler(CommandHandler("api", handle_mode_api))
    app.add_handler(CommandHandler("web", handle_mode_web))
    app.add_handler(CommandHandler("provider", handle_provider))
    app.add_handler(CommandHandler("login", handle_login))

    app.add_handler(CommandHandler("sessions", handle_sessions))
    app.add_handler(CommandHandler("use", handle_use))

    app.add_handler(CommandHandler("models", handle_models))
    app.add_handler(CommandHandler("model", handle_model))
    app.add_handler(CommandHandler("effort", handle_effort))

    app.add_handler(CommandHandler("conversations", handle_conversations))
    app.add_handler(CommandHandler("resume", handle_resume))
    app.add_handler(CommandHandler("newchat", handle_newchat))
    app.add_handler(CommandHandler("usechat", handle_usechat))
    app.add_handler(CommandHandler("renamechat", handle_renamechat))
    app.add_handler(CommandHandler("deletechat", handle_deletechat))

    app.add_handler(CommandHandler("fallback", handle_fallback))
    app.add_handler(CommandHandler("agent", handle_agent))

    # Claude permission relay: inline y/n buttons answer can_use_tool requests.
    app.add_handler(CallbackQueryHandler(handle_perm_callback, pattern=r"^perm:"))

    # Chat without /prompt: any plain text message is a prompt.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    # Photos with optional caption text: routed to providers with vision.
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_prompt))

    app.add_handler(CommandHandler("progress", handle_progress))
    app.add_handler(CommandHandler("shot", handle_shot))
    app.add_handler(CommandHandler("last", handle_last))
    app.add_handler(CommandHandler("stop", handle_stop))
    app.add_handler(CommandHandler("watch", handle_watch))
    app.add_handler(CommandHandler("unwatch", handle_unwatch))

    return app
