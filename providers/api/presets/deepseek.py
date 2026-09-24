"""DeepSeek API provider preset."""

from typing import Optional
from providers.api.openai_compatible import OpenAICompatibleProvider
from config import settings


class DeepSeekAPIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.deepseek_api_key
        super().__init__(
            name="deepseek",
            friendly_name="DeepSeek",
            base_url=settings.deepseek_base_url,
            api_key=key,
            default_model=settings.deepseek_default_model,
        )
