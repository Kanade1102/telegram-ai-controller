"""API provider registry and dynamic loader."""

import os
import logging
from typing import Optional
from providers.api.base import APIProvider
from providers.api.openai_compatible import OpenAICompatibleProvider
from providers.api.openai import OpenAIProvider
from providers.api.gemini import GeminiAPIProvider
from providers.api.anthropic import AnthropicProvider
from providers.api.agy import AgyCLIProvider
from providers.api.presets.openrouter import OpenRouterProvider
from providers.api.presets.router9 import Router9Provider
from providers.api.presets.deepseek import DeepSeekAPIProvider
from services.credential_manager import credentials
from config import settings

logger = logging.getLogger(__name__)


class APIProviderRegistry:
    def __init__(self):
        self._providers: dict[str, APIProvider] = {}
        self.reload()

    def reload(self) -> None:
        """Register built-in providers and dynamically load custom ones from YAML."""
        self._providers.clear()

        # Built-in providers
        self.register(OpenAIProvider())
        self.register(GeminiAPIProvider())
        self.register(AgyCLIProvider())
        self.register(OpenRouterProvider())
        if settings.router9_enabled:
            self.register(Router9Provider())
        self.register(AnthropicProvider())
        self.register(DeepSeekAPIProvider())

        # Load dynamic custom providers from providers.yaml
        for p_name, p_cfg in settings.custom_providers.items():
            try:
                p_type = p_cfg.get("type", "openai_compatible")
                if p_type == "openai_compatible":
                    env_key = p_cfg.get("api_key_env", "")
                    api_key = credentials.get(env_key, "") if env_key else ""
                    provider = OpenAICompatibleProvider(
                        name=p_name.lower(),
                        friendly_name=p_cfg.get("friendly_name", p_name.title()),
                        base_url=p_cfg.get("base_url", "http://127.0.0.1:1234/v1"),
                        api_key=api_key,
                        default_model=p_cfg.get("default_model", ""),
                        custom_headers=p_cfg.get("custom_headers", {}),
                        timeout=float(p_cfg.get("timeout", 60.0)),
                        extra_body=p_cfg.get("extra_body", {}),
                    )
                    self.register(provider)
                    logger.info("Loaded custom dynamic provider: %s", p_name)
            except Exception as e:
                logger.error("Failed to load custom provider '%s': %s", p_name, e)

    def register(self, provider: APIProvider) -> None:
        self._providers[provider.name.lower()] = provider

    def get(self, name: str) -> Optional[APIProvider]:
        clean = name.lower().strip()
        # Direct match
        if clean in self._providers:
            return self._providers[clean]
        # Match without _api suffix if passed e.g. "gemini" -> "gemini_api"
        if f"{clean}_api" in self._providers:
            return self._providers[f"{clean}_api"]
        # Match with _api suffix stripped e.g. "openai_api" -> "openai"
        if clean.endswith("_api") and clean[:-4] in self._providers:
            return self._providers[clean[:-4]]
        return None

    def list_all(self) -> list[APIProvider]:
        return list(self._providers.values())


registry = APIProviderRegistry()

# Cached startup/live health results: provider_name -> (success, message, latency_ms)
health_cache: dict[str, tuple[bool, str, float]] = {}


def get_api_provider(name: str) -> Optional[APIProvider]:
    return registry.get(name)


def list_api_providers() -> list[APIProvider]:
    return registry.list_all()
