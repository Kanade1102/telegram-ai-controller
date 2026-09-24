"""OpenRouter provider preset."""

from typing import Optional
from providers.api.openai_compatible import OpenAICompatibleProvider
from config import settings


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.openrouter_api_key
        super().__init__(
            name="openrouter",
            friendly_name="OpenRouter",
            base_url=settings.openrouter_base_url,
            api_key=key,
            default_model=settings.openrouter_default_model,
            custom_headers={
                "HTTP-Referer": "https://github.com/telegram-ai-controller",
                "X-Title": "Telegram AI Controller",
            }
        )
