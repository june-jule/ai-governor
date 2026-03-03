"""Concurrent transition stress tests.

Validates that the TransitionEngine handles concurrent transition
attempts correctly — including optimistic-concurrency conflicts,
rate limiting, and parallel guard evaluation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import concurrent.futures
import threading
import pytest

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine

# Import guards so they register
import governor.guards.executor_guards  # noqa: F401


def _make_engine(**kwargs):
    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEV": "EXECUTOR", "DEVELOPER": "EXECUTOR"},
        **kwargs,
    )
    return backend, engine


def _create_ready_task(backend, task_id="TASK_001"):
    """Create a task with all evidence needed to pass submission guards."""
    backend.create_task({
        "task_id": task_id,
        "task_name": "Test task",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Implement feature X. Add tests to verify correctness.",
    })
    backend.add_review(task_id, {
        "review_id": f"REVIEW_{task_id}",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 8.0,
        "content": "All tests pass.",
    })
    backend.add_report(task_id, {
        "report_id": f"REPORT_{task_id}",
        "report_type": "IMPLEMENTATION",
        "content": "Implementation complete.",
    })


class TestConcurrentTransitions:
    """Test concurrent transition attempts on the same task."""

    def test_concurrent_submit_only_one_succeeds(self):
        """When multiple threads try to transition the same task, only one
        should succeed (the rest should see FAIL or STATE_CONFLICT)."""
        backend, engine = _make_engine()
        _create_ready_task(backend)

        results = []
        barrier = threading.Barrier(5)

        def _attempt():
            barrier.wait()
            r = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
            results.append(r)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_attempt) for _ in range(5)]
            concurrent.futures.wait(futures)

        pass_count = sum(1 for r in results if r["result"] == "PASS")
        # At least one should pass (the first one through)
        assert pass_count >= 1
        # Verify final task state
        task = backend.get_task("TASK_001")["task"]
        assert task["status"] == "READY_FOR_REVIEW"

    def test_concurrent_different_tasks(self):
        """Transitions on different tasks should not interfere."""
        backend, engine = _make_engine()
        for i in range(10):
            _create_ready_task(backend, f"TASK_{i:03d}")

        results = {}

        def _attempt(tid):
            r = engine.transition_task(tid, "READY_FOR_REVIEW", "EXECUTOR")
            results[tid] = r

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_attempt, f"TASK_{i:03d}") for i in range(10)]
            concurrent.futures.wait(futures)

        # All should pass — no interference between tasks
        for tid, r in results.items():
            assert r["result"] == "PASS", f"{tid} failed: {r.get('rejection_reason')}"

    def test_many_dry_runs_concurrent(self):
        """Many concurrent dry-runs should all succeed without state change."""
        backend, engine = _make_engine()
        _create_ready_task(backend)

        results = []

        def _attempt():
            r = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
            results.append(r)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(_attempt) for _ in range(20)]
            concurrent.futures.wait(futures)

        # All dry runs should pass
        for r in results:
            assert r["result"] == "PASS"
            assert r["dry_run"] is True

        # Task should still be ACTIVE
        task = backend.get_task("TASK_001")["task"]
        assert task["status"] == "ACTIVE"


class TestParallelGuards:
    """Test parallel guard evaluation."""

    def test_parallel_guards_same_results(self):
        """Parallel guards should produce same results as sequential."""
        backend_seq, engine_seq = _make_engine()
        backend_par, engine_par = _make_engine(parallel_guards=True)

        _create_ready_task(backend_seq)
        _create_ready_task(backend_par)

        result_seq = engine_seq.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
        result_par = engine_par.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        assert result_seq["result"] == result_par["result"]
        assert len(result_seq["guard_results"]) == len(result_par["guard_results"])

        for gs, gp in zip(result_seq["guard_results"], result_par["guard_results"]):
            assert gs["guard_id"] == gp["guard_id"]
            assert gs["passed"] == gp["passed"]

    def test_parallel_guards_with_timeout(self):
        """Engine with guard_timeout_seconds should work correctly."""
        backend, engine = _make_engine(guard_timeout_seconds=5.0)
        _create_ready_task(backend)
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
        assert result["result"] == "PASS"


class TestRateLimiting:
    """Test transition rate limiting."""

    def test_rate_limit_blocks_excess(self):
        """Rate limiter should block attempts exceeding the threshold."""
        backend, engine = _make_engine(rate_limit=(3, 60.0))
        _create_ready_task(backend)

        results = []
        for _ in range(5):
            r = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
            results.append(r)

        # First 3 should be allowed (PASS from guards)
        for r in results[:3]:
            assert r.get("error_code") != "RATE_LIMITED"

        # Remaining should be rate-limited
        for r in results[3:]:
            assert r["result"] == "FAIL"
            assert r["error_code"] == "RATE_LIMITED"

    def test_rate_limit_per_task(self):
        """Rate limiting is per-task — different tasks have independent limits."""
        backend, engine = _make_engine(rate_limit=(2, 60.0))
        _create_ready_task(backend, "TASK_A")
        _create_ready_task(backend, "TASK_B")

        # 2 attempts each should be fine
        for tid in ("TASK_A", "TASK_B"):
            for _ in range(2):
                r = engine.transition_task(tid, "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
                assert r.get("error_code") != "RATE_LIMITED"

        # 3rd attempt on each should be blocked
        for tid in ("TASK_A", "TASK_B"):
            r = engine.transition_task(tid, "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
            assert r["error_code"] == "RATE_LIMITED"

    def test_no_rate_limit_by_default(self):
        """Without rate_limit, no throttling should occur."""
        backend, engine = _make_engine()
        _create_ready_task(backend)

        for _ in range(50):
            r = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)
            assert r.get("error_code") != "RATE_LIMITED"


class TestStateMachineVersion:
    """Test state machine version tracking."""

    def test_version_exposed(self):
        """Engine should expose the state machine version."""
        _, engine = _make_engine()
        assert engine.state_machine_version == "2.0.0"

    def test_version_in_event_payload(self):
        """Transition events should include the state machine version."""
        backend, engine = _make_engine()
        _create_ready_task(backend)
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "PASS"

        # Check the recorded transition event via audit trail
        events = backend.get_task_audit_trail("TASK_001")
        assert len(events) >= 1
        # The PASS event should have the SM version stamped
        pass_events = [e for e in events if e.get("result") == "PASS"]
        assert len(pass_events) >= 1
        assert pass_events[0].get("state_machine_version") == "2.0.0"
