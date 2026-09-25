"""Main entry point for Telegram AI Controller."""

import asyncio
import logging
import signal
import sys
from typing import Optional
from config import settings
from services.credential_manager import mask_secret
from browser.manager import browser_manager
from web.server import start_web_server
from bot import build_bot_app
from providers.api import list_api_providers, health_cache

# Configure structured logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, settings.log_level, logging.INFO),
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("telegram-ai-controller")


async def run_self_test() -> None:
    """Validate configuration and perform startup checks without costly generations."""
    logger.info("Running provider self-test...")

    # Telegram security check
    if not settings.telegram_allowed_users:
        logger.warning(
            "SECURITY WARNING: TELEGRAM_ALLOWED_USERS is empty! Deny-by-default is ACTIVE. "
            "No Telegram user will be permitted until you configure user IDs in .env."
        )
    else:
        logger.info(
            "Telegram access control configured for %d authorized user(s).",
            len(settings.telegram_allowed_users)
        )

    # Browser CDP check
    logger.info("Checking Browser CDP endpoint at %s...", settings.browser_cdp_url)
    connected = await browser_manager.connect()
    if connected:
        logger.info("Browser CDP connection established.")
    else:
        logger.info(
            "Browser CDP is not currently running. Browser automation will activate automatically "
            "when Chromium is launched with --remote-debugging-port=9222."
        )

    # API Providers check
    for prov in list_api_providers():
        try:
            h = await prov.health()
            success = h["status"] == "AVAILABLE"
            msg = h.get("message", h["status"])
            latency = h.get("latency_ms", 0.0)
            health_cache[prov.name] = (success, msg, latency)
            status = "AVAILABLE" if success else "UNAVAILABLE"
            logger.info("Provider [%s]: %s (latency: %.0fms, info: %s)", prov.name, status, latency, msg)
        except Exception as e:
            health_cache[prov.name] = (False, str(e), 0.0)
            logger.info("Provider [%s]: UNAVAILABLE (%s)", prov.name, e)


async def main_async() -> None:
    logger.info("Starting Telegram AI Controller...")
    logger.info("Configuration: default_mode=%s, default_provider=%s", settings.default_mode, settings.default_provider)

    # 1. Startup self-tests
    await run_self_test()

    # 2. Start local management web UI
    web_runner = await start_web_server()

    # 3. Build Telegram bot application
    bot_app = build_bot_app()

    # Hermes REPL approval bridge: hermes plugin POSTs flagged-command
    # requests to /api/approval; the bot posts y/n buttons to Telegram.
    from services.hermes_approval_bridge import hermes_bridge

    async def post_hermes_approval(payload: dict) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        rid = payload["rid"]
        cmd = str(payload.get("command") or "")[:500]
        desc = str(payload.get("description") or "")[:300]
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Allow", callback_data=f"hperm:{rid}:y"),
            InlineKeyboardButton("⛔ Deny", callback_data=f"hperm:{rid}:n"),
        ]])
        for user_id in settings.telegram_allowed_users:
            try:
                await bot_app.bot.send_message(
                    user_id,
                    "🔐 *Hermes wants to run a flagged command*\n\n"
                    f"```\n{cmd}\n```\n_{desc}_\n\nAllow?",
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.warning("Failed to post hermes approval to %s: %s", user_id, e)

    hermes_bridge.set_poster(post_hermes_approval)

    # Graceful shutdown handler
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def handle_signal():
        logger.info("Shutdown signal received. Cleaning up...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        while not stop_event.is_set():
            try:
                if not bot_app.running:
                    logger.info("Connecting to Telegram...")
                    await bot_app.initialize()
                    await bot_app.start()
                    from bot.menu import register_commands
                    await register_commands(bot_app.bot)
                    await bot_app.updater.start_polling(
                        drop_pending_updates=True,
                        poll_interval=0.3,  # long-poll re-arm: don't idle 10s between updates
                        timeout=8,  # server long-poll timeout (shorter = snappier delivery)
                        allowed_updates=["message", "callback_query"],
                    )
                    logger.info("Telegram Bot started and polling for authorized commands.")

                await stop_event.wait()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if stop_event.is_set():
                    break
                logger.warning("Telegram connection error: %s. Retrying in 10s...", e)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    pass

    finally:
        # Suppress benign playwright driver-pipe warnings during teardown
        loop = asyncio.get_running_loop()

        def _quiet_handler(_loop, ctx):
            logger.debug("Async loop exception during shutdown: %s", ctx.get("message"))

        loop.set_exception_handler(_quiet_handler)
        logger.info("Stopping bot...")
        try:
            if bot_app.updater and bot_app.updater.running:
                await bot_app.updater.stop()
        except Exception:
            pass
        try:
            if bot_app.running:
                await bot_app.stop()
        except Exception:
            pass
        try:
            await bot_app.shutdown()
        except Exception:
            pass

        if web_runner:
            logger.info("Stopping local web server...")
            try:
                await web_runner.cleanup()
            except Exception:
                pass

        logger.info("Disconnecting browser manager...")
        await browser_manager.disconnect()
        logger.info("Shutdown complete.")


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
