"""Model manager storing active models per provider and resolving aliases."""

import logging
from typing import Optional
from config import settings
from services.database import db
from providers.api import get_api_provider

logger = logging.getLogger(__name__)


class ModelManager:
    def get_selected_model(self, provider_name: str) -> str:
        """Get selected model for a specific provider, falling back to default."""
        clean_p = provider_name.lower().strip()
        # 1. From database
        saved_model = db.get_provider_model(clean_p)
        if saved_model:
            return saved_model

        # 2. From provider's default model
        prov = get_api_provider(clean_p)
        if prov and prov.default_model:
            return prov.default_model

        return ""

    def set_selected_model(self, provider_name: str, model_name: str) -> None:
        """Persist selected model for this provider."""
        clean_p = provider_name.lower().strip()
        db.set_provider_model(clean_p, model_name.strip())

    def resolve_alias(self, alias_name: str) -> Optional[tuple[str, str]]:
        """Resolve alias e.g. 'coding' -> ('openrouter', 'meta-llama/llama-3.3-70b-instruct')."""
        clean_alias = alias_name.lower().strip()
        if clean_alias in settings.aliases:
            entry = settings.aliases[clean_alias]
            p = entry.get("provider", "")
            m = entry.get("model", "")
            if p and m:
                return p, m
        return None

    async def list_models_for_provider(self, provider_name: str, refresh: bool = False) -> list[str]:
        prov = get_api_provider(provider_name)
        if not prov:
            return []
        try:
            return await prov.list_models(refresh=refresh)
        except Exception as e:
            logger.warning("Error listing models for %s: %s", provider_name, e)
            return [prov.default_model] if prov.default_model else []


model_manager = ModelManager()
