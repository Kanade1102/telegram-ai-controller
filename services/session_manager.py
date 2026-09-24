"""Manages active session state, persistence to data/state.json, and synchronization with database.

Never stores bot tokens, passwords, or API keys in state files.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, asdict
from config import DATA_DIR
from services.database import db

logger = logging.getLogger(__name__)
STATE_FILE = DATA_DIR / "state.json"


@dataclass
class SessionState:
    active_mode: str = "browser"  # "browser", "api", "auto"
    active_provider: str = "chatgpt_web"
    active_browser_tab_id: Optional[str] = None
    active_conversation_id: Optional[int] = None
    active_fallback_chain: Optional[str] = None
    active_effort: Optional[str] = None  # None = model default; else low|medium|high
    last_prompt: str = ""
    last_prompt_time: str = ""
    last_known_response: str = ""
    last_status: str = "IDLE"
    last_screenshot_time: str = ""


class SessionManager:
    def __init__(self, state_file: Path = STATE_FILE, database=None):
        self.state_file = state_file
        self.db = database or db  # injectable for tests; never let tests touch the real DB
        self.state = SessionState()
        self.load_state()

    def load_state(self) -> None:
        """Load minimal session state from JSON file and DB."""
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.state = SessionState(
                        active_mode=data.get("active_mode", "browser"),
                        active_provider=data.get("active_provider", "chatgpt_web"),
                        active_browser_tab_id=data.get("active_browser_tab_id"),
                        active_conversation_id=data.get("active_conversation_id"),
                        active_fallback_chain=data.get("active_fallback_chain"),
                        active_effort=data.get("active_effort"),
                        last_prompt=data.get("last_prompt", ""),
                        last_prompt_time=data.get("last_prompt_time", ""),
                        last_known_response=data.get("last_known_response", ""),
                        last_status=data.get("last_status", "IDLE"),
                        last_screenshot_time=data.get("last_screenshot_time", ""),
                    )
            except Exception as e:
                logger.warning("Could not load state from %s: %s", self.state_file, e)

        # Reconcile from DB if present
        saved_provider = self.db.get_session_val("active_provider")
        if saved_provider:
            self.state.active_provider = saved_provider
        saved_mode = self.db.get_session_val("active_mode")
        if saved_mode:
            self.state.active_mode = saved_mode
        saved_conv = self.db.get_session_val("active_conversation_id")
        if saved_conv and saved_conv.isdigit():
            self.state.active_conversation_id = int(saved_conv)
        saved_effort = self.db.get_session_val("active_effort")
        if saved_effort:
            self.state.active_effort = saved_effort

    def save_state(self) -> None:
        """Persist session state to state.json and DB."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            temp_file = self.state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self.state), f, indent=2, ensure_ascii=False)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error("Failed to save state to %s: %s", self.state_file, e)

        # Sync to DB
        try:
            self.db.set_session_val("active_provider", self.state.active_provider)
            self.db.set_session_val("active_mode", self.state.active_mode)
            if self.state.active_conversation_id is not None:
                self.db.set_session_val("active_conversation_id", str(self.state.active_conversation_id))
            if self.state.active_fallback_chain is not None:
                self.db.set_session_val("active_fallback_chain", self.state.active_fallback_chain)
            else:
                self.db.delete_session_val("active_fallback_chain")
            if self.state.active_effort is not None:
                self.db.set_session_val("active_effort", self.state.active_effort)
            else:
                self.db.delete_session_val("active_effort")
        except Exception as e:
            logger.error("Failed to sync session state to DB: %s", e)

    def set_provider(self, provider: str) -> None:
        self.state.active_provider = provider
        if "_web" in provider:
            self.state.active_mode = "browser"
        else:
            self.state.active_mode = "api"
        self.save_state()

    def set_mode(self, mode: str) -> None:
        self.state.active_mode = mode
        self.save_state()

    def set_conversation(self, conv_id: int) -> None:
        self.state.active_conversation_id = conv_id
        self.save_state()

    def set_browser_tab(self, tab_id: str) -> None:
        self.state.active_browser_tab_id = tab_id
        self.save_state()

    def set_fallback(self, fallback: Optional[str]) -> None:
        self.state.active_fallback_chain = fallback
        self.save_state()

    def set_effort(self, effort: Optional[str]) -> None:
        self.state.active_effort = effort
        self.save_state()

    def record_prompt(self, prompt: str, timestamp: str) -> None:
        self.state.last_prompt = prompt
        self.state.last_prompt_time = timestamp
        self.state.last_status = "GENERATING"
        self.save_state()

    def record_response(self, response: str, status: str = "IDLE") -> None:
        self.state.last_known_response = response
        self.state.last_status = status
        self.save_state()

    def record_screenshot(self, timestamp: str) -> None:
        self.state.last_screenshot_time = timestamp
        self.save_state()


session_manager = SessionManager()
