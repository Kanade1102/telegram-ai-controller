"""Credential manager handling environment variables, .env files, and optional OS keyring.

Ensures secrets are never exposed in logs, outputs, or unencrypted local state.
Priority order:
1. Environment variables
2. .env file
3. OS Keyring (GNOME Keyring / Secret Service / KWallet via Python keyring)
"""

import os
import logging
from typing import Optional
from pathlib import Path
from dotenv import dotenv_values, find_dotenv

logger = logging.getLogger(__name__)

# Keyring service name
KEYRING_SERVICE_NAME = "telegram-ai-controller"


def mask_secret(secret: Optional[str], visible_chars: int = 4) -> str:
    """Mask sensitive string like an API key.

    Example: 'sk-1234567890abcdef' -> 'sk-12...cdef'
    """
    if not secret:
        return "[NOT SET]"
    secret_str = str(secret).strip()
    if len(secret_str) <= visible_chars * 2:
        return "********"
    if secret_str.startswith("sk-"):
        # Show 'sk-' followed by 2 characters, e.g. 'sk-12...cdef'
        prefix = secret_str[:5]
    else:
        prefix = secret_str[:visible_chars]
    suffix = secret_str[-visible_chars:]
    return f"{prefix}...{suffix}"


class CredentialManager:
    """Manages credentials across env vars, .env, and optional OS keyring."""

    def __init__(self, env_path: Optional[str] = None):
        self.env_path = env_path or find_dotenv(usecwd=True)
        self._dotenv_cache: dict[str, str] = {}
        if self.env_path and Path(self.env_path).is_file():
            self._dotenv_cache = {k: v for k, v in dotenv_values(self.env_path).items() if v is not None}
        self._keyring_available = self._check_keyring()

    def _check_keyring(self) -> bool:
        """Check if keyring is supported and operational."""
        try:
            import keyring
            # Test getting or checking backend
            backend = keyring.get_keyring()
            # If backend is fail backend, disable
            backend_name = backend.__class__.__name__
            if "fail" in backend_name.lower() or "null" in backend_name.lower():
                return False
            return True
        except Exception as e:
            logger.debug("Keyring not available: %s", e)
            return False

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve credential with priority: OS env -> .env file -> Keyring."""
        # 1. OS environment variable
        val = os.environ.get(key)
        if val is not None and val != "":
            return val

        # 2. .env file
        if key in self._dotenv_cache and self._dotenv_cache[key] != "":
            return self._dotenv_cache[key]

        # 3. Keyring
        if self._keyring_available:
            try:
                import keyring
                kr_val = keyring.get_password(KEYRING_SERVICE_NAME, key)
                if kr_val:
                    return kr_val
            except Exception as e:
                logger.debug("Error querying keyring for %s: %s", key, e)

        return default

    def set(self, key: str, value: str, store_in_keyring: bool = False) -> None:
        """Store credential in process env or optionally in system keyring."""
        os.environ[key] = value
        self._dotenv_cache[key] = value
        if store_in_keyring and self._keyring_available:
            try:
                import keyring
                keyring.set_password(KEYRING_SERVICE_NAME, key, value)
            except Exception as e:
                logger.warning("Failed to store %s in keyring: %s", key, e)

    @property
    def keyring_available(self) -> bool:
        return self._keyring_available


# Global singleton instance
credentials = CredentialManager()
