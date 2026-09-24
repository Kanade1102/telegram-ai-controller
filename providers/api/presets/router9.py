"""9Router provider preset."""

from typing import Optional
from providers.api.openai_compatible import OpenAICompatibleProvider
from config import settings


class Router9Provider(OpenAICompatibleProvider):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.router9_api_key
        super().__init__(
            name="9router",
            friendly_name="9Router",
            base_url=settings.router9_base_url,
            api_key=key,
            default_model=settings.router9_default_model,
        )
