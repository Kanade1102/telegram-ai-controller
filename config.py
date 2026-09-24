"""Central application configuration loader and validator."""

import os
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any
from services.credential_manager import credentials, mask_secret

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"


@dataclass
class Settings:
    # Telegram Security
    telegram_bot_token: str = ""
    telegram_allowed_users: set[int] = field(default_factory=set)

    # Browser CDP
    browser_cdp_url: str = "http://127.0.0.1:9222"

    # Modes & Providers
    default_mode: str = "browser"  # "browser", "api", "auto"
    default_provider: str = "chatgpt_web"

    # Screenshots
    # browser/window/desktop as before, plus "off" disables screenshots entirely
    screenshot_mode: str = "browser"
    screenshot_dir: Path = SCREENSHOTS_DIR
    # max visible-response chars sent via Telegram (0 = unlimited)
    response_char_limit: int = 3900

    # Streaming and Cache
    telegram_stream_update_interval: float = 1.5
    model_cache_seconds: int = 1800

    # Local Management UI
    local_server_enabled: bool = True
    local_server_host: str = "127.0.0.1"
    local_server_port: int = 8765

    # Google Antigravity CLI (agy)
    agy_cli_path: str = "agy"
    # Low-effort flash = fast first token; medium/high are thinking models (slow).
    agy_default_model: str = "gemini-3.8-flash-low"
    # Reasoning effort: low|medium|high; empty = model default
    agy_effort: str = ""

    # Hermes Agent local CLI
    hermes_cli_path: str = "hermes"
    # Empty or "idk" = use whatever Hermes is configured with (config.yaml)
    hermes_default_model: str = ""
    # Reasoning effort: none|minimal|low|medium|high|xhigh|max|ultra; empty = Hermes default
    hermes_effort: str = ""

    # Logging
    log_level: str = "INFO"

    # API Providers Keys & Defaults
    openai_api_key: Optional[str] = None
    openai_default_model: str = "gpt-4o"

    gemini_api_key: Optional[str] = None
    gemini_default_model: str = "gemini-3.6-flash"

    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "meta-llama/llama-3.3-70b-instruct"

    router9_enabled: bool = True
    router9_api_key: Optional[str] = None
    router9_base_url: str = "https://api.9router.com/v1"
    router9_default_model: str = ""

    anthropic_api_key: Optional[str] = None
    anthropic_default_model: str = "claude-3-5-sonnet-20241022"

    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str = "deepseek-chat"

    # Dynamic configuration from providers.yaml
    fallback_chains: dict[str, list[str]] = field(default_factory=dict)
    aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    custom_providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def is_user_allowed(self, user_id: int) -> bool:
        """Security check: user MUST be in telegram_allowed_users."""
        if not self.telegram_allowed_users:
            return False
        return user_id in self.telegram_allowed_users


def load_settings() -> Settings:
    """Load settings from environment, .env, and config/providers.yaml."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # Allowed users parsing
    raw_users = credentials.get("TELEGRAM_ALLOWED_USERS", "")
    allowed_users: set[int] = set()
    if raw_users:
        for uid_str in raw_users.split(","):
            cleaned = uid_str.strip()
            if cleaned.isdigit():
                allowed_users.add(int(cleaned))

    screenshot_dir_str = credentials.get("SCREENSHOT_DIR", str(SCREENSHOTS_DIR))
    screenshot_path = Path(screenshot_dir_str).resolve()
    screenshot_path.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        telegram_bot_token=credentials.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_allowed_users=allowed_users,
        browser_cdp_url=credentials.get("BROWSER_CDP_URL", "http://127.0.0.1:9222"),
        default_mode=credentials.get("DEFAULT_MODE", "browser").lower(),
        default_provider=credentials.get("DEFAULT_PROVIDER", "chatgpt_web").lower(),
        screenshot_mode=credentials.get("SCREENSHOT_MODE", "browser").lower(),
        screenshot_dir=screenshot_path,
        response_char_limit=int(credentials.get("RESPONSE_CHAR_LIMIT", "3900")),
        telegram_stream_update_interval=float(credentials.get("TELEGRAM_STREAM_UPDATE_INTERVAL", "1.5")),
        model_cache_seconds=int(credentials.get("MODEL_CACHE_SECONDS", "1800")),
        local_server_enabled=credentials.get("LOCAL_SERVER_ENABLED", "true").lower() in ("true", "1", "yes"),
        local_server_host=credentials.get("LOCAL_SERVER_HOST", "127.0.0.1"),
        local_server_port=int(credentials.get("LOCAL_SERVER_PORT", "8765")),
        agy_cli_path=credentials.get("AGY_CLI_PATH", "agy"),
        agy_default_model=credentials.get("AGY_DEFAULT_MODEL", "gemini-3.8-flash-low"),
        agy_effort=credentials.get("AGY_EFFORT", "").lower(),
        hermes_cli_path=credentials.get("HERMES_CLI_PATH", "hermes"),
        hermes_default_model=credentials.get("HERMES_DEFAULT_MODEL", ""),
        hermes_effort=credentials.get("HERMES_EFFORT", "").lower(),
        log_level=credentials.get("LOG_LEVEL", "INFO").upper(),
        openai_api_key=credentials.get("OPENAI_API_KEY"),
        openai_default_model=credentials.get("OPENAI_DEFAULT_MODEL", "gpt-4o"),
        gemini_api_key=credentials.get("GEMINI_API_KEY"),
        gemini_default_model=credentials.get("GEMINI_DEFAULT_MODEL", "gemini-3.6-flash"),
        openrouter_api_key=credentials.get("OPENROUTER_API_KEY"),
        openrouter_base_url=credentials.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_default_model=credentials.get("OPENROUTER_DEFAULT_MODEL", "meta-llama/llama-3.3-70b-instruct"),
        router9_enabled=credentials.get("ROUTER9_ENABLED", "true").lower() in ("true", "1", "yes"),
        router9_api_key=credentials.get("ROUTER9_API_KEY"),
        router9_base_url=credentials.get("ROUTER9_BASE_URL", "https://api.9router.com/v1"),
        router9_default_model=credentials.get("ROUTER9_DEFAULT_MODEL", ""),
        anthropic_api_key=credentials.get("ANTHROPIC_API_KEY"),
        anthropic_default_model=credentials.get("ANTHROPIC_DEFAULT_MODEL", "claude-3-5-sonnet-20241022"),
        deepseek_api_key=credentials.get("DEEPSEEK_API_KEY"),
        deepseek_base_url=credentials.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_default_model=credentials.get("DEEPSEEK_DEFAULT_MODEL", "deepseek-chat"),
    )

    # Load providers.yaml
    providers_yaml = CONFIG_DIR / "providers.yaml"
    if providers_yaml.is_file():
        try:
            with open(providers_yaml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                settings.fallback_chains = data.get("fallback_chains", {})
                settings.aliases = data.get("aliases", {})
                settings.custom_providers = data.get("providers", {}) or {}
        except Exception as e:
            logger.error("Failed to parse config/providers.yaml: %s", e)

    return settings


# Global settings instance
settings = load_settings()
