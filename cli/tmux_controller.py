"""Tmux controller architecture for terminal AI CLI integrations (Claude Code, Aider, Codex CLI, etc.)."""

import shutil
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TmuxController:
    """Manages background terminal AI sessions via tmux."""

    def __init__(self, default_session: str = "ai-cli"):
        self.default_session = default_session

    def is_available(self) -> bool:
        """Check if tmux binary is installed on the host."""
        return shutil.which("tmux") is not None

    async def run_command(self, *args: str) -> tuple[int, str, str]:
        """Run a tmux CLI command asynchronously."""
        if not self.is_available():
            return -1, "", "tmux is not installed on this system"
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode("utf-8"), stderr.decode("utf-8")
        except Exception as e:
            logger.error("Error executing tmux %s: %s", args, e)
            return -1, "", str(e)

    async def list_sessions(self) -> list[str]:
        """List active tmux sessions."""
        code, out, _ = await self.run_command("list-sessions", "-F", "#{session_name}")
        if code != 0 or not out:
            return []
        return [s.strip() for s in out.splitlines() if s.strip()]

    async def send_keys(self, keys: str, session: Optional[str] = None, pane: str = "0") -> bool:
        """Send keys (prompt or commands) to a tmux target pane."""
        target = f"{session or self.default_session}:{pane}"
        code, _, err = await self.run_command("send-keys", "-t", target, keys, "C-m")
        if code != 0:
            logger.warning("Failed to send keys to tmux target %s: %s", target, err)
            return False
        return True

    async def capture_pane(self, session: Optional[str] = None, pane: str = "0", lines: int = 50) -> str:
        """Capture terminal output from a tmux pane."""
        target = f"{session or self.default_session}:{pane}"
        code, out, err = await self.run_command("capture-pane", "-p", "-t", target, "-S", f"-{lines}")
        if code != 0:
            logger.warning("Failed to capture tmux pane %s: %s", target, err)
            return ""
        return out

    async def has_session(self, session: Optional[str] = None) -> bool:
        """Check if a specific tmux session exists."""
        target = session or self.default_session
        code, _, _ = await self.run_command("has-session", "-t", target)
        return code == 0

    async def start_session(self, session: Optional[str] = None, command: Optional[str] = None) -> bool:
        """Create a new background tmux session running a command."""
        target = session or self.default_session
        if await self.has_session(target):
            return True
        args = ["new-session", "-d", "-s", target]
        if command:
            args.append(command)
        code, _, err = await self.run_command(*args)
        if code != 0:
            logger.warning("Failed to create tmux session %s: %s", target, err)
            return False
        return True

    async def kill_session(self, session: Optional[str] = None) -> bool:
        """Kill a tmux session."""
        target = session or self.default_session
        code, _, err = await self.run_command("kill-session", "-t", target)
        return code == 0


tmux_controller = TmuxController()

