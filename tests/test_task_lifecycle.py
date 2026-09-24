"""Tests for AITask lifecycle edge cases: cancel, detached completion, fail."""

import pytest
from services.task_manager import TaskManager, TaskStatus


def test_cancel_then_complete_keeps_cancelled_status():
    mgr = TaskManager()
    task = mgr.create_task(backend="api", provider="openai", mode="api", prompt="hi")
    mgr.update_task_output(task.id, "partial output")
    assert mgr.cancel_active_task() is True
    assert task.status == TaskStatus.CANCELLED

    # Completion arriving after cancel must NOT flip status to COMPLETE
    mgr.complete_task(task.id, final_output="partial output")
    assert task.status == TaskStatus.CANCELLED
    assert task.latest_output == "partial output"


def test_complete_task_detached_from_active():
    mgr = TaskManager()
    task1 = mgr.create_task(backend="api", provider="openai", mode="api", prompt="one")
    task2 = mgr.create_task(backend="api", provider="gemini_api", mode="api", prompt="two")
    # Active is task2; completing task1 (e.g. late fallback completion) must not clear active
    mgr.complete_task(task1.id, final_output="done-1", usage={"prompt_tokens": 5})
    assert mgr.get_active_task() is not None
    assert mgr.get_active_task().id == task2.id
    assert task1.status == TaskStatus.COMPLETE


def test_fail_task_after_cancel_is_noop():
    mgr = TaskManager()
    task = mgr.create_task(backend="api", provider="openai", mode="api", prompt="hi")
    mgr.cancel_active_task()
    mgr.fail_task(task.id, "late error")
    assert task.status == TaskStatus.CANCELLED
    assert task.error is None
