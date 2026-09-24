"""Telegram bot command handlers and message processing."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Any
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import settings
from bot.security import restricted
from services.session_manager import session_manager
from services.model_manager import model_manager
from services.conversation_manager import conversation_manager
from services.task_manager import task_manager, TaskStatus
from services.fallback_manager import fallback_manager
from services.progress import progress_service
from services.screenshot import screenshot_service
from services.database import db
from browser.manager import browser_manager
from browser.detector import ProgressState, get_provider_display_name
from providers import get_provider
from providers.browser import BROWSER_PROVIDERS, get_browser_provider_by_name
from providers.api import list_api_providers, get_api_provider, health_cache
from providers.api.base import APIError, AuthError, RateLimitError, ServerError

logger = logging.getLogger(__name__)

# Active background watch tasks: chat_id -> asyncio.Task
WATCH_TASKS: dict[int, asyncio.Task] = {}


def extract_prompt_text(full_text: str) -> str:
    """Extract prompt text after command preserving newlines and special characters."""
    if not full_text:
        return ""
    lines = full_text.split(None, 1)
    if len(lines) > 1:
        return lines[1]
    return ""


def truncate_response(text: str) -> str:
    """Keep Telegram messages under the 4096-char limit without cutting mid-word."""
    if not text:
        return text
    limit = settings.response_char_limit
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…[truncated]"


# ==============================================================================
# GENERAL COMMANDS
# ==============================================================================

@restricted
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "🤖 *Telegram AI Controller Online*\n\n"
        "Unified remote controller for your local browser AI sessions and direct API providers.\n\n"
        f"*Active Mode:* `{session_manager.state.active_mode.upper()}`\n"
        f"*Active Provider:* `{session_manager.state.active_provider}`\n\n"
        "Type /help to see all available commands."
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 *Telegram AI Controller — Command Guide*\n\n"
        "*General*\n"
        "• `/start` — Check bot connectivity\n"
        "• `/help` — Show this documentation\n"
        "• `/status` — View current bot & provider status\n"
        "• `/health` — Live health check of all providers\n"
        "• `/usage` — View token usage & stats\n\n"
        "*Provider & Mode*\n"
        "• `/providers` — List browser & API backends\n"
        "• `/mode [browser|api|auto]` — Switch execution mode\n"
        "• `/api` — Shortcut: switch to API mode\n"
        "• `/web` — Shortcut: switch to browser mode\n"
        "• `/provider <name>` — Select active AI provider\n"
        "• `/login <chatgpt|gemini>` — Open browser login tab\n\n"
        "*Models*\n"
        "• `/models [provider] [refresh]` — List models for provider\n"
        "• `/model <model-id|alias>` — Set model for active provider\n"
        "• `/effort [low|medium|high|off]` — Reasoning effort (AGY)\n\n"
        "*Prompts & Generation*\n"
        "• `/prompt <text>` (or `/promt`) — Send prompt to active backend\n"
        "• `/progress` — Check active activity & screenshot\n"
        "• `/last` — Show latest visible AI response\n"
        "• `/stop` — Stop current generation\n"
        "• `/watch [secs]` — Periodic progress updates (min 10s)\n"
        "• `/unwatch` — Stop periodic updates\n\n"
        "*Browser Sessions*\n"
        "• `/sessions` — List open AI browser tabs\n"
        "• `/use <id|name>` — Select active browser tab\n\n"
        "*API Conversations*\n"
        "• `/conversations` — List saved API threads\n"
        "• `/resume [number]` — List chat history numbered, resume by number\n"
        "• `/newchat <name>` — Create a new API conversation\n"
        "• `/usechat <id>` — Select conversation thread\n"
        "• `/renamechat <id> <name>` — Rename conversation\n"
        "• `/deletechat <id>` — Delete conversation\n\n"
        "*Routing & Fallback*\n"
        "• `/fallback <chain|off>` — Set active fallback chain"
    )
    await update.effective_message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = session_manager.state
    cdp_connected = await browser_manager.is_connected()
    browser_status_str = "Connected" if cdp_connected else "Disconnected"

    # Browser accounts: real per-site check when CDP is up, else ⚪ unknown
    browser_lines = []
    if cdp_connected:
        ai_tabs = await browser_manager.get_ai_sessions()
        tab_providers = {s["provider_key"] for s in ai_tabs}
        for b_key, b_prov in BROWSER_PROVIDERS.items():
            icon = "✅" if b_key in tab_providers else "🔴"
            browser_lines.append(f"{b_prov.friendly_name} {icon}")
    else:
        for b_key, b_prov in BROWSER_PROVIDERS.items():
            browser_lines.append(f"{b_prov.friendly_name} ⚪")
    browser_accs = "\n".join(browser_lines) or "No browser providers"

    # API providers: cached startup health (no live calls here; /health does live)
    api_lines = []
    for a_prov in list_api_providers():
        icon = "⚪"
        no_key = not getattr(a_prov, "api_key", "")
        local_url = "127.0.0.1" in getattr(a_prov, "base_url", "") or "localhost" in getattr(a_prov, "base_url", "")
        if no_key and not local_url and a_prov.name != "agy" and a_prov.name != "hermes":
            icon = "🔴"  # no key configured
        elif a_prov.name in health_cache and health_cache[a_prov.name][0]:
            icon = "✅"
        elif a_prov.name in health_cache:
            icon = "🔴"
        api_lines.append(f"{a_prov.friendly_name} {icon}")
    api_provs = "\n".join(api_lines) or "No API providers"

    # Active conversation name
    conv_name = "N/A"
    if state.active_conversation_id:
        conv_obj = conversation_manager.get_conversation(state.active_conversation_id)
        if conv_obj:
            conv_name = conv_obj.get("name", "N/A")

    active_task = task_manager.get_active_task()
    current_task_status = active_task.status.value if active_task else state.last_status

    msg = (
        "🟢 *Telegram AI Controller*\n\n"
        f"*Mode:*\n{state.active_mode.upper()}\n\n"
        f"*Backend:*\n{get_provider_display_name(state.active_provider)}\n\n"
        f"*Model:*\n`{model_manager.get_selected_model(state.active_provider) or 'default'}`\n\n"
        f"*Effort:*\n`{state.active_effort or 'default'}`\n\n"
        f"*Conversation:*\n{conv_name}\n\n"
        f"*Browser:*\n{browser_status_str}\n\n"
        f"*Browser Accounts:*\n{browser_accs}\n\n"
        f"*API Providers:*\n{api_provs}\n\n"
        f"*Current task:*\n{current_task_status}\n\n"
        f"*Last prompt:* {state.last_prompt_time or 'None'}\n"
        f"*Last screenshot:* {state.last_screenshot_time or 'None'}"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_msg = await update.effective_message.reply_text("🔎 Testing provider health...")

    lines = ["📊 *Provider Health*\n"]

    # Test API providers
    for prov in list_api_providers():
        try:
            h = await prov.health()
            success = h["status"] == "AVAILABLE"
            health_cache[prov.name] = (success, h.get("message", ""), h.get("latency_ms", 0.0))
            icon = "✅" if success else "🔴"
            latency = f"{h['latency_ms']:.0f} ms" if h["latency_ms"] > 0 else "N/A"
            lines.append(f"*{prov.friendly_name}*")
            lines.append(f"{icon} {h['status']} ({latency})\n")
        except Exception as e:
            health_cache[prov.name] = (False, str(e), 0.0)
            lines.append(f"*{prov.friendly_name}*\n🔴 Error: {e}\n")

    # Browser status
    cdp_conn = await browser_manager.is_connected()
    cdp_icon = "✅" if cdp_conn else "🔴"
    lines.append("*Browser CDP*")
    lines.append(f"{cdp_icon} {'Connected' if cdp_conn else 'Unavailable'}\n")

    await status_msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = session_manager.state
    conv_id = state.active_conversation_id
    stats = db.get_usage_summary(conversation_id=conv_id)

    header = f"Current conversation (#{conv_id})" if conv_id else "All API conversations"
    msg = (
        f"📊 *Usage Statistics — {header}*\n\n"
        f"*Provider:* {get_provider_display_name(state.active_provider)}\n"
        f"*Requests:* {stats['request_count']}\n"
        f"*Input tokens:* {stats['total_prompt_tokens']:,}\n"
        f"*Output tokens:* {stats['total_completion_tokens']:,}\n"
        f"*Total tokens:* {stats['total_tokens']:,}\n"
        f"*Reported cost:* ${stats['total_cost']:.4f}"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ==============================================================================
# PROVIDER, MODE & BROWSER LOGIN COMMANDS
# ==============================================================================

@restricted
async def handle_providers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = session_manager.state
    cdp_conn = await browser_manager.is_connected()

    browser_lines = []
    if cdp_conn:
        ai_tabs = await browser_manager.get_ai_sessions()
        tab_providers = {s["provider_key"] for s in ai_tabs}
        for k, p in BROWSER_PROVIDERS.items():
            icon = "🟢" if k in tab_providers else "🔴"
            browser_lines.append(f"{icon} {p.friendly_name} (`{k}`)")
    else:
        for k, p in BROWSER_PROVIDERS.items():
            browser_lines.append(f"⚪ {p.friendly_name} (`{k}`)")

    api_lines = []
    for p in list_api_providers():
        icon = "⚪"
        if p.name in health_cache:
            icon = "🟢" if health_cache[p.name][0] else "🔴"
        else:
            no_key = not getattr(p, "api_key", "")
            local_url = "127.0.0.1" in getattr(p, "base_url", "") or "localhost" in getattr(p, "base_url", "")
            if no_key and not local_url and p.name != "agy" and p.name != "hermes":
                icon = "🔴"
        api_lines.append(f"{icon} {p.friendly_name} (`{p.name}`)")

    current_m = model_manager.get_selected_model(state.active_provider)

    msg = (
        "🌐 *Available Backends*\n\n"
        "*Browser:*\n" + "\n".join(browser_lines) + "\n\n"
        "*API:*\n" + "\n".join(api_lines) + "\n\n"
        f"*Selected:*\n{get_provider_display_name(state.active_provider)} (`{state.active_provider}`)\n\n"
        f"*Model:*\n`{current_m or 'default'}`"
    )
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text(
            f"Current mode: `{session_manager.state.active_mode}`\n\nUsage: `/mode [browser|api|auto]`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    new_mode = args[0].lower().strip()
    if new_mode not in ("browser", "api", "auto"):
        await update.effective_message.reply_text("Invalid mode. Choose `browser`, `api`, or `auto`.", parse_mode=ParseMode.MARKDOWN)
        return

    session_manager.set_mode(new_mode)
    await update.effective_message.reply_text(f"✅ Mode changed to: `{new_mode.upper()}`", parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_mode_api(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: switch to API mode (same as /mode api)."""
    session_manager.set_mode("api")
    await update.effective_message.reply_text(
        "✅ Mode set to *API*. `/prompt` will use direct API providers.",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_mode_web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: switch to browser mode (same as /mode browser)."""
    session_manager.set_mode("browser")
    await update.effective_message.reply_text(
        "✅ Mode set to *BROWSER*. `/prompt` will drive your browser AI tabs.",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_provider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        cur_p = session_manager.state.active_provider
        await update.effective_message.reply_text(
            f"Active provider: `{cur_p}` ({get_provider_display_name(cur_p)})\n\nUsage: `/provider <name>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    target = args[0].lower().strip()
    prov = get_provider(target)
    if not prov:
        await update.effective_message.reply_text(
            f"❌ Unknown provider: `{target}`. Use `/providers` to see available backends.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    session_manager.set_provider(prov.name)
    current_model = model_manager.get_selected_model(prov.name)

    await update.effective_message.reply_text(
        f"✅ Active provider switched to: *{prov.friendly_name}*\n"
        f"Mode: `{session_manager.state.active_mode.upper()}`\n"
        f"Model: `{current_model or 'default'}`",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: `/login <gemini|chatgpt>`", parse_mode=ParseMode.MARKDOWN)
        return

    service = args[0].lower().strip()
    target_url = ""
    prov_name = ""
    if "gemini" in service:
        target_url = "https://gemini.google.com/"
        prov_name = "gemini_web"
    elif "chatgpt" in service:
        target_url = "https://chatgpt.com/"
        prov_name = "chatgpt_web"
    else:
        await update.effective_message.reply_text("Supported login services: `gemini`, `chatgpt`", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.effective_message.reply_text(f"🌐 Inspecting browser for {service.title()} tab...")

    if not await browser_manager.is_connected():
        conn = await browser_manager.connect()
        if not conn:
            await status_msg.edit_text("❌ Cannot connect to browser CDP. Ensure Chromium is running with remote debugging port 9222.")
            return

    page = await browser_manager.open_or_focus_tab(target_url)
    if not page:
        await status_msg.edit_text("❌ Failed to open or find tab in Chromium.")
        return

    prov = get_browser_provider_by_name(prov_name)
    if not prov:
        await status_msg.edit_text(f"❌ Provider adapter for {prov_name} not found.")
        return

    is_logged_in = await prov.check_login_status(page)
    if is_logged_in:
        session_manager.set_provider(prov_name)
        await status_msg.edit_text(
            f"✅ *{prov.friendly_name}* is already logged in and ready!\n"
            f"Registered as active session: `{prov_name}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await status_msg.edit_text(
            f"🔑 Opened {target_url} in your Chromium browser.\n\n"
            "Please complete your authentication manually in the browser.\n"
            "The bot will not request, access, or touch your credentials.\n\n"
            "After logging in, run `/login " + service + "` again to confirm."
        )


# ==============================================================================
# BROWSER SESSION COMMANDS
# ==============================================================================

@restricted
async def handle_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await browser_manager.is_connected():
        await browser_manager.connect()

    sessions = await browser_manager.get_ai_sessions()
    if not sessions:
        await update.effective_message.reply_text(
            "⚠️ No compatible AI browser tabs found.\n"
            "Make sure Chromium is running with `--remote-debugging-port=9222` and has an AI website open (ChatGPT, Gemini, Claude, or DeepSeek)."
        )
        return

    lines = ["🖥️ *Active Browser AI Sessions*\n"]
    for s in sessions:
        active_tag = " [ACTIVE]" if s["active"] else ""
        lines.append(f"{s['index']}. *{s['provider_name']}*{active_tag}\n   \"{s['title']}\"\n   {s['url']}")

    lines.append("\nUse `/use <index|name>` to switch to a session.")
    await update.effective_message.reply_text("\n\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: `/use <1|chatgpt|gemini>`")
        return

    target = args[0]
    session = await browser_manager.select_session(target)
    if not session:
        await update.effective_message.reply_text(f"❌ Session matching '{target}' not found. Use `/sessions` to list tabs.")
        return

    session_manager.set_provider(session["provider_key"])
    session_manager.set_browser_tab(session["id"])

    await update.effective_message.reply_text(
        f"✅ Switched active browser session to:\n\n"
        f"*{session['provider_name']}*\n"
        f"\"{session['title']}\"",
        parse_mode=ParseMode.MARKDOWN
    )


# ==============================================================================
# MODELS COMMANDS
# ==============================================================================

@restricted
async def handle_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    target_prov = session_manager.state.active_provider
    refresh = False

    if args:
        if args[-1].lower() == "refresh":
            refresh = True
            if len(args) > 1:
                target_prov = args[0].lower()
        else:
            target_prov = args[0].lower()

    prov = get_api_provider(target_prov)
    if not prov:
        await update.effective_message.reply_text(
            f"❌ `{target_prov}` is not an API provider. Use `/providers` to view API backends.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    status_msg = await update.effective_message.reply_text(f"🔎 Fetching models for {prov.friendly_name}...")
    try:
        models = await model_manager.list_models_for_provider(prov.name, refresh=refresh)
        if not models:
            await status_msg.edit_text(f"No models found for {prov.friendly_name}.")
            return

        current_m = model_manager.get_selected_model(prov.name)
        display_models = models[:40]  # Limit to 40 for Telegram message size
        models_text = "\n".join([f"• `{m}`" + (" *(selected)*" if m == current_m else "") for m in display_models])
        if len(models) > 40:
            models_text += f"\n\n_...and {len(models) - 40} more models._"

        msg = (
            f"📋 *Models for {prov.friendly_name}* ({len(models)} available)\n\n"
            f"{models_text}\n\n"
            f"Select with: `/model <model-id>`"
        )
        await status_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error fetching models: {e}")


@restricted
async def handle_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        cur_p = session_manager.state.active_provider
        cur_m = model_manager.get_selected_model(cur_p)
        await update.effective_message.reply_text(
            f"Active provider: `{cur_p}`\nSelected model: `{cur_m or 'default'}`\n\nUsage: `/model <model-id|alias>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    target = args[0].strip()

    # Syntax: /model <provider>/<model-id>  e.g. /model openrouter/meta-llama/...
    if "/" in target and not target.lower().startswith(("models/", "gpt-", "claude-", "gemini-", "o1", "o3", "o4", "deepseek-", "llama")):
        prov_part, _, model_part = target.partition("/")
        prov_obj = get_provider(prov_part)
        if prov_obj and model_part:
            session_manager.set_provider(prov_obj.name)
            model_manager.set_selected_model(prov_obj.name, model_part)
            await update.effective_message.reply_text(
                f"✅ Switched to *{prov_obj.friendly_name}*\nModel set to:\n`{model_part}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    # Check alias
    alias_match = model_manager.resolve_alias(target)
    if alias_match:
        prov_key, model_key = alias_match
        session_manager.set_provider(prov_key)
        model_manager.set_selected_model(prov_key, model_key)
        await update.effective_message.reply_text(
            f"✅ Resolved alias `{target}`:\n"
            f"Provider: *{get_provider_display_name(prov_key)}*\n"
            f"Model: `{model_key}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    active_p = session_manager.state.active_provider
    model_manager.set_selected_model(active_p, target)
    await update.effective_message.reply_text(
        f"✅ Selected model for *{get_provider_display_name(active_p)}* set to:\n`{target}`",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_effort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View or set reasoning effort (low|medium|high). Passed to providers that
    support it (agy --effort); silently ignored by providers that don't."""
    args = context.args
    cur = session_manager.state.active_effort

    if not args:
        await update.effective_message.reply_text(
            f"Current effort: `{cur or 'default (model)'}`\n\n"
            "Usage: `/effort [low|medium|high|off]`\n"
            "`off` resets to the model default.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    val = args[0].lower().strip()
    if val in ("off", "none", "default"):
        session_manager.set_effort(None)
        await update.effective_message.reply_text("✅ Effort reset to model default.")
        return
    if val not in ("low", "medium", "high"):
        await update.effective_message.reply_text("❌ Effort must be `low`, `medium`, `high`, or `off`.")
        return

    session_manager.set_effort(val)
    await update.effective_message.reply_text(
        f"✅ Reasoning effort set to `{val}`.\n"
        "Applies to the next prompt. Supported by: AGY (agy --effort).",
        parse_mode=ParseMode.MARKDOWN
    )


# ==============================================================================
# CONVERSATION COMMANDS (API)
# ==============================================================================

@restricted
async def handle_conversations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    convs = conversation_manager.list_conversations()
    if not convs:
        await update.effective_message.reply_text("No API conversations yet. Create one with `/newchat <name>`.")
        return

    active_id = session_manager.state.active_conversation_id
    lines = ["💬 *API Conversations*\n"]
    for c in convs:
        tag = " *(active)*" if c["id"] == active_id else ""
        lines.append(f"• ID `{c['id']}`: *{c['name']}*{tag}\n  Backend: {c['provider']} | Model: `{c['model']}`")

    lines.append("\nSwitch with: `/usechat <id>`")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume a saved conversation. Bare /resume lists history numbered from 1;
    /resume <number> switches to that conversation (number = position in list)."""
    convs = conversation_manager.list_conversations()
    if not convs:
        await update.effective_message.reply_text(
            "No saved conversations yet. Start one with `/newchat <name>`."
        )
        return

    # 1. No argument: show numbered history
    if not context.args:
        active_id = session_manager.state.active_conversation_id
        lines = ["💬 *Chat History*\n"]
        for i, c in enumerate(convs, 1):
            tag = " *(active)*" if c["id"] == active_id else ""
            lines.append(
                f"{i}: *{c['name']}*{tag}\n"
                f"   Provider: {c['provider']} | Model: `{c['model']}`"
            )
        lines.append("\nResume with: `/resume <number>`")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    # 2. Argument: switch by 1-based position
    if not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: `/resume` to list, `/resume <number>` to resume.")
        return

    n = int(context.args[0])
    if n < 1 or n > len(convs):
        await update.effective_message.reply_text(
            f"❌ Number {n} not in history (1-{len(convs)}). Use `/resume` to see the list."
        )
        return

    conv = convs[n - 1]
    session_manager.set_conversation(conv["id"])
    session_manager.set_provider(conv["provider"])
    model_manager.set_selected_model(conv["provider"], conv["model"])

    await update.effective_message.reply_text(
        f"✅ Resumed conversation:\n\n"
        f"#{conv['id']}: *{conv['name']}*\n"
        f"Provider: {conv['provider']}\n"
        f"Model: `{conv['model']}`",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_newchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = " ".join(context.args).strip() if context.args else f"Chat {datetime.now().strftime('%b %d %H:%M')}"
    prov = session_manager.state.active_provider
    if "_web" in prov:
        prov = "openai"  # Default API provider for newchat
    model = model_manager.get_selected_model(prov)

    conv = conversation_manager.create_conversation(name, prov, model)
    session_manager.set_conversation(conv["id"])

    await update.effective_message.reply_text(
        f"✅ Created conversation:\n\n"
        f"*ID:* `{conv['id']}`\n"
        f"*Name:* {conv['name']}\n"
        f"*Provider:* {get_provider_display_name(prov)}\n"
        f"*Model:* `{model}`",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_usechat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: `/usechat <id>`")
        return

    conv_id = int(context.args[0])
    conv = conversation_manager.get_conversation(conv_id)
    if not conv:
        await update.effective_message.reply_text(f"❌ Conversation #{conv_id} not found.")
        return

    session_manager.set_conversation(conv_id)
    session_manager.set_provider(conv["provider"])
    model_manager.set_selected_model(conv["provider"], conv["model"])

    await update.effective_message.reply_text(
        f"✅ Active conversation set to #{conv_id}:\n*{conv['name']}*\n"
        f"Provider: {conv['provider']}\n"
        f"Model: `{conv['model']}`",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def handle_renamechat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: `/renamechat <id> <new name>`")
        return

    conv_id = int(context.args[0])
    new_name = " ".join(context.args[1:]).strip()
    if conversation_manager.rename_conversation(conv_id, new_name):
        await update.effective_message.reply_text(f"✅ Conversation #{conv_id} renamed to: *{new_name}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(f"❌ Could not rename conversation #{conv_id}.")


@restricted
async def handle_deletechat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: `/deletechat <id>`")
        return

    conv_id = int(context.args[0])
    if conversation_manager.delete_conversation(conv_id):
        if session_manager.state.active_conversation_id == conv_id:
            session_manager.set_conversation(None)
        await update.effective_message.reply_text(f"✅ Conversation #{conv_id} deleted.")
    else:
        await update.effective_message.reply_text(f"❌ Conversation #{conv_id} not found.")


# ==============================================================================
# ROUTING & FALLBACK
# ==============================================================================

@restricted
async def handle_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        cur_fb = fallback_manager.get_active_chain_name() or "off"
        chains = fallback_manager.list_chains()
        chains_desc = "\n".join([f"• `{k}`: {' → '.join(v)}" for k, v in chains.items()])
        await update.effective_message.reply_text(
            f"Current fallback chain: `{cur_fb}`\n\n"
            f"Available chains:\n{chains_desc}\n\n"
            "Set with `/fallback <chain>` or `/fallback off`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    chain_name = args[0].lower().strip()
    if fallback_manager.set_active_chain(chain_name):
        await update.effective_message.reply_text(f"✅ Fallback chain set to: `{chain_name}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(f"❌ Unknown fallback chain: `{chain_name}`", parse_mode=ParseMode.MARKDOWN)


# ==============================================================================
# PROMPT EXECUTION & STREAMING
# ==============================================================================

@restricted
async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw_text = update.effective_message.text or ""
    prompt_text = extract_prompt_text(raw_text)

    if not prompt_text:
        await update.effective_message.reply_text("Please provide a prompt after the command. Example:\n`/prompt hello`", parse_mode=ParseMode.MARKDOWN)
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    session_manager.record_prompt(prompt_text, now_iso)
    state = session_manager.state

    # 1. BROWSER MODE EXECUTION
    if state.active_mode == "browser" or "_web" in state.active_provider:
        await execute_browser_prompt(update, prompt_text)
        return

    # 2. API OR AUTO MODE EXECUTION
    await execute_api_prompt(update, prompt_text)


async def execute_browser_prompt(update: Update, prompt_text: str) -> None:
    """Execute prompt inside the active browser AI tab."""
    if not await browser_manager.is_connected():
        await browser_manager.connect()

    session = await browser_manager.get_active_session()
    if not session:
        await update.effective_message.reply_text(
            "⚠️ No active browser AI tab found.\n"
            "Open ChatGPT, Gemini, Claude, or DeepSeek in Chromium (port 9222) and run `/sessions`."
        )
        return

    page = session["page"]
    provider = session["provider"]
    p_name = session["provider_name"]
    session_title = session["title"]

    status_msg = await update.effective_message.reply_text(f"📤 Sending prompt to {p_name}...")

    # Create task object
    task = task_manager.create_task(
        backend="browser",
        provider=provider.name,
        mode="browser",
        prompt=prompt_text
    )

    success = await provider.send_prompt(page, prompt_text)
    if success:
        task.status = TaskStatus.GENERATING
        await status_msg.edit_text(
            f"✅ Prompt sent successfully.\n\n"
            f"*Provider:* {p_name}\n"
            f"*Session:* {session_title}",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        task_manager.fail_task(task.id, "Failed to inject prompt into input element")
        await status_msg.edit_text(
            f"❌ Failed to send prompt to {p_name}.\n"
            "Input field or send button could not be reached. Try `/progress` to view the page state."
        )


async def execute_api_prompt(update: Update, prompt_text: str) -> None:
    """Execute prompt through direct API with streaming and throttled updates."""
    state = session_manager.state
    target_providers = [state.active_provider]

    # If fallback is enabled or auto mode, build candidate chain
    chain_name = fallback_manager.get_active_chain_name()
    if chain_name and state.active_mode in ("auto", "api"):
        candidates = fallback_manager.get_chain_providers(chain_name)
        if state.active_provider in candidates:
            # Reorder starting from active provider
            idx = candidates.index(state.active_provider)
            target_providers = candidates[idx:] + candidates[:idx]
        else:
            target_providers = [state.active_provider] + candidates

    # Ensure conversation exists
    conv_id = state.active_conversation_id
    if not conv_id:
        new_conv = conversation_manager.create_conversation("New Chat", state.active_provider, model_manager.get_selected_model(state.active_provider))
        conv_id = new_conv["id"]
        session_manager.set_conversation(conv_id)

    # Save user message
    conversation_manager.add_user_message(conv_id, prompt_text)
    history = conversation_manager.get_history_for_api(conv_id)

    initial_msg: Optional[Any] = None
    last_error: Optional[Exception] = None

    for prov_name in target_providers:
        # Skip browser providers in API mode
        if "_web" in prov_name:
            continue

        api_prov = get_api_provider(prov_name)
        if not api_prov:
            continue

        model_name = model_manager.get_selected_model(prov_name)
        display_name = api_prov.friendly_name

        try:
            if not initial_msg:
                initial_msg = await update.effective_message.reply_text(
                    f"🤖 *{display_name}*\n"
                    f"Model: `{model_name}`\n"
                    f"Status: Generating...",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await initial_msg.edit_text(
                    f"🔄 Switched to *{display_name}*\n"
                    f"Model: `{model_name}`\n"
                    f"Status: Generating...",
                    parse_mode=ParseMode.MARKDOWN
                )

            task = task_manager.create_task(
                backend="api",
                provider=prov_name,
                mode=state.active_mode,
                prompt=prompt_text,
                model=model_name,
                conversation_id=conv_id
            )

            # Stream response
            collected_text = ""
            last_edit_time = time.time()
            edit_interval = settings.telegram_stream_update_interval
            current_telegram_msg = initial_msg
            cancelled = False

            send_opts: dict[str, Any] = {}
            if state.active_effort:
                send_opts["effort"] = state.active_effort
            async for chunk in api_prov.send_message(history, model=model_name, stream=True, **send_opts):
                if task.cancel_requested:
                    cancelled = True
                    break

                collected_text += chunk
                task_manager.update_task_output(task.id, chunk)

                now = time.time()
                if (now - last_edit_time) >= edit_interval and collected_text.strip():
                    last_edit_time = now
                    # Handle message length limits (Telegram max 4096)
                    if len(collected_text) > 3900:
                        # Finalize current message and create continuation message
                        try:
                            await current_telegram_msg.edit_text(collected_text[:3900])
                        except Exception:
                            pass
                        collected_text = collected_text[3900:]
                        current_telegram_msg = await update.effective_message.reply_text(collected_text)
                    else:
                        try:
                            await current_telegram_msg.edit_text(collected_text)
                        except Exception:
                            pass

            # Final edit with complete text
            if collected_text.strip():
                try:
                    await current_telegram_msg.edit_text(collected_text)
                except Exception:
                    pass

            if cancelled:
                # User pressed /stop mid-stream: keep partial text, don't mark complete
                task_manager.complete_task(task.id, final_output=collected_text)
                if collected_text.strip():
                    conversation_manager.add_assistant_message(conv_id, collected_text + "\n[stopped]")
                try:
                    await update.effective_message.reply_text("🛑 Generation stopped.")
                except Exception:
                    pass
                return

            # Record usage & message
            usage = await api_prov.get_usage()
            conversation_manager.add_assistant_message(conv_id, collected_text, tokens=usage.get("completion_tokens", 0))
            db.record_usage(
                conversation_id=conv_id,
                provider=prov_name,
                model=model_name,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                cost=usage.get("cost", 0.0)
            )
            task_manager.complete_task(task.id, final_output=collected_text, usage=usage)
            session_manager.record_response(collected_text, status="IDLE")

            # Successfully completed with this provider
            return

        except (AuthError, RateLimitError, ServerError, APIError) as e:
            logger.warning("Provider %s failed: %s. Attempting fallback.", prov_name, e)
            last_error = e
            if initial_msg:
                try:
                    await initial_msg.edit_text(
                        f"⚠️ *{display_name} unavailable*\n\n"
                        f"Reason:\n`{e}`\n\n"
                        "Trying next fallback provider...",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass
            continue
        except Exception as e:
            logger.error("Unexpected error with provider %s: %s", prov_name, e)
            last_error = e
            continue

    # If all providers failed
    err_desc = str(last_error) if last_error else "All configured providers were unavailable."
    if initial_msg:
        await initial_msg.edit_text(f"❌ Request failed across all providers:\n\n`{err_desc}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text(f"❌ Request failed:\n\n`{err_desc}`", parse_mode=ParseMode.MARKDOWN)


# ==============================================================================
# PROGRESS, LAST, STOP & WATCH COMMANDS
# ==============================================================================

@restricted
async def handle_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_msg = await update.effective_message.reply_text("🔎 Checking current AI session...")

    info = await progress_service.get_progress()
    text = info.get("text", "No progress info.")
    shot_path = info.get("screenshot_path")

    # API mode never returns a browser screenshot. Capture the desktop here so
    # /progress always answers with a picture (as the menu description says).
    if not shot_path and session_manager.state.active_mode == "api":
        try:
            shot_path = await screenshot_service.capture(page=None, force_mode="desktop")
        except Exception as e:
            logger.warning("Desktop screenshot for API progress failed: %s", e)

    # If browser screenshot captured, send photo with caption or photo followed by text
    if shot_path:
        session_manager.record_screenshot(datetime.now(timezone.utc).isoformat())
        try:
            # Plain caption: MARKDOWN parse failures must never cost the screenshot.
            with open(shot_path, "rb") as photo:
                await update.effective_message.reply_photo(photo=photo, caption=text)
            await status_msg.delete()
            return
        except Exception as e:
            logger.warning("Failed to send screenshot photo: %s", e)

    # API or fallback text
    await status_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def handle_shot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit screenshot command. Prefers the active browser tab (private,
    browser-native); falls back to whole-desktop capture via grim/Wayland tools."""
    status_msg = await update.effective_message.reply_text("📸 Taking screenshot...")

    # 1. Browser tab (browser-native, privacy-preserving)
    shot_path = None
    try:
        session = await browser_manager.get_active_session()
        if session:
            shot_path = await screenshot_service.capture(page=session["page"], force_mode="browser")
            if shot_path:
                provider_name = session.get("provider_name", "browser")
                caption = f"📸 Screenshot of active AI tab ({provider_name})"
    except Exception as e:
        logger.warning("Browser-tab screenshot failed: %s; falling back to desktop.", e)

    # 2. Desktop fallback (grim on Wayland/Hyprland)
    if not shot_path:
        shot_path = await screenshot_service.capture(page=None, force_mode="desktop")
        if not shot_path:
            await status_msg.edit_text(
                "❌ Screenshot failed: no active browser tab and no desktop capture tool "
                "(grim/scrot/gnome-screenshot) available."
            )
            return
        caption = "📸 Screenshot (full desktop — no active browser tab found)"

    session_manager.record_screenshot(datetime.now(timezone.utc).isoformat())
    try:
        with open(shot_path, "rb") as photo:
            await update.effective_message.reply_photo(photo=photo, caption=caption)
        await status_msg.delete()
    except Exception as e:
        logger.error("Failed to send screenshot %s: %s", shot_path, e)
        await status_msg.edit_text("❌ Screenshot captured but Telegram upload failed. Try again.")


@restricted
async def handle_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = session_manager.state

    # 1. API Mode: fetch last message from active conversation
    if state.active_mode == "api":
        if state.active_conversation_id:
            history = conversation_manager.get_history_for_api(state.active_conversation_id, limit=5)
            for m in reversed(history):
                if m["role"] == "assistant":
                    await update.effective_message.reply_text(
                        f"💬 *Latest AI Response:*\n\n{truncate_response(m['content'])}"
                    )
                    return
        await update.effective_message.reply_text("No responses found in current conversation.")
        return

    # 2. Browser Mode: inspect DOM
    session = await browser_manager.get_active_session()
    if not session:
        await update.effective_message.reply_text("⚠️ No active browser AI tab found.")
        return

    provider = session["provider"]
    page = session["page"]
    last_text = await provider.get_last_response(page)

    if last_text:
        await update.effective_message.reply_text(
            f"💬 *Latest visible response from {session['provider_name']}:*\n\n{truncate_response(last_text)}"
        )
    else:
        await update.effective_message.reply_text(f"No visible response text found on {session['provider_name']} page.")


@restricted
async def handle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = session_manager.state

    # 1. Cancel API streaming task if running
    if task_manager.cancel_active_task():
        await update.effective_message.reply_text("🛑 Cancelled active API generation task.")
        return

    # 2. Browser stop button
    session = await browser_manager.get_active_session()
    if not session:
        await update.effective_message.reply_text("⚠️ No active browser session or generation to stop.")
        return

    provider = session["provider"]
    page = session["page"]
    stopped = await provider.stop_generating(page)
    if stopped:
        await update.effective_message.reply_text(f"🛑 Generation stopped on {session['provider_name']}.")
    else:
        await update.effective_message.reply_text(f"⚠️ No active 'Stop generating' button was found on {session['provider_name']}.")


@restricted
async def handle_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    interval = 30
    if args and args[0].isdigit():
        interval = max(10, int(args[0]))  # Minimum 10 seconds to avoid Telegram spam

    if chat_id in WATCH_TASKS and not WATCH_TASKS[chat_id].done():
        WATCH_TASKS[chat_id].cancel()

    async def watch_loop():
        try:
            await update.effective_message.reply_text(
                f"⏱️ Auto-watch enabled. Progress updates will be sent every {interval}s while AI is active.\n"
                "Use `/unwatch` to disable."
            )
            while True:
                await asyncio.sleep(interval)
                info = await progress_service.get_progress()
                status = info.get("status", "UNKNOWN")
                # Send update if GENERATING
                if status == ProgressState.GENERATING.value:
                    shot_path = info.get("screenshot_path")
                    text = info.get("text", "")
                    if shot_path:
                        with open(shot_path, "rb") as photo:
                            await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=text, parse_mode=ParseMode.MARKDOWN)
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Watch loop error: %s", e)

    WATCH_TASKS[chat_id] = asyncio.create_task(watch_loop())


@restricted
async def handle_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in WATCH_TASKS and not WATCH_TASKS[chat_id].done():
        WATCH_TASKS[chat_id].cancel()
        del WATCH_TASKS[chat_id]
        await update.effective_message.reply_text("🛑 Auto-watch disabled.")
    else:
        await update.effective_message.reply_text("Auto-watch is not currently active.")
