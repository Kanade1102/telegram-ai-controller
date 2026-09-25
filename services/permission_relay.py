"""Claude CLI permission relay — Telegram-mediated tool approval.

When claudecode runs with --permission-prompt-tool stdio, the CLI sends
`control_request` / `can_use_tool` events on stdout and waits for a
`control_response` on stdin. This service turns each request into a Telegram
message with inline y/n buttons and answers allow/deny from the user's click.

Design: in-process asyncio. No MCP server, no file channel. The provider owns
the claude subprocess; this module owns the control-protocol conversation.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Deny: the CLI decides what happens next (model sees denied, retries without
# the tool). Timeout -> deny, never allow: a silent auto-approve would defeat
# the whole point of the relay.
DENY = {"behavior": "deny", "message": "Denied by user via Telegram."}


@dataclass
class PendingApproval:
    """One tool-use request waiting for a Telegram y/n answer."""
    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())

    @property
    def description(self) -> str:
        """Short human line for the Telegram prompt."""
        desc = str(self.tool_input.get("description") or "").strip()
        command = str(self.tool_input.get("command") or "").strip()
        text = f"{self.tool_name}: {desc or command or '?'}"
        if len(text) > 280:
            text = text[:277] + "..."
        return text


class PermissionRelay:
    """Registry of pending approvals. The provider's control loop awaits
    `request_approval()`; the bot handler resolves via `answer()`."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._lock = asyncio.Lock()
        # Providers in flight: request_id -> asyncio.Task (for /stop cleanup)
        self._runs: dict[str, asyncio.Task] = {}

    async def register(
        self,
        request_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        timeout_s: float,
    ) -> tuple[bool, Optional[str]]:
        """Register a pending approval and block until answered. Returns
        (allowed, note). Timeout denies (never auto-allows)."""
        pending = PendingApproval(
            request_id=request_id, tool_name=tool_name, tool_input=tool_input
        )
        async with self._lock:
            self._pending[request_id] = pending
        try:
            return await asyncio.wait_for(pending.future, timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("Permission %s timed out after %.0fs — denying", request_id, timeout_s)
            return False, "timed out"
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def answer(self, request_id: str, allowed: bool, note: str = "") -> bool:
        """Resolve a pending approval. Returns True if it was still waiting."""
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending and not pending.future.done():
            pending.future.set_result((allowed, note or ("allowed" if allowed else "denied")))
            return True
        return False

    def cancel_all(self, note: str = "cancelled") -> int:
        """Deny every pending approval (used on /stop or generator teardown)."""
        count = 0
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_result((False, note))
                count += 1
        return count


permission_relay = PermissionRelay()


async def control_loop(
    proc: asyncio.subprocess.Process,
    on_request: Any,
    on_event: Any,
    on_ready: Any = None,
    timeout_s: float = 720.0,
) -> None:
    """Run the control-protocol conversation on claude's stdio.

    Owns stdout exclusively (stream events, result, control requests all
    arrive on the same pipe). Sequence: initialize handshake -> set manual
    permission mode -> on_ready() (caller sends the user message) -> answer
    can_use_tool requests via on_request() -> on_event() for stream/result.
    """
    assert proc.stdin is not None
    assert proc.stdout is not None

    async def send(obj: dict[str, Any]) -> None:
        proc.stdin.write((json.dumps(obj) + "\n").encode())
        await proc.stdin.drain()

    await send({
        "type": "control_request",
        "request_id": "perm-init",
        "request": {"subtype": "initialize", "hooks": {}},
    })

    while True:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("claude control loop idle timeout after %.0fs", timeout_s)
            break
        if not line:
            break
        s = line.decode("utf-8", "replace").strip()
        if not s:
            continue
        try:
            ev = json.loads(s)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type")
        if ev_type == "control_response":
            resp = ev.get("response", {})
            rid = resp.get("request_id", "")
            if rid == "perm-init":
                # Mode may read "default" from a dir gate; force manual so the
                # CLI prompts us instead of auto-denying.
                await send({
                    "type": "control_request",
                    "request_id": "perm-mode",
                    "request": {"subtype": "set_permission_mode", "mode": "manual"},
                })
            elif rid == "perm-mode" and on_ready is not None:
                await on_ready()
        elif ev_type == "control_request":
            req = ev.get("request", {})
            subtype = req.get("subtype", "")
            rid = ev.get("request_id", "")
            if subtype == "can_use_tool":
                allowed, note = await on_request(
                    rid,
                    req.get("tool_name", "?"),
                    req.get("input", {}),
                )
                resp_data = dict(DENY) if not allowed else {
                    "behavior": "allow",
                    "updatedInput": req.get("input", {}),
                }
                if not allowed:
                    resp_data["message"] = note or DENY["message"]
                await send({
                    "type": "control_response",
                    "response": {"subtype": "success", "request_id": rid, "response": resp_data},
                })
            else:
                # Unknown control subtype (CLI-side initialize etc.): ack.
                await send({
                    "type": "control_response",
                    "response": {"subtype": "success", "request_id": rid, "response": {}},
                })
        elif ev_type in ("stream_event", "result"):
            await on_event(ev)
