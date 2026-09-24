"""Fallback and routing manager for sequential multi-provider resilience."""

import logging
from typing import Optional
from config import settings
from services.session_manager import session_manager

logger = logging.getLogger(__name__)


class FallbackManager:
    def list_chains(self) -> dict[str, list[str]]:
        return dict(settings.fallback_chains)

    def get_active_chain_name(self) -> Optional[str]:
        return session_manager.state.active_fallback_chain

    def set_active_chain(self, name: Optional[str]) -> bool:
        if name is None or name.lower() in ("off", "none", "disable"):
            session_manager.set_fallback(None)
            return True

        clean = name.lower().strip()
        if clean in settings.fallback_chains:
            session_manager.set_fallback(clean)
            return True
        return False

    def get_chain_providers(self, chain_name: Optional[str] = None) -> list[str]:
        target = chain_name or self.get_active_chain_name()
        if not target or target not in settings.fallback_chains:
            return []
        return list(settings.fallback_chains[target])


fallback_manager = FallbackManager()
