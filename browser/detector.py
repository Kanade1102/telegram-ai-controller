"""Browser AI page and progress state detection."""

from enum import Enum
from typing import Optional


class ProgressState(str, Enum):
    IDLE = "IDLE"
    GENERATING = "GENERATING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


def detect_provider_from_url(url: str) -> Optional[str]:
    """Identify AI provider from tab URL."""
    if not url:
        return None
    url_lower = url.lower()
    if "chatgpt.com" in url_lower or "chat.openai.com" in url_lower:
        return "chatgpt_web"
    elif "gemini.google.com" in url_lower:
        return "gemini_web"
    elif "claude.ai" in url_lower:
        return "claude_web"
    elif "chat.deepseek.com" in url_lower:
        return "deepseek_web"
    return None


def get_provider_display_name(provider_key: str) -> str:
    """Format provider key to user-friendly label."""
    mapping = {
        "chatgpt_web": "ChatGPT Web",
        "gemini_web": "Gemini Web",
        "claude_web": "Claude Web",
        "deepseek_web": "DeepSeek Web",
        "openai": "OpenAI",
        "gemini_api": "Gemini API",
        "agy": "AGY (Antigravity)",
        "hermes": "Hermes Agent (local CLI)",
        "openrouter": "OpenRouter",
        "9router": "9Router",
        "anthropic": "Anthropic",
        "deepseek": "DeepSeek",
    }
    return mapping.get(provider_key, provider_key)
