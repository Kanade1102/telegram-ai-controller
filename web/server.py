"""Local-only management web interface running on 127.0.0.1:8765."""

import json
import logging
from aiohttp import web
from config import settings
from services.session_manager import session_manager
from services.model_manager import model_manager
from services.fallback_manager import fallback_manager
from services.database import db
from providers.api import list_api_providers
from providers.browser import BROWSER_PROVIDERS
from browser.manager import browser_manager

logger = logging.getLogger(__name__)

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Telegram AI Controller - Local Management</title>
  <style>
    :root { --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --accent: #38bdf8; --green: #22c55e; --red: #ef4444; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 2rem; }
    .container { max-width: 1000px; margin: 0 auto; }
    header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 1rem; margin-bottom: 2rem; }
    h1 { font-size: 1.5rem; margin: 0; display: flex; align-items: center; gap: 0.5rem; }
    .badge { background: #334155; padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.8rem; color: var(--accent); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
    .card { background: var(--card); border-radius: 8px; padding: 1.5rem; border: 1px solid #334155; }
    .card h2 { font-size: 1.1rem; margin-top: 0; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }
    ul { list-style: none; padding: 0; margin: 0; }
    li { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 0; border-bottom: 1px solid #334155; }
    li:last-child { border-bottom: none; }
    .status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 0.5rem; }
    .status-green { background: var(--green); }
    .status-red { background: var(--red); }
    .refresh-btn { background: #0284c7; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; }
    .refresh-btn:hover { background: #0369a1; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🟢 Telegram AI Controller <span class="badge">Local Only (127.0.0.1)</span></h1>
      <button class="refresh-btn" onclick="location.reload()">Refresh</button>
    </header>

    <div class="grid">
      <div class="card">
        <h2>Active Controller State</h2>
        <ul>
          <li><span>Mode</span> <strong>{mode}</strong></li>
          <li><span>Active Provider</span> <strong>{active_provider}</strong></li>
          <li><span>Selected Model</span> <code>{active_model}</code></li>
          <li><span>Fallback Chain</span> <strong>{fallback_chain}</strong></li>
          <li><span>Browser CDP</span> <span>{browser_status}</span></li>
        </ul>
      </div>

      <div class="card">
        <h2>Browser Sessions</h2>
        <ul>
          {browser_items}
        </ul>
      </div>

      <div class="card">
        <h2>API Providers</h2>
        <ul>
          {api_items}
        </ul>
      </div>

      <div class="card">
        <h2>Fallback Chains</h2>
        <ul>
          {fallback_items}
        </ul>
      </div>
    </div>
  </div>
</body>
</html>
"""


async def handle_index(request: web.Request) -> web.Response:
    state = session_manager.state
    active_m = model_manager.get_selected_model(state.active_provider)

    cdp_conn = await browser_manager.is_connected()
    browser_status = '<span class="status-dot status-green"></span>Connected' if cdp_conn else '<span class="status-dot status-red"></span>Disconnected'

    browser_items = ""
    for name, prov in BROWSER_PROVIDERS.items():
        is_active = (state.active_provider == name)
        active_tag = " (Active)" if is_active else ""
        browser_items += f"<li><span>{prov.friendly_name}{active_tag}</span> <span class='badge'>{name}</span></li>"

    api_items = ""
    for prov in list_api_providers():
        is_active = (state.active_provider == prov.name)
        active_tag = " (Active)" if is_active else ""
        selected_model = model_manager.get_selected_model(prov.name)
        api_items += f"<li><span>{prov.friendly_name}{active_tag}</span> <code>{selected_model}</code></li>"

    fallback_items = ""
    chains = fallback_manager.list_chains()
    for c_name, c_list in chains.items():
        chain_str = " → ".join(c_list)
        fallback_items += f"<li><strong>{c_name}</strong> <span>{chain_str}</span></li>"

    html = HTML_DASHBOARD.format(
        mode=state.active_mode.upper(),
        active_provider=state.active_provider,
        active_model=active_m or "None",
        fallback_chain=state.active_fallback_chain or "Off",
        browser_status=browser_status,
        browser_items=browser_items,
        api_items=api_items,
        fallback_items=fallback_items,
    )
    return web.Response(text=html, content_type="text/html")


async def handle_api_status(request: web.Request) -> web.Response:
    state = session_manager.state
    cdp_conn = await browser_manager.is_connected()
    return web.json_response({
        "status": "online",
        "mode": state.active_mode,
        "active_provider": state.active_provider,
        "active_browser_tab": state.active_browser_tab_id,
        "active_conversation_id": state.active_conversation_id,
        "fallback_chain": state.active_fallback_chain,
        "cdp_connected": cdp_conn,
        "last_status": state.last_status,
        "last_prompt_time": state.last_prompt_time,
    })


def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_api_status)
    return app


async def start_web_server() -> Optional[web.AppRunner]:
    if not settings.local_server_enabled:
        return None
    try:
        app = create_web_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, settings.local_server_host, settings.local_server_port)
        await site.start()
        logger.info(
            "Local management web interface started on http://%s:%s",
            settings.local_server_host, settings.local_server_port
        )
        return runner
    except Exception as e:
        logger.warning("Failed to start local web server on %s:%s: %s", settings.local_server_host, settings.local_server_port, e)
        return None
