"""Hermes approval bridge + repl_inject unit tests (in-process, no desktop)."""

import asyncio

import pytest

from services.hermes_approval_bridge import HermesApprovalBridge
from services.repl_inject import inject_prompt_into_repl


def test_bridge_allow_and_deny():
    bridge = HermesApprovalBridge()
    posted = []

    async def poster(payload):
        posted.append(payload)

    async def go():
        bridge.set_poster(poster)
        t1 = asyncio.create_task(bridge.submit({"request_id": "r1", "command": "rm x"}))
        await asyncio.sleep(0)
        assert await bridge.answer("r1", "once")
        choice, note = await t1
        return choice, note, posted

    choice, note, posted = asyncio.run(go())
    assert choice == "once"
    assert note is None
    assert posted and posted[0]["rid"] == "r1"
    assert posted[0]["command"] == "rm x"


def test_bridge_missing_rid_denies():
    bridge = HermesApprovalBridge()
    choice, note = asyncio.run(bridge.submit({"command": "x"}))
    assert choice == "deny"
    assert note == "missing request_id"


def test_bridge_timeout_denies():
    bridge = HermesApprovalBridge()

    async def go():
        # No poster (never called), tiny wait via monkeypatched timeout
        return await bridge.submit({"request_id": "r3"})

    # Patch timeout to 0.05 to keep the test fast
    import services.hermes_approval_bridge as mod
    old = mod.BRIDGE_TIMEOUT_S
    mod.BRIDGE_TIMEOUT_S = 0.05
    try:
        choice, note = asyncio.run(go())
    finally:
        mod.BRIDGE_TIMEOUT_S = old
    assert choice == "deny"
    assert note == "timed out"


def test_bridge_unknown_answer_returns_false():
    bridge = HermesApprovalBridge()
    assert asyncio.run(bridge.answer("nope", "once")) is False


def test_inject_missing_wtype_fails_clean():
    """Without wtype on PATH, injection returns False (no crash)."""
    import services.repl_inject as mod
    old = mod.shutil.which

    def fake_which(name):
        return None if name == "wtype" else old(name)

    mod.shutil.which = fake_which
    try:
        assert asyncio.run(inject_prompt_into_repl("hello")) is False
    finally:
        mod.shutil.which = old


def test_inject_empty_prompt_fails():
    import services.repl_inject as mod
    old = mod.shutil.which
    mod.shutil.which = lambda name: "/usr/bin/wtype"
    try:
        # find_hermes_window would need hyprctl; without it returns None -> False
        assert asyncio.run(inject_prompt_into_repl("   \n  ")) is False
    finally:
        mod.shutil.which = old
