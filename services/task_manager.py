"""Unified AI task tracking and lifecycle management."""

import time
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    CONNECTING = "CONNECTING"
    GENERATING = "GENERATING"
    WAITING = "WAITING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


@dataclass
class AITask:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    backend: str = "browser"  # "browser" or "api"
    provider: str = ""
    mode: str = "browser"
    model: str = ""
    conversation_id: Optional[int] = None
    prompt: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: TaskStatus = TaskStatus.QUEUED
    latest_output: str = ""
    error: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0
    })
    screenshot_path: Optional[str] = None
    cancel_requested: bool = False

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    @property
    def elapsed_formatted(self) -> str:
        secs = int(self.elapsed_seconds)
        hours = secs // 3600
        mins = (secs % 3600) // 60
        s = secs % 60
        return f"{hours:02d}:{mins:02d}:{s:02d}"


class TaskManager:
    def __init__(self):
        self._active_task: Optional[AITask] = None
        self._history: list[AITask] = []

    def create_task(
        self,
        backend: str,
        provider: str,
        mode: str,
        prompt: str,
        model: str = "",
        conversation_id: Optional[int] = None
    ) -> AITask:
        task = AITask(
            backend=backend,
            provider=provider,
            mode=mode,
            prompt=prompt,
            model=model,
            conversation_id=conversation_id,
            status=TaskStatus.CONNECTING
        )
        self._active_task = task
        self._history.append(task)
        if len(self._history) > 100:
            self._history.pop(0)
        return task

    def get_active_task(self) -> Optional[AITask]:
        return self._active_task

    def update_task_output(self, task_id: str, chunk: str) -> None:
        if self._active_task and self._active_task.id == task_id:
            self._active_task.latest_output += chunk
            self._active_task.status = TaskStatus.GENERATING

    def complete_task(self, task_id: str, final_output: Optional[str] = None, usage: Optional[dict] = None) -> None:
        # Accept completion for tasks that were detached by cancel (kept in _history)
        task = next((t for t in self._history if t.id == task_id), None)
        if task is None:
            return
        if self._active_task and self._active_task.id == task_id:
            self._active_task = None
        if task.status == TaskStatus.CANCELLED:
            # Cancelled task: keep CANCELLED status, just attach final partial output
            if final_output is not None:
                task.latest_output = final_output
            return
        task.status = TaskStatus.COMPLETE
        if final_output is not None:
            task.latest_output = final_output
        if usage:
            task.usage = usage

    def fail_task(self, task_id: str, error: str) -> None:
        task = next((t for t in self._history if t.id == task_id), None)
        if task is None:
            return
        if self._active_task and self._active_task.id == task_id:
            self._active_task = None
        if task.status == TaskStatus.CANCELLED:
            return
        task.status = TaskStatus.ERROR
        task.error = error

    def cancel_active_task(self) -> bool:
        if self._active_task and self._active_task.status in (TaskStatus.CONNECTING, TaskStatus.GENERATING):
            self._active_task.cancel_requested = True
            self._active_task.status = TaskStatus.CANCELLED
            self._active_task = None
            return True
        return False


task_manager = TaskManager()
