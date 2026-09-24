"""Tests for browser providers with mock page objects."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from providers.browser.chatgpt import ChatGPTWebProvider
from providers.browser.gemini import GeminiWebProvider
from providers.browser.claude import ClaudeWebProvider
from providers.browser.deepseek import DeepSeekWebProvider
from browser.detector import ProgressState


@pytest.mark.asyncio
async def test_chatgpt_provider_status_generating():
    prov = ChatGPTWebProvider()
    page = MagicMock()

    # Mock stop button visible -> GENERATING
    stop_btn = MagicMock()
    stop_btn.count = AsyncMock(return_value=1)
    stop_btn.first.is_visible = AsyncMock(return_value=True)

    page.locator = MagicMock(return_value=stop_btn)

    status = await prov.get_status(page)
    assert status == ProgressState.GENERATING.value


@pytest.mark.asyncio
async def test_gemini_provider_status_generating():
    prov = GeminiWebProvider()
    page = MagicMock()

    stop_btn = MagicMock()
    stop_btn.count = AsyncMock(return_value=1)
    stop_btn.first.is_visible = AsyncMock(return_value=True)

    page.locator = MagicMock(return_value=stop_btn)

    status = await prov.get_status(page)
    assert status == ProgressState.GENERATING.value


@pytest.mark.asyncio
async def test_claude_provider_status_generating():
    prov = ClaudeWebProvider()
    page = MagicMock()

    stop_btn = MagicMock()
    stop_btn.count = AsyncMock(return_value=1)
    stop_btn.first.is_visible = AsyncMock(return_value=True)

    page.locator = MagicMock(return_value=stop_btn)

    status = await prov.get_status(page)
    assert status == ProgressState.GENERATING.value


@pytest.mark.asyncio
async def test_deepseek_provider_status_generating():
    prov = DeepSeekWebProvider()
    page = MagicMock()

    stop_btn = MagicMock()
    stop_btn.count = AsyncMock(return_value=1)
    stop_btn.first.is_visible = AsyncMock(return_value=True)

    page.locator = MagicMock(return_value=stop_btn)

    status = await prov.get_status(page)
    assert status == ProgressState.GENERATING.value


@pytest.mark.asyncio
async def test_chatgpt_send_prompt_success():
    prov = ChatGPTWebProvider()
    page = MagicMock()

    input_loc = MagicMock()
    input_loc.count = AsyncMock(return_value=1)
    input_loc.is_visible = AsyncMock(return_value=True)
    input_loc.click = AsyncMock()
    input_loc.fill = AsyncMock()

    send_btn = MagicMock()
    send_btn.count = AsyncMock(return_value=1)
    send_btn.is_visible = AsyncMock(return_value=True)
    send_btn.is_enabled = AsyncMock(return_value=True)
    send_btn.click = AsyncMock()

    def locator_side_effect(selector):
        if "send" in selector.lower():
            m = MagicMock()
            m.first = send_btn
            return m
        m = MagicMock()
        m.first = input_loc
        return m

    page.locator = MagicMock(side_effect=locator_side_effect)
    page.wait_for_timeout = AsyncMock()

    success = await prov.send_prompt(page, "Test prompt")
    assert success is True
    input_loc.fill.assert_awaited_once_with("Test prompt")
    send_btn.click.assert_awaited_once()
