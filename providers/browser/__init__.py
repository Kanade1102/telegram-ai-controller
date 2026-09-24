"""Browser AI provider registry."""

from typing import Optional
from providers.browser.base import BrowserAIProvider
from providers.browser.chatgpt import ChatGPTWebProvider
from providers.browser.gemini import GeminiWebProvider
from providers.browser.claude import ClaudeWebProvider
from providers.browser.deepseek import DeepSeekWebProvider

BROWSER_PROVIDERS: dict[str, BrowserAIProvider] = {
    "chatgpt_web": ChatGPTWebProvider(),
    "gemini_web": GeminiWebProvider(),
    "claude_web": ClaudeWebProvider(),
    "deepseek_web": DeepSeekWebProvider(),
}


def get_browser_provider_by_url(url: str) -> Optional[BrowserAIProvider]:
    for provider in BROWSER_PROVIDERS.values():
        if provider.matches_url(url):
            return provider
    return None


def get_browser_provider_by_name(name: str) -> Optional[BrowserAIProvider]:
    clean_name = name.lower().strip()
    if clean_name in BROWSER_PROVIDERS:
        return BROWSER_PROVIDERS[clean_name]
    # Check alias without _web
    if f"{clean_name}_web" in BROWSER_PROVIDERS:
        return BROWSER_PROVIDERS[f"{clean_name}_web"]
    return None
