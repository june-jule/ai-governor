"""Tests for error boundaries — malformed inputs, guard exceptions, strict mode."""

import json
import os
import tempfile

import pytest

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import (
    GuardContext,
    GuardResult,
    TransitionEngine,
    register_guard,
)
from governor.engine import transition_engine as te


def _write_sm(sm_dict):
    """Write a state machine dict to a temp file and return path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(sm_dict, f)
    return path


def _valid_sm():
    return {
        "states": {
            "ACTIVE": {"terminal": False},
            "DONE": {"terminal": True},
        },
        "transitions": [
            {"id": "T01", "from_state": "ACTIVE", "to_state": "DONE",
             "allowed_roles": ["EXECUTOR"], "guards": []},
        ],
    }


class TestErrorBoundaries:

    def test_invalid_state_machine_missing_states(self):
        path = _write_sm({"transitions": []})
        try:
            with pytest.raises(ValueError, match="Invalid state machine"):
                TransitionEngine(backend=MemoryBackend(), state_machine_path=path)
        finally:
            os.unlink(path)

    def test_invalid_state_machine_no_terminal(self):
        sm = {
            "states": {"A": {"terminal": False}},
            "transitions": [{"id": "T01", "from_state": "A", "to_state": "A",
                             "allowed_roles": ["X"], "guards": []}],
        }
        path = _write_sm(sm)
        try:
            with pytest.raises(ValueError, match="Invalid state machine"):
                TransitionEngine(backend=MemoryBackend(), state_machine_path=path)
        finally:
            os.unlink(path)

    def test_strict_mode_rejects_unregistered_guard(self):
        """strict=True surfaces unregistered guards at init time, not at transition time."""
        sm = _valid_sm()
        sm["transitions"][0]["guards"] = ["NONEXISTENT_GUARD"]
        path = _write_sm(sm)
        try:
            backend = MemoryBackend()
            with pytest.raises(ValueError, match="strict=True.*NONEXISTENT_GUARD"):
                TransitionEngine(backend=backend, state_machine_path=path, strict=True)
        finally:
            os.unlink(path)

    def test_non_strict_mode_allows_unregistered_guard(self):
        sm = _valid_sm()
        sm["transitions"][0]["guards"] = ["NONEXISTENT_GUARD"]
        path = _write_sm(sm)
        try:
            backend = MemoryBackend()
            backend.create_task({"task_id": "T1", "status": "ACTIVE",
                                 "task_type": "IMPLEMENTATION", "role": "DEV",
                                 "priority": "HIGH", "content": "test"})
            engine = TransitionEngine(backend=backend, state_machine_path=path, strict=False)
            result = engine.transition_task("T1", "DONE", "EXECUTOR")
            assert result["result"] == "PASS"
        finally:
            os.unlink(path)

    def test_guard_exception_caught_as_fail(self):
        @register_guard("TEST_EXPLODING")
        def _exploding(ctx: GuardContext) -> GuardResult:
            raise RuntimeError("Kaboom!")

        sm = _valid_sm()
        sm["transitions"][0]["guards"] = ["TEST_EXPLODING"]
        path = _write_sm(sm)
        try:
            backend = MemoryBackend()
            backend.create_task({"task_id": "T1", "status": "ACTIVE",
                                 "task_type": "IMPLEMENTATION", "role": "DEV",
                                 "priority": "HIGH", "content": "test"})
            engine = TransitionEngine(backend=backend, state_machine_path=path)
            result = engine.transition_task("T1", "DONE", "EXECUTOR")
            assert result["result"] == "FAIL"
            assert any("Kaboom" in gr["reason"] for gr in result["guard_results"])
        finally:
            os.unlink(path)

    def test_transition_on_nonexistent_task(self):
        sm = _valid_sm()
        path = _write_sm(sm)
        try:
            engine = TransitionEngine(backend=MemoryBackend(), state_machine_path=path)
            result = engine.transition_task("GHOST_TASK", "DONE", "EXECUTOR")
            assert result["result"] == "FAIL"
            assert result["error_code"] == "TASK_NOT_FOUND"
        finally:
            os.unlink(path)

    def test_illegal_transition_returns_fail(self):
        sm = _valid_sm()
        path = _write_sm(sm)
        try:
            backend = MemoryBackend()
            backend.create_task({"task_id": "T1", "status": "DONE",
                                 "task_type": "IMPLEMENTATION", "role": "DEV",
                                 "priority": "HIGH", "content": "test"}, strict=False)
            engine = TransitionEngine(backend=backend, state_machine_path=path)
            result = engine.transition_task("T1", "ACTIVE", "EXECUTOR")
            assert result["result"] == "FAIL"
            assert result["error_code"] == "ILLEGAL_TRANSITION"
        finally:
            os.unlink(path)

    def test_unauthorized_role_returns_fail(self):
        sm = _valid_sm()
        path = _write_sm(sm)
        try:
            backend = MemoryBackend()
            backend.create_task({"task_id": "T1", "status": "ACTIVE",
                                 "task_type": "IMPLEMENTATION", "role": "DEV",
                                 "priority": "HIGH", "content": "test"})
            engine = TransitionEngine(backend=backend, state_machine_path=path)
            result = engine.transition_task("T1", "DONE", "NOBODY")
            assert result["result"] == "FAIL"
            assert result["error_code"] == "ROLE_NOT_AUTHORIZED"
        finally:
            os.unlink(path)

    def test_builtin_eg_guards_auto_bootstrap(self):
        snapshot = dict(te._guard_registry)
        try:
            te._guard_registry.clear()
            engine = TransitionEngine(backend=MemoryBackend())
            assert "EG-01" in te._guard_registry

            backend = MemoryBackend()
            backend.create_task(
                {
                    "task_id": "T_BOOTSTRAP",
                    "task_name": "Bootstrap test",
                    "task_type": "IMPLEMENTATION",
                    "role": "DEVELOPER",
                    "status": "ACTIVE",
                    "priority": "HIGH",
                    "content": "Run tests to verify behavior.",
                }
            )
            backend.add_review("T_BOOTSTRAP", {"review_type": "SELF_REVIEW", "rating": 8.0})
            backend.add_report("T_BOOTSTRAP", {"report_type": "IMPLEMENTATION", "content": "Done."})
            engine = TransitionEngine(backend=backend)
            result = engine.transition_task("T_BOOTSTRAP", "READY_FOR_REVIEW", "EXECUTOR")
            assert result["result"] == "PASS"
        finally:
            te._guard_registry.clear()
            te._guard_registry.update(snapshot)

    def test_builtin_guard_autoload_does_not_clobber_user_override(self):
        snapshot = dict(te._guard_registry)
        try:
            te._guard_registry.clear()

            @register_guard("EG-01")
            def _override_eg01(_ctx: GuardContext) -> GuardResult:
                return GuardResult("EG-01", False, "Override EG-01 always fails")

            backend = MemoryBackend()
            backend.create_task(
                {
                    "task_id": "T_OVERRIDE",
                    "task_name": "Override test",
                    "task_type": "IMPLEMENTATION",
                    "role": "DEVELOPER",
                    "status": "ACTIVE",
                    "priority": "HIGH",
                    "content": "Run tests to verify behavior.",
                }
            )
            backend.add_review("T_OVERRIDE", {"review_type": "SELF_REVIEW", "rating": 8.0})
            backend.add_report("T_OVERRIDE", {"report_type": "IMPLEMENTATION", "content": "Done."})

            # Engine init will auto-load built-in EG guard module because EG-02.. are missing.
            engine = TransitionEngine(backend=backend)
            result = engine.transition_task("T_OVERRIDE", "READY_FOR_REVIEW", "EXECUTOR")
            assert result["result"] == "FAIL"
            assert result["rejection_reason"] == "Override EG-01 always fails"
            assert any(gr["guard_id"] == "EG-01" and gr["passed"] is False for gr in result["guard_results"])
        finally:
            te._guard_registry.clear()
            te._guard_registry.update(snapshot)

    def test_backend_read_error_is_normalized(self):
        class BrokenBackend(MemoryBackend):
            def get_task(self, task_id: str):
                raise RuntimeError("driver timeout")

        engine = TransitionEngine(backend=BrokenBackend())
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "BACKEND_ERROR"

        available = engine.get_available_transitions("TASK_001", "EXECUTOR")
        assert available["error"] == "BACKEND_ERROR"

    def test_atomic_apply_event_write_failure_returns_fail(self):
        class EventFailBackend(MemoryBackend):
            def apply_transition(self, task_id, updates, event, expected_current_status=None):
                return {"success": False, "error_code": "EVENT_WRITE_FAILED"}

        backend = EventFailBackend()
        backend.create_task(
            {
                "task_id": "TASK_001",
                "task_name": "Atomic test",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Run tests to verify behavior.",
            }
        )
        backend.add_review("TASK_001", {"review_type": "SELF_REVIEW"})
        backend.add_report("TASK_001", {"report_type": "IMPLEMENTATION", "content": "Done."})

        engine = TransitionEngine(backend=backend)
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "EVENT_WRITE_FAILED"

    def test_default_apply_transition_rolls_back_updates_on_event_failure(self):
        class EventFailRollbackBackend(MemoryBackend):
            def record_transition_event(self, event):
                return {"success": False, "error_code": "EVENT_WRITE_FAILED"}

        backend = EventFailRollbackBackend()
        backend.create_task(
            {
                "task_id": "TASK_ROLLBACK",
                "task_name": "Rollback test",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Run tests to verify behavior.",
            }
        )
        backend.add_review("TASK_ROLLBACK", {"review_type": "SELF_REVIEW"})
        backend.add_report("TASK_ROLLBACK", {"report_type": "IMPLEMENTATION", "content": "Done."})

        engine = TransitionEngine(backend=backend)
        result = engine.transition_task("TASK_ROLLBACK", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "EVENT_WRITE_FAILED"

        task = backend.get_task("TASK_ROLLBACK")["task"]
        assert task["status"] == "ACTIVE"
