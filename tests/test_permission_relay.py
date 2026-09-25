"""Claude permission relay unit tests — in-process, no real claude binary."""

import asyncio
import json

import pytest

from services.permission_relay import (
    PermissionRelay,
    permission_relay,
    control_loop,
    DENY,
)


class FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data.decode("utf-8"))

    async def drain(self):
        pass


class FakeStream:
    """Scripted stdout: list of JSON-serializable events, then EOF."""

    def __init__(self, events):
        self.events = [json.dumps(e).encode() for e in events]

    async def readline(self):
        return self.events.pop(0) if self.events else b""


class FakeProc:
    def __init__(self, events):
        self.returncode = 0
        self.stdin = FakeStdin()
        self.stdout = FakeStream(events)

    async def wait(self):
        return 0

    def kill(self):
        pass


def make_events(include_request=False):
    """init ack -> mode ack -> [can_use_tool] -> result."""
    evs = [
        {"type": "control_response", "response": {"request_id": "perm-init", "subtype": "success", "response": {}}},
        {"type": "control_response", "response": {"request_id": "perm-mode", "subtype": "success", "response": {}}},
    ]
    if include_request:
        evs.append({
            "type": "control_request",
            "request_id": "req-1",
            "request": {
                "subtype": "can_use_tool",
                "tool_name": "Bash",
                "input": {"command": "echo hi", "description": "say hi"},
            },
        })
    evs.append({"type": "result", "subtype": "success", "is_error": False, "result": "done"})
    return evs


def test_relay_register_answer_allow():
    relay = PermissionRelay()

    async def go():
        reg = asyncio.create_task(relay.register("r1", "Bash", {"command": "x"}, timeout_s=5))
        await asyncio.sleep(0)
        assert await relay.answer("r1", True)
        allowed, note = await reg
        return allowed, note

    allowed, note = asyncio.run(go())
    assert allowed is True
    assert note == "allowed"


def test_relay_register_answer_deny():
    relay = PermissionRelay()

    async def go():
        reg = asyncio.create_task(relay.register("r2", "Bash", {"command": "x"}, timeout_s=5))
        await asyncio.sleep(0)
        assert await relay.answer("r2", False, "user said no")
        return await reg

    allowed, note = asyncio.run(go())
    assert allowed is False
    assert note == "user said no"


def test_relay_timeout_denies():
    relay = PermissionRelay()

    async def go():
        return await relay.register("r3", "Bash", {"command": "x"}, timeout_s=0.1)

    allowed, note = asyncio.run(go())
    assert allowed is False
    assert note == "timed out"


def test_relay_answer_unknown_id_returns_false():
    relay = PermissionRelay()
    assert asyncio.run(relay.answer("nope", True)) is False


def test_relay_cancel_all_denies():
    relay = PermissionRelay()

    async def go():
        reg = asyncio.create_task(relay.register("r4", "Bash", {"command": "x"}, timeout_s=5))
        await asyncio.sleep(0)
        assert relay.cancel_all("stopped") == 1
        return await reg

    allowed, note = asyncio.run(go())
    assert allowed is False
    assert note == "stopped"


def test_control_loop_allow_writes_response():
    proc = FakeProc(make_events(include_request=True))
    seen = []

    async def on_request(rid, tool_name, tool_input):
        seen.append((rid, tool_name, tool_input))
        return True, "allowed"

    async def on_event(ev):
        seen.append(("event", ev.get("type")))

    async def on_ready():
        seen.append(("ready",))

    asyncio.run(control_loop(proc, on_request, on_event, on_ready=on_ready))

    assert ("ready",) in seen
    assert ("req-1", "Bash", {"command": "echo hi", "description": "say hi"}) in seen
    assert ("event", "result") in seen
    # stdin received initialize, set_permission_mode, then allow response
    written = "\n".join(proc.stdin.writes)
    assert '"subtype": "initialize"' in written
    assert '"subtype": "set_permission_mode"' in written
    assert '"behavior": "allow"' in written
    assert '"updatedInput"' in written


def test_control_loop_deny_writes_message():
    proc = FakeProc(make_events(include_request=True))
    seen = []

    async def on_request(rid, tool_name, tool_input):
        seen.append(rid)
        return False, "user said no"

    async def on_event(ev):
        pass

    asyncio.run(control_loop(proc, on_request, on_event))
    written = "\n".join(proc.stdin.writes)
    assert '"behavior": "deny"' in written
    assert "user said no" in written


def test_control_loop_stream_events_forwarded():
    events = make_events(include_request=False)
    events.insert(2, {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"text": "hi"}}})
    proc = FakeProc(events)
    seen = []

    async def on_event(ev):
        seen.append(ev.get("type"))

    asyncio.run(control_loop(proc, lambda *a: None, on_event))
    assert seen == ["stream_event", "result"]


def test_deny_constant_shape():
    assert DENY["behavior"] == "deny"
    assert "message" in DENY
