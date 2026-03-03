"""Tests for the core transition engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine

# Import guards so they register
import governor.guards.executor_guards  # noqa: F401


def _make_engine():
    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEV": "EXECUTOR", "DEVELOPER": "EXECUTOR"},
    )
    return backend, engine


def _create_active_task(backend, task_id="TASK_001"):
    backend.create_task({
        "task_id": task_id,
        "task_name": "Test task",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Implement feature X. Add tests to verify correctness.",
    })


class TestTransitionTask:
    def test_eg05_blocks_secret_content(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        backend.add_report("TASK_001", {"report_id": "RP1", "report_type": "IMPLEMENTATION"})
        backend.update_task("TASK_001", {"content": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"})

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")
        assert result["result"] == "FAIL"
        failed_ids = {g["guard_id"] for g in result["guard_results"] if not g["passed"]}
        assert "EG-05" in failed_ids

    def test_submit_active_task(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {
            "review_id": "R1",
            "review_type": "SELF_REVIEW",
            "rating": 8.0,
        })

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")
        assert result["result"] == "PASS"
        assert result["from_state"] == "ACTIVE"
        assert result["to_state"] == "READY_FOR_REVIEW"

        data = backend.get_task("TASK_001")
        assert data["task"]["status"] == "READY_FOR_REVIEW"

    def test_dry_run_does_not_change_state(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {
            "review_id": "R1",
            "review_type": "SELF_REVIEW",
            "rating": 8.0,
        })

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER", dry_run=True)
        assert result["result"] == "PASS"
        assert result["dry_run"] is True

        data = backend.get_task("TASK_001")
        assert data["task"]["status"] == "ACTIVE"  # Not changed

    def test_illegal_transition(self):
        backend, engine = _make_engine()
        _create_active_task(backend)

        result = engine.transition_task("TASK_001", "COMPLETED", "REVIEWER")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ILLEGAL_TRANSITION"

    def test_role_not_authorized(self):
        backend, engine = _make_engine()
        _create_active_task(backend)

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "REVIEWER")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ROLE_NOT_AUTHORIZED"

    def test_lowercase_role_is_normalized(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "executor")
        assert result["result"] == "PASS"

    def test_lowercase_target_state_is_normalized(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        backend.add_report("TASK_001", {"report_id": "RP1", "report_type": "IMPLEMENTATION"})
        result = engine.transition_task("TASK_001", "ready_for_review", "EXECUTOR")
        assert result["result"] == "PASS"

    def test_task_not_found(self):
        _, engine = _make_engine()
        result = engine.transition_task("NONEXISTENT", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "TASK_NOT_FOUND"

    def test_full_lifecycle(self):
        backend, engine = _make_engine()
        _create_active_task(backend)

        # Add self-review for EG-01
        backend.add_review("TASK_001", {
            "review_id": "REV_001",
            "review_type": "SELF_REVIEW",
            "rating": 8.0,
        })

        # Submit (ACTIVE -> READY_FOR_REVIEW)
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")
        assert result["result"] == "PASS"

        # Reviewer approves (READY_FOR_REVIEW -> COMPLETED)
        result = engine.transition_task("TASK_001", "COMPLETED", "REVIEWER")
        assert result["result"] == "PASS"

        data = backend.get_task("TASK_001")
        assert data["task"]["status"] == "COMPLETED"

    def test_rework_cycle(self):
        backend, engine = _make_engine()
        _create_active_task(backend)

        # Add self-review and submit
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")

        # Reviewer sends back for rework (T03)
        result = engine.transition_task("TASK_001", "REWORK", "REVIEWER")
        assert result["result"] == "PASS"

        data = backend.get_task("TASK_001")
        assert data["task"]["status"] == "REWORK"

        # Executor resubmits (T04)
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")
        assert result["result"] == "PASS"

        # Reviewer approves
        result = engine.transition_task("TASK_001", "COMPLETED", "REVIEWER")
        assert result["result"] == "PASS"

    def test_submitted_date_set_on_submit(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")
        assert "submitted_date" in result["temporal_updates"]

    def test_completed_date_set_on_complete(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "DEVELOPER")

        result = engine.transition_task("TASK_001", "COMPLETED", "REVIEWER")
        assert "completed_date" in result["temporal_updates"]

    def test_returns_state_conflict_when_expected_status_mismatch(self):
        class ConflictBackend(MemoryBackend):
            def update_task(self, task_id, updates, expected_current_status=None):
                return {
                    "success": False,
                    "error_code": "STATE_CONFLICT",
                    "actual_current_status": "REWORK",
                }

        backend = ConflictBackend()
        engine = TransitionEngine(backend=backend)
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        backend.add_report("TASK_001", {"report_id": "RP1", "report_type": "IMPLEMENTATION"})

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "STATE_CONFLICT"

    def test_event_callback_receives_updated_task_state(self):
        seen_statuses = []

        def cb(_event_type, _config, _task_id, task, _transition_params):
            seen_statuses.append(task.get("status"))

        custom_sm = {
            "states": {"ACTIVE": {"terminal": False}, "DONE": {"terminal": True}},
            "transitions": [
                {
                    "id": "T01",
                    "from_state": "ACTIVE",
                    "to_state": "DONE",
                    "allowed_roles": ["EXECUTOR"],
                    "guards": [],
                    "events": [{"event_id": "E1", "type": "custom", "config": {}}],
                }
            ],
        }

        import tempfile
        import json

        backend = MemoryBackend()
        backend.create_task(
            {
                "task_id": "TASK_EVENT_001",
                "task_name": "Event task",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Test content.",
            }
        )

        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(custom_sm, f)
            engine = TransitionEngine(backend=backend, state_machine_path=path, event_callbacks=[cb])
            result = engine.transition_task("TASK_EVENT_001", "DONE", "EXECUTOR")
            assert result["result"] == "PASS"
            assert seen_statuses == ["DONE"]
        finally:
            os.unlink(path)

    def test_inline_property_set_allows_falsy_values(self):
        custom_sm = {
            "states": {"ACTIVE": {"terminal": False}, "DONE": {"terminal": True}},
            "transitions": [
                {
                    "id": "T01",
                    "from_state": "ACTIVE",
                    "to_state": "DONE",
                    "allowed_roles": ["EXECUTOR"],
                    "guards": [{"guard_id": "G_BOOL", "check": "property_set(approved)"}],
                    "events": [],
                }
            ],
        }

        import tempfile
        import json

        backend = MemoryBackend()
        backend.create_task(
            {
                "task_id": "TASK_BOOL_001",
                "task_name": "Bool test",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Test content.",
            }
        )

        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(custom_sm, f)
            engine = TransitionEngine(backend=backend, state_machine_path=path)
            result = engine.transition_task(
                "TASK_BOOL_001",
                "DONE",
                "EXECUTOR",
                transition_params={"approved": False},
            )
            assert result["result"] == "PASS"
        finally:
            os.unlink(path)


class TestGetAvailableTransitions:
    def test_active_task_transitions(self):
        backend, engine = _make_engine()
        _create_active_task(backend)

        available = engine.get_available_transitions("TASK_001", "DEVELOPER")
        assert available["current_state"] == "ACTIVE"
        targets = {t["target_state"] for t in available["transitions"]}
        assert "READY_FOR_REVIEW" in targets

    def test_task_not_found(self):
        _, engine = _make_engine()
        result = engine.get_available_transitions("NONEXISTENT", "EXECUTOR")
        assert "error" in result

    def test_ready_indicates_guard_status(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})

        available = engine.get_available_transitions("TASK_001", "DEVELOPER")
        submit_transition = next(
            t for t in available["transitions"] if t["target_state"] == "READY_FOR_REVIEW"
        )
        assert submit_transition["ready"] is True
        assert submit_transition["role_authorized"] is True

    def test_available_transitions_exposes_non_blocking_guard_warnings(self):
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        # No report on IMPLEMENTATION should produce EG-02 warning.

        available = engine.get_available_transitions("TASK_001", "DEVELOPER")
        submit_transition = next(
            t for t in available["transitions"] if t["target_state"] == "READY_FOR_REVIEW"
        )
        assert submit_transition["ready"] is True
        assert submit_transition["warnings_count"] >= 1
        warning_ids = {w["guard_id"] for w in submit_transition["guard_warnings"]}
        assert "EG-02" in warning_ids

    def test_executor_sees_submission_transition(self):
        backend, engine = _make_engine()
        _create_active_task(backend)

        available = engine.get_available_transitions("TASK_001", "DEVELOPER")
        targets = {t["target_state"] for t in available["transitions"]}
        assert "READY_FOR_REVIEW" in targets

    def test_current_state_is_normalized_for_transition_lookup(self):
        class LowercaseStatusBackend(MemoryBackend):
            def get_task(self, task_id: str):
                data = super().get_task(task_id)
                data["task"]["status"] = str(data["task"].get("status") or "").lower()
                return data

        backend = LowercaseStatusBackend()
        backend.create_task(
            {
                "task_id": "TASK_CASE_001",
                "task_name": "Case test",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Implement feature X. Add tests to verify correctness.",
            }
        )
        engine = TransitionEngine(backend=backend, role_aliases={"DEVELOPER": "EXECUTOR"})

        available = engine.get_available_transitions("TASK_CASE_001", "DEVELOPER")
        assert available["current_state"] == "ACTIVE"
        targets = {t["target_state"] for t in available["transitions"]}
        assert "READY_FOR_REVIEW" in targets


class TestNormalizeState:
    """Tests for _normalize_state edge cases (Bug 3)."""

    def test_normalize_state_with_none(self):
        from governor.engine.transition_engine import _normalize_state
        assert _normalize_state(None) == ""

    def test_normalize_state_with_zero(self):
        from governor.engine.transition_engine import _normalize_state
        assert _normalize_state(0) == "0"

    def test_normalize_state_with_false(self):
        from governor.engine.transition_engine import _normalize_state
        assert _normalize_state(False) == "FALSE"

    def test_normalize_state_with_empty_string(self):
        from governor.engine.transition_engine import _normalize_state
        assert _normalize_state("") == ""

    def test_normalize_state_with_lowercase(self):
        from governor.engine.transition_engine import _normalize_state
        assert _normalize_state("active") == "ACTIVE"


class TestCallbackReloadFailure:
    """Tests that callback reload failure is logged, not silent (Bug 2)."""

    def test_transition_succeeds_when_post_reload_fails(self):
        """Transition should succeed even if post-transition task reload fails."""

        class ReloadFailBackend(MemoryBackend):
            def __init__(self):
                super().__init__()
                self._get_count = 0

            def get_task(self, task_id):
                self._get_count += 1
                if self._get_count > 1:
                    raise RuntimeError("simulated reload failure")
                return super().get_task(task_id)

        backend = ReloadFailBackend()
        backend.create_task({
            "task_id": "TASK_RELOAD_001",
            "task_name": "Reload test",
            "task_type": "IMPLEMENTATION",
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "Implement feature. Tests verify correctness.",
        })
        backend.add_review("TASK_RELOAD_001", {"review_type": "SELF_REVIEW", "rating": 8.0})
        backend.add_report("TASK_RELOAD_001", {"report_type": "IMPLEMENTATION", "content": "Done."})

        engine = TransitionEngine(backend=backend, role_aliases={"DEVELOPER": "EXECUTOR"})
        result = engine.transition_task("TASK_RELOAD_001", "READY_FOR_REVIEW", "DEVELOPER")
        assert result["result"] == "PASS"
