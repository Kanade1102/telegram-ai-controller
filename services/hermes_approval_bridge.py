"""Hermes approval bridge — routes desktop-REPL approval requests to Telegram.

The hermes plugin ~/.hermes/plugins/telegram-approval-bridge registers an
approval transport ("telegram-bridge") in the user's interactive REPL. When
the REPL's agent wants to run a flagged/dangerous command, the transport POSTs
the request to this bot's local web server (127.0.0.1:8765/api/approval), the
bot sends a Telegram message with inline y/n buttons, and the user's tap
resolves the request. Timeout and any failure = deny (silence is not consent).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

BRIDGE_TIMEOUT_S = 300.0  # must stay < the REPL's approval timeout


class HermesApprovalBridge:
    """In-process registry: request_id -> future resolved by a Telegram tap."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._poster: Any = None  # async fn(payload: dict) -> None

    def set_poster(self, poster: Any) -> None:
        self._poster = poster

    async def submit(self, payload: dict[str, Any]) -> tuple[str, Optional[str]]:
        """Register an approval request, post to Telegram, await the answer."""
        rid = str(payload.get("request_id") or "")
        if not rid:
            return "deny", "missing request_id"
        fut = asyncio.get_event_loop().create_future()
        async with self._lock:
            self._pending[rid] = fut
        try:
            if self._poster is not None:
                await self._poster({**payload, "rid": rid})
            choice = await asyncio.wait_for(fut, timeout=BRIDGE_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("hermes approval %s timed out — denying", rid)
            return "deny", "timed out"
        except Exception as e:
            logger.warning("hermes approval %s poster failed: %s", rid, e)
            return "deny", "poster failed"
        finally:
            async with self._lock:
                self._pending.pop(rid, None)
        return str(choice), None

    async def answer(self, rid: str, choice: str) -> bool:
        """Resolve a pending request from a Telegram button tap."""
        async with self._lock:
            fut = self._pending.get(rid)
        if fut and not fut.done():
            fut.set_result(choice)
            return True
        return False


hermes_bridge = HermesApprovalBridge()
