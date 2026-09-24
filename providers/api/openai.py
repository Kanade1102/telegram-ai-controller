"""Official OpenAI API provider."""

from typing import Optional
from providers.api.openai_compatible import OpenAICompatibleProvider
from config import settings


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.openai_api_key
        super().__init__(
            name="openai",
            friendly_name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key=key,
            default_model=settings.openai_default_model,
        )
