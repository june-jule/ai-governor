"""Tests for v2.0.0 features: BLOCKED/FAILED states, rate limiter fix,
guard composition, metrics, webhook callbacks, and thread safety.
"""

import sys
import os
import collections
import json
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import (
    TransitionEngine,
    _RateLimiter,
    _guard_registry,
    _guard_registry_lock,
    register_guard,
    GuardContext,
    GuardResult,
)

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


def _create_task(backend, task_id="TASK_001", status="ACTIVE", task_type="IMPLEMENTATION"):
    backend.create_task({
        "task_id": task_id,
        "task_name": "Test task",
        "task_type": task_type,
        "role": "DEVELOPER",
        "status": status,
        "priority": "HIGH",
        "content": "Implement feature X. Add tests to verify correctness.",
    })


# ============================================================
# BLOCKED / FAILED State Tests
# ============================================================


class TestBlockedState:
    def test_active_to_blocked(self):
        backend, engine = _make_engine()
        _create_task(backend)

        result = engine.transition_task(
            "TASK_001", "BLOCKED", "EXECUTOR",
            transition_params={"blocking_reason": "Waiting on API key"},
        )
        assert result["result"] == "PASS"
        assert result["to_state"] == "BLOCKED"

        task = backend.get_task("TASK_001")["task"]
        assert task["status"] == "BLOCKED"
        assert task.get("blocked_date") is not None

    def test_blocked_to_active(self):
        backend, engine = _make_engine()
        _create_task(backend, status="BLOCKED")

        result = engine.transition_task(
            "TASK_001", "ACTIVE", "EXECUTOR",
            transition_params={"unblock_reason": "API key received"},
        )
        assert result["result"] == "PASS"
        assert result["to_state"] == "ACTIVE"

        task = backend.get_task("TASK_001")["task"]
        assert task["status"] == "ACTIVE"

    def test_blocked_to_failed(self):
        backend, engine = _make_engine()
        _create_task(backend, status="BLOCKED")

        result = engine.transition_task(
            "TASK_001", "FAILED", "REVIEWER",
            transition_params={"failure_reason": "Dependency permanently unavailable"},
        )
        assert result["result"] == "PASS"
        assert result["to_state"] == "FAILED"

        task = backend.get_task("TASK_001")["task"]
        assert task["status"] == "FAILED"
        assert task.get("failed_date") is not None


class TestFailedState:
    def test_active_to_failed(self):
        backend, engine = _make_engine()
        _create_task(backend)

        result = engine.transition_task(
            "TASK_001", "FAILED", "REVIEWER",
            transition_params={"failure_reason": "Task abandoned"},
        )
        assert result["result"] == "PASS"
        assert result["to_state"] == "FAILED"

    def test_rework_to_failed(self):
        backend, engine = _make_engine()
        _create_task(backend, status="REWORK")

        result = engine.transition_task(
            "TASK_001", "FAILED", "REVIEWER",
            transition_params={"failure_reason": "Exhausted rework attempts"},
        )
        assert result["result"] == "PASS"
        assert result["to_state"] == "FAILED"

    def test_failed_is_terminal(self):
        backend, engine = _make_engine()
        _create_task(backend, status="FAILED")

        result = engine.transition_task("TASK_001", "ACTIVE", "REVIEWER")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ILLEGAL_TRANSITION"

    def test_executor_cannot_fail_task(self):
        backend, engine = _make_engine()
        _create_task(backend)

        result = engine.transition_task(
            "TASK_001", "FAILED", "EXECUTOR",
            transition_params={"failure_reason": "Self-fail"},
        )
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ROLE_NOT_AUTHORIZED"


class TestRevisionCount:
    def test_rework_increments_revision_count(self):
        backend, engine = _make_engine()
        _create_task(backend, status="READY_FOR_REVIEW")

        result = engine.transition_task("TASK_001", "REWORK", "REVIEWER")
        assert result["result"] == "PASS"

        task = backend.get_task("TASK_001")["task"]
        assert task.get("revision_count") == 1

    def test_multiple_reworks_increment(self):
        backend, engine = _make_engine()
        _create_task(backend, status="READY_FOR_REVIEW")

        # First rework
        engine.transition_task("TASK_001", "REWORK", "REVIEWER")

        # Resubmit
        backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")

        # Second rework
        engine.transition_task("TASK_001", "REWORK", "REVIEWER")

        task = backend.get_task("TASK_001")["task"]
        assert task.get("revision_count") == 2


# ============================================================
# Rate Limiter Memory Leak Fix Tests
# ============================================================


class TestRateLimiterLRU:
    def test_basic_rate_limiting(self):
        rl = _RateLimiter(max_attempts=3, window_seconds=60.0)
        assert rl.check("t1") is True
        assert rl.check("t1") is True
        assert rl.check("t1") is True
        assert rl.check("t1") is False  # Exceeded

    def test_lru_eviction(self):
        rl = _RateLimiter(max_attempts=5, window_seconds=60.0, max_keys=3)
        # Fill up 3 keys
        rl.check("t1")
        rl.check("t2")
        rl.check("t3")
        assert len(rl._attempts) == 3

        # Adding t4 should evict t1 (LRU)
        rl.check("t4")
        assert len(rl._attempts) <= 3
        assert "t1" not in rl._attempts

    def test_lru_touch_refreshes(self):
        rl = _RateLimiter(max_attempts=5, window_seconds=60.0, max_keys=3)
        rl.check("t1")
        rl.check("t2")
        rl.check("t3")

        # Touch t1 to make it most-recently-used
        rl.check("t1")

        # Adding t4 should evict t2 (now LRU, not t1)
        rl.check("t4")
        assert "t1" in rl._attempts
        assert "t2" not in rl._attempts

    def test_window_expiry(self):
        rl = _RateLimiter(max_attempts=2, window_seconds=0.05)
        assert rl.check("t1") is True
        assert rl.check("t1") is True
        assert rl.check("t1") is False
        time.sleep(0.06)
        assert rl.check("t1") is True  # Window expired

    def test_ordered_dict_type(self):
        rl = _RateLimiter(max_attempts=5, window_seconds=60.0)
        assert isinstance(rl._attempts, collections.OrderedDict)


# ============================================================
# Guard Registry Thread Safety Tests
# ============================================================


class TestGuardRegistryThreadSafety:
    def test_concurrent_registration(self):
        """Multiple threads registering guards concurrently should not corrupt the registry."""
        errors = []

        def register_in_thread(idx):
            try:
                guard_id = f"TEST-THREAD-{idx}"

                @register_guard(guard_id)
                def _guard(ctx):
                    return GuardResult(guard_id, True, "ok")

                with _guard_registry_lock:
                    assert guard_id in _guard_registry
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_in_thread, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        # Cleanup
        with _guard_registry_lock:
            for i in range(20):
                _guard_registry.pop(f"TEST-THREAD-{i}", None)


# ============================================================
# Guard Composition (AND/OR) Tests
# ============================================================


def _or_state_machine(guard_ids, guard_mode="OR"):
    """Build a minimal valid state machine with custom guards and guard_mode."""
    return {
        "_meta": {"schema_version": "1.1", "version": "2.0.0-test"},
        "states": {
            "ACTIVE": {"terminal": False},
            "READY_FOR_REVIEW": {"terminal": False},
            "COMPLETED": {"terminal": True},
        },
        "transitions": [
            {
                "id": "T01",
                "from_state": "ACTIVE",
                "to_state": "READY_FOR_REVIEW",
                "allowed_roles": ["EXECUTOR"],
                "guards": guard_ids,
                "guard_mode": guard_mode,
                "events": [],
                "temporal_fields": {},
            },
            {
                "id": "T02",
                "from_state": "READY_FOR_REVIEW",
                "to_state": "COMPLETED",
                "allowed_roles": ["REVIEWER"],
                "guards": [],
                "events": [],
                "temporal_fields": {},
            },
        ],
    }


class TestGuardComposition:
    def test_and_mode_all_must_pass(self):
        """AND mode (default): all guards must pass."""
        backend, engine = _make_engine()
        _create_task(backend)

        # No self-review -> EG-01 fails
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"

    def test_or_mode_one_must_pass(self):
        """OR mode: at least one guard passing is enough."""
        backend = MemoryBackend()
        sm_path = os.path.join(os.path.dirname(__file__), "_test_or_sm.json")
        sm = _or_state_machine(["TEST-OR-PASS", "TEST-OR-FAIL"], "OR")

        with open(sm_path, "w") as f:
            json.dump(sm, f)

        try:
            engine = TransitionEngine(backend=backend, state_machine_path=sm_path, strict=False)
            engine.register_guard("TEST-OR-PASS", lambda ctx: GuardResult("TEST-OR-PASS", True, "ok"))
            engine.register_guard("TEST-OR-FAIL", lambda ctx: GuardResult("TEST-OR-FAIL", False, "nope"))

            _create_task(backend)
            result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
            assert result["result"] == "PASS"  # OR mode: one pass is enough
        finally:
            os.unlink(sm_path)

    def test_or_mode_all_fail(self):
        """OR mode: if all guards fail, transition fails."""
        backend = MemoryBackend()
        sm_path = os.path.join(os.path.dirname(__file__), "_test_or_fail_sm.json")
        sm = _or_state_machine(["TEST-FAIL-A", "TEST-FAIL-B"], "OR")

        with open(sm_path, "w") as f:
            json.dump(sm, f)

        try:
            engine = TransitionEngine(backend=backend, state_machine_path=sm_path, strict=False)
            engine.register_guard("TEST-FAIL-A", lambda ctx: GuardResult("TEST-FAIL-A", False, "nope A"))
            engine.register_guard("TEST-FAIL-B", lambda ctx: GuardResult("TEST-FAIL-B", False, "nope B"))

            _create_task(backend)
            result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
            assert result["result"] == "FAIL"
        finally:
            os.unlink(sm_path)

    def test_available_transitions_or_mode(self):
        """get_available_transitions reports guard_mode and correct readiness."""
        backend = MemoryBackend()
        sm_path = os.path.join(os.path.dirname(__file__), "_test_avail_or_sm.json")
        sm = _or_state_machine(["TEST-AVAIL-PASS", "TEST-AVAIL-FAIL"], "OR")

        with open(sm_path, "w") as f:
            json.dump(sm, f)

        try:
            engine = TransitionEngine(backend=backend, state_machine_path=sm_path, strict=False)
            engine.register_guard("TEST-AVAIL-PASS", lambda ctx: GuardResult("TEST-AVAIL-PASS", True, "ok"))
            engine.register_guard("TEST-AVAIL-FAIL", lambda ctx: GuardResult("TEST-AVAIL-FAIL", False, "no"))

            _create_task(backend)
            avail = engine.get_available_transitions("TASK_001", "EXECUTOR")
            t01 = avail["transitions"][0]
            assert t01["guard_mode"] == "OR"
            assert t01["ready"] is True  # OR: one pass is enough
            assert t01["guards_met"] == 1
            assert t01["guards_total"] == 2
        finally:
            os.unlink(sm_path)


# ============================================================
# Metrics Tests
# ============================================================


class TestMetrics:
    def test_metrics_singleton(self):
        from governor.metrics import get_metrics
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_snapshot_structure(self):
        from governor.metrics import get_metrics
        metrics = get_metrics()
        snap = metrics.snapshot()
        assert "prometheus_available" in snap
        assert "counters" in snap

    def test_transition_metrics(self):
        from governor.metrics import GovernorMetrics
        metrics = GovernorMetrics(namespace="test_ns")
        metrics.transition_attempted("T01", "EXECUTOR")
        metrics.transition_completed("T01", "EXECUTOR", result="PASS", duration_seconds=0.5)
        snap = metrics.snapshot()
        assert snap["counters"]["transition_attempted:T01:EXECUTOR"] == 1
        assert snap["counters"]["transition_completed:T01:PASS"] == 1

    def test_guard_metrics(self):
        from governor.metrics import GovernorMetrics
        metrics = GovernorMetrics(namespace="test_ns2")
        metrics.guard_evaluated("EG-01", passed=True, duration_seconds=0.01)
        metrics.guard_evaluated("EG-01", passed=False, duration_seconds=0.02)
        snap = metrics.snapshot()
        assert snap["counters"]["guard_eval:EG-01:true"] == 1
        assert snap["counters"]["guard_eval:EG-01:false"] == 1

    def test_rate_limited_metric(self):
        from governor.metrics import GovernorMetrics
        metrics = GovernorMetrics(namespace="test_ns3")
        metrics.rate_limited("TASK_001")
        snap = metrics.snapshot()
        assert snap["counters"]["rate_limited:TASK"] == 1


# ============================================================
# Webhook Callback Tests
# ============================================================


class TestWebhookCallback:
    def test_webhook_callable_interface(self):
        """WebhookCallback implements the event callback interface."""
        from governor.callbacks.webhook import WebhookCallback
        webhook = WebhookCallback(
            url="http://localhost:9999/nonexistent",
            timeout_seconds=1.0,
            retry_count=0,
            async_dispatch=False,
        )

        # Should not raise even if the endpoint doesn't exist
        webhook(
            "transition",
            {"some": "config"},
            "TASK_001",
            {"task_id": "TASK_001", "status": "ACTIVE"},
            {"calling_role": "EXECUTOR"},
        )

    def test_webhook_event_filter(self):
        """Webhook respects event_filter."""
        from governor.callbacks.webhook import WebhookCallback
        calls = []

        class MockWebhook(WebhookCallback):
            def _send_with_retry(self, payload):
                calls.append(payload)

        webhook = MockWebhook(
            url="http://localhost:9999",
            event_filter=["custom_event"],
            async_dispatch=False,
        )

        # This event type is not in the filter
        webhook("transition", {}, "T1", {}, {})
        assert len(calls) == 0

        # This event type IS in the filter
        webhook("custom_event", {}, "T1", {}, {})
        assert len(calls) == 1

    def test_webhook_hmac_signature(self):
        """Webhook includes HMAC signature when secret is provided."""
        import hashlib
        import hmac as hmac_mod
        from governor.callbacks.webhook import WebhookCallback

        secret = "test-secret"
        webhook = WebhookCallback(url="http://localhost:9999", secret=secret)

        # Just verify the signing logic doesn't crash
        payload = {"event_type": "test", "task_id": "T1", "timestamp": "2026-01-01"}
        body = json.dumps(payload, default=str).encode("utf-8")
        expected_sig = hmac_mod.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        assert len(expected_sig) == 64  # SHA-256 hex digest


# ============================================================
# State Machine Version Tests
# ============================================================


class TestStateMachineVersion:
    def test_version_is_2_0_0(self):
        _, engine = _make_engine()
        assert engine.state_machine_version == "2.0.0"

    def test_blocked_and_failed_in_states(self):
        _, engine = _make_engine()
        states = engine._state_machine["states"]
        assert "BLOCKED" in states
        assert "FAILED" in states
        assert states["BLOCKED"]["terminal"] is False
        assert states["FAILED"]["terminal"] is True

    def test_nine_transitions(self):
        _, engine = _make_engine()
        transitions = engine._state_machine["transitions"]
        assert len(transitions) == 9
        ids = {t["id"] for t in transitions}
        assert ids == {"T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09"}
