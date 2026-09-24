"""Unified provider lookup for both browser and direct API backends."""

from typing import Union, Optional
from providers.browser import get_browser_provider_by_name, BROWSER_PROVIDERS
from providers.browser.base import BrowserAIProvider
from providers.api import get_api_provider, list_api_providers, APIProvider

AnyProvider = Union[BrowserAIProvider, APIProvider]


def get_provider(name: str) -> Optional[AnyProvider]:
    """Retrieve provider by key.

    Priority:
    - If ends with _web: browser provider
    - If ends with _api: API provider
    - Else check API provider then Browser provider
    """
    clean = name.lower().strip()
    if clean.endswith("_web"):
        return get_browser_provider_by_name(clean)
    if clean.endswith("_api"):
        return get_api_provider(clean)

    api_p = get_api_provider(clean)
    if api_p:
        return api_p

    browser_p = get_browser_provider_by_name(clean)
    if browser_p:
        return browser_p

    return None
