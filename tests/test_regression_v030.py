"""Regression tests for v0.3.0 bug fixes (15 bugs across 3 review rounds).

Bug 1A: Failed transition audit persistence  (transition_engine.py)
Bug 1B: Path traversal in EG-03              (executor_guards.py)
Bug 1C: GDS graph name collision             (graph_algorithms.py)
Bug 2A: Guard timeout / close()              (transition_engine.py)
Bug 2B: WriteConflict retry                  (neo4j_backend.py)
Bug 2C: Secret detection                     (executor_guards.py)
Bug 2D: ensure_schema error reporting        (neo4j_backend.py)
Bug 2E: GuardResult type validation          (transition_engine.py)
Bug 2F: Event callback error tracking        (transition_engine.py)
Bug 2G: Rate limiter capacity                (transition_engine.py)
Bug 2H: Relationship truncation metadata     (neo4j_backend.py)
Bug 2I: Regex DoS in deliverables            (executor_guards.py)
"""

import json
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from governor.engine.transition_engine import (
    TransitionEngine,
    GuardResult,
    GuardContext,
    _RateLimiter,
)
from governor.backend.memory_backend import MemoryBackend
from governor.guards.executor_guards import (
    guard_no_secrets_in_content,
    guard_deliverables_exist,
    _parse_deliverables_from_content,
)
from governor.analytics.graph_algorithms import GovernorAnalytics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(**kwargs):
    """Create a MemoryBackend + TransitionEngine pair with standard aliases."""
    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEV": "EXECUTOR", "DEVELOPER": "EXECUTOR"},
        **kwargs,
    )
    return backend, engine


def _create_active_task(backend, task_id="TASK_001", task_type="IMPLEMENTATION"):
    """Create an ACTIVE task with content referencing tests (passes EG-08)."""
    backend.create_task({
        "task_id": task_id,
        "task_name": "Test task",
        "task_type": task_type,
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Implement feature X. Add tests to verify correctness.",
    })


def _make_custom_sm(guards=None, events=None):
    """Create a minimal custom state machine JSON file.

    Returns the file path. Caller must unlink after use.
    """
    sm = {
        "_meta": {"version": "test-v030"},
        "states": {
            "ACTIVE": {"terminal": False},
            "DONE": {"terminal": True},
        },
        "transitions": [
            {
                "id": "T01",
                "from_state": "ACTIVE",
                "to_state": "DONE",
                "allowed_roles": ["EXECUTOR"],
                "guards": guards or [],
                "events": events or [],
            },
        ],
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(sm, f)
    return path


def _make_guard_context(content="", task_type="IMPLEMENTATION", task_extra=None,
                        relationships=None, transition_params=None):
    """Build a GuardContext from minimal arguments."""
    task = {
        "task_id": "TASK_CTX",
        "task_type": task_type,
        "status": "ACTIVE",
        "role": "DEVELOPER",
        "content": content,
        **(task_extra or {}),
    }
    task_data = {
        "task": task,
        "relationships": relationships or [],
    }
    return GuardContext(
        task_id="TASK_CTX",
        task_data=task_data,
        transition_params=transition_params or {},
    )


# ---------------------------------------------------------------------------
# Neo4j Backend Mock Helpers (following tests/test_neo4j_backend_mock.py)
# ---------------------------------------------------------------------------


def _make_neo4j_backend(mock_driver):
    """Create a Neo4jBackend with a mocked driver."""
    with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
        mock_gdb.driver.return_value = mock_driver
        from governor.backend.neo4j_backend import Neo4jBackend
        backend = Neo4jBackend(uri="neo4j://mock:7687", user="neo4j", password="test")
    return backend


def _mock_driver(records=None):
    """Create a mock driver that returns given records.

    Returns (mock_driver, mock_session, mock_tx).
    """
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter(records or [])
    mock_tx.run.return_value = mock_result
    mock_session.execute_read.side_effect = lambda fn, **kw: fn(mock_tx)
    mock_session.execute_write.side_effect = lambda fn, **kw: fn(mock_tx)
    mock_session.__enter__ = lambda self: self
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session, mock_tx


# =========================================================================
# Bug 1A: Failed transition audit persistence
# =========================================================================


class TestBug1A_FailedTransitionAuditPersistence:
    """Verify that record_transition_event is called even when guards FAIL,
    and that audit_trail_error surfaces when the backend raises.
    """

    def test_record_transition_event_called_on_guard_failure(self):
        """When guards fail, the engine should persist the FAIL event."""
        backend, engine = _make_engine()
        _create_active_task(backend)
        # No self-review => EG-01 will fail

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"

        # The MemoryBackend stores transition events; check that a FAIL event
        # was recorded for this task.
        trail = backend.get_task_audit_trail("TASK_001")
        fail_events = [e for e in trail if e.get("result") == "FAIL"]
        assert len(fail_events) >= 1, (
            "Expected at least one FAIL audit event; backend should persist "
            "transition events even when guards reject the transition."
        )

    def test_audit_trail_error_surfaces_when_backend_raises(self):
        """When record_transition_event raises, response should include
        audit_trail_error instead of crashing.
        """

        class BrokenAuditBackend(MemoryBackend):
            def record_transition_event(self, event):
                raise RuntimeError("simulated audit write failure")

        backend = BrokenAuditBackend()
        _create_active_task(backend)
        engine = TransitionEngine(
            backend=backend,
            role_aliases={"DEVELOPER": "EXECUTOR"},
        )

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert "audit_trail_error" in result, (
            "Response should contain audit_trail_error when event persistence fails"
        )

    def test_audit_persistence_retries_on_transient_failure(self):
        """If record_transition_event fails on the first call but succeeds
        on the second, the event should be persisted (retry semantics).
        """
        call_count = {"n": 0}
        original_record = MemoryBackend.record_transition_event

        class RetryableAuditBackend(MemoryBackend):
            def record_transition_event(self, event):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("transient failure")
                return original_record(self, event)

        backend = RetryableAuditBackend()
        _create_active_task(backend)
        engine = TransitionEngine(
            backend=backend,
            role_aliases={"DEVELOPER": "EXECUTOR"},
        )

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        # The retry should have succeeded, so no audit_trail_error
        assert "audit_trail_error" not in result, (
            "Retry should have succeeded on second attempt; no audit_trail_error expected"
        )
        assert call_count["n"] >= 2, (
            "record_transition_event should have been called at least twice (retry)"
        )


# =========================================================================
# Bug 1B: Path traversal in EG-03
# =========================================================================


class TestBug1B_PathTraversalEG03:
    """Verify that EG-03 rejects paths outside the workspace via prefix tricks
    like /tmp/workspace.bak/file.txt when workspace is /tmp/workspace.
    """

    def test_path_traversal_via_dot_extension_is_rejected(self):
        """A deliverable at /tmp/workspace.bak/file.txt must be REJECTED
        when the workspace is /tmp/workspace.
        """
        ctx = _make_guard_context(
            task_extra={
                "deliverables": json.dumps(["/tmp/workspace.bak/file.txt"]),
            },
            transition_params={"project_root": "/tmp/workspace"},
        )
        result = guard_deliverables_exist(ctx)
        assert not result.passed, (
            "EG-03 should REJECT /tmp/workspace.bak/file.txt — it is outside "
            "/tmp/workspace (path traversal via dot extension in directory name)"
        )

    def test_legitimate_subdirectory_path_is_accepted(self):
        """A deliverable at /tmp/workspace/subdir/file.txt must be ACCEPTED."""
        # Create the file on disk for the test
        workspace = tempfile.mkdtemp(prefix="governor_test_ws_")
        subdir = os.path.join(workspace, "subdir")
        os.makedirs(subdir, exist_ok=True)
        filepath = os.path.join(subdir, "file.txt")
        with open(filepath, "w") as f:
            f.write("test content")

        try:
            ctx = _make_guard_context(
                task_extra={
                    "deliverables": json.dumps([filepath]),
                },
                transition_params={"project_root": workspace},
            )
            result = guard_deliverables_exist(ctx)
            assert result.passed, (
                f"EG-03 should ACCEPT {filepath} — it is inside {workspace}"
            )
        finally:
            os.unlink(filepath)
            os.rmdir(subdir)
            os.rmdir(workspace)


# =========================================================================
# Bug 1C: GDS graph name collision
# =========================================================================


class TestBug1C_GDSGraphNameCollision:
    """Verify that sequential get_task_criticality calls use different
    graph names, and that the graph is dropped even when the algorithm raises.
    """

    def test_sequential_calls_use_different_graph_names(self):
        """Two sequential get_task_criticality calls should project with
        different graph names to avoid GDS name collisions.
        """
        calls: list = []

        class SpyBackend:
            def _run_query(self, query, params, mode="read"):
                calls.append((query, params))
                return []

        analytics = GovernorAnalytics(SpyBackend())  # type: ignore[arg-type]

        # First call
        analytics.get_task_criticality()
        first_calls = list(calls)

        # Second call
        analytics.get_task_criticality()
        second_calls = calls[len(first_calls):]

        # Extract graph names from query params (parameterized via $graph_name)
        # or from the query string itself (for backward compatibility).
        import re
        pattern = r"gov_task_deps_pr_[a-f0-9]+"

        def _extract_graph_names(call_list):
            names = set()
            for query, params in call_list:
                names.update(re.findall(pattern, query))
                if isinstance(params, dict):
                    for v in params.values():
                        if isinstance(v, str):
                            names.update(re.findall(pattern, v))
            return names

        first_names = _extract_graph_names(first_calls)
        second_names = _extract_graph_names(second_calls)

        assert first_names, "Expected to find graph names in first call queries/params"
        assert second_names, "Expected to find graph names in second call queries/params"
        assert first_names.isdisjoint(second_names), (
            f"Graph names must differ between calls to avoid collision: "
            f"first={first_names}, second={second_names}"
        )

    def test_graph_dropped_even_when_algorithm_raises(self):
        """The GDS graph should be dropped (cleanup in finally block) even
        when the pageRank algorithm call raises an exception.

        The get_task_criticality method catches exceptions whose message
        contains 'gds' or 'procedure' and returns an error dict. We
        simulate a GDS-related failure that triggers the catch clause,
        then verify the finally block still runs gds.graph.drop.
        """
        call_log: list = []

        class FailingBackend:
            def _run_query(self, query, params, mode="read"):
                call_log.append(query)
                if "pageRank" in query:
                    raise RuntimeError("gds pageRank algorithm failed")
                return []

        analytics = GovernorAnalytics(FailingBackend())  # type: ignore[arg-type]

        # The method catches GDS-related errors (message contains "gds")
        # and returns an error dict instead of raising.
        result = analytics.get_task_criticality()
        assert isinstance(result, list)
        assert any("error" in r for r in result), (
            "Expected error dict in result when GDS algorithm fails"
        )

        # Verify that gds.graph.drop was called even after the failure
        drop_calls = [q for q in call_log if "gds.graph.drop" in q]
        assert len(drop_calls) >= 1, (
            "gds.graph.drop should be called in the finally block even when "
            "the algorithm raises"
        )


# =========================================================================
# Bug 2A: Guard timeout / close()
# =========================================================================


class TestBug2A_GuardTimeoutClose:
    """Verify that engine.shutdown() cleans up the guard executor and that
    the context manager auto-cleans up.
    """

    def test_shutdown_clears_guard_executor(self):
        """After shutdown(), _guard_executor should be None."""
        _, engine = _make_engine(parallel_guards=True)
        assert engine._guard_executor is not None
        engine.shutdown()
        assert engine._guard_executor is None

    def test_context_manager_auto_cleans_up(self):
        """Using 'with TransitionEngine(...) as engine:' should automatically
        call shutdown and set _guard_executor to None.
        """
        with TransitionEngine(
            backend=MemoryBackend(),
            parallel_guards=True,
        ) as engine:
            assert engine._guard_executor is not None
        assert engine._guard_executor is None


# =========================================================================
# Bug 2B: WriteConflict retry
# =========================================================================


class TestBug2B_WriteConflictRetry:
    """Verify that _is_retryable() correctly identifies transient Neo4j errors
    as retryable and non-transient errors as non-retryable.
    """

    def _make_backend(self):
        """Create a Neo4jBackend with a mocked driver for retryable tests."""
        driver, _, _ = _mock_driver([])
        return _make_neo4j_backend(driver)

    def test_deadlock_detected_is_retryable(self):
        """An exception with code='Neo.TransientError.Transaction.DeadlockDetected'
        should be retryable.
        """
        backend = self._make_backend()
        exc = Exception("DeadlockDetected")
        exc.code = "Neo.TransientError.Transaction.DeadlockDetected"
        assert backend._is_retryable(exc) is True

    def test_syntax_error_is_not_retryable(self):
        """An exception with code='Neo.ClientError.Statement.SyntaxError'
        should NOT be retryable.
        """
        backend = self._make_backend()
        exc = Exception("SyntaxError")
        exc.code = "Neo.ClientError.Statement.SyntaxError"
        assert backend._is_retryable(exc) is False

    def test_generic_transient_error_is_retryable(self):
        """Any Neo.TransientError.* code should be retryable."""
        backend = self._make_backend()
        exc = Exception("TransientError")
        exc.code = "Neo.TransientError.General.DatabaseUnavailable"
        assert backend._is_retryable(exc) is True

    def test_no_code_attribute_is_not_retryable(self):
        """A plain exception without a .code attribute should NOT be retryable."""
        backend = self._make_backend()
        exc = Exception("generic error")
        assert backend._is_retryable(exc) is False


# =========================================================================
# Bug 2C: Secret detection (EG-05)
# =========================================================================


class TestBug2C_SecretDetection:
    """Verify that EG-05 detects various secret and credential patterns."""

    def _assert_secret_detected(self, content, description):
        """Helper: EG-05 should FAIL for the given content."""
        ctx = _make_guard_context(content=content)
        result = guard_no_secrets_in_content(ctx)
        assert not result.passed, (
            f"EG-05 should detect {description} in content"
        )
        assert result.guard_id == "EG-05"

    def test_detects_jwt_token(self):
        """EG-05 should detect a JWT token (base64-encoded header.payload)."""
        self._assert_secret_detected(
            "Authorization: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
            "JWT token",
        )

    def test_detects_slack_token(self):
        """EG-05 should detect a Slack bot token."""
        self._assert_secret_detected(
            "SLACK_TOKEN=xoxb-123456789012-abcdefghij",
            "Slack token",
        )

    def test_detects_db_connection_string(self):
        """EG-05 should detect a PostgreSQL connection string with credentials."""
        self._assert_secret_detected(
            "DATABASE_URL=postgresql://user:pass@host:5432/db",
            "database connection string",
        )

    def test_detects_aws_session_token(self):
        """EG-05 should detect an AWS session token key ID (ASIA prefix)."""
        self._assert_secret_detected(
            "aws_access_key_id = ASIAQWERTYUIOPZXCVBN",
            "AWS session token key ID",
        )

    def test_detects_github_oauth_token(self):
        """EG-05 should detect a GitHub OAuth token (gho_ prefix)."""
        self._assert_secret_detected(
            "token = gho_abcdefghijklmnopqrstuvwxyz12345678",
            "GitHub OAuth token",
        )

    def test_detects_stripe_key(self):
        """EG-05 should detect a Stripe live secret key."""
        self._assert_secret_detected(
            "STRIPE_KEY=sk_live_abcdefghijklmnopqrstuvwx",
            "Stripe API key",
        )

    def test_clean_content_passes(self):
        """EG-05 should PASS when content has no secrets."""
        ctx = _make_guard_context(
            content="This task implements the new dashboard feature. "
                    "All tests pass. Verified with unit tests.",
        )
        result = guard_no_secrets_in_content(ctx)
        assert result.passed, "EG-05 should pass when no secrets are present"


# =========================================================================
# Bug 2D: ensure_schema error reporting
# =========================================================================


class TestBug2D_EnsureSchemaErrorReporting:
    """Verify that when a schema statement fails, ensure_schema returns
    a result with 'errors' list and 'success': False.
    """

    def test_schema_failure_returns_errors_and_false_success(self):
        """When a schema statement raises, result should have errors + success=False."""
        driver, session, tx = _mock_driver([])
        backend = _make_neo4j_backend(driver)

        # Patch _run_write_query to raise for every call, simulating
        # schema statement execution failure.
        backend._run_write_query = MagicMock(
            side_effect=RuntimeError("Constraint creation failed")
        )

        # Patch the importlib.resources file read to return a simple schema
        # with one statement. ensure_schema uses `from importlib import resources as _res`
        # inside the method body, so we patch `importlib.resources.files`.
        with patch("importlib.resources.files") as mock_files:
            mock_ref = MagicMock()
            mock_ref.read_text.return_value = (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Task) "
                "REQUIRE t.task_id IS UNIQUE;"
            )
            mock_files.return_value.joinpath.return_value = mock_ref

            result = backend.ensure_schema()

        assert result["success"] is False, (
            "ensure_schema should return success=False when statements fail"
        )
        assert "errors" in result, (
            "ensure_schema should include an 'errors' list when statements fail"
        )
        assert len(result["errors"]) >= 1
        assert "error" in result["errors"][0]


# =========================================================================
# Bug 2E: GuardResult type validation
# =========================================================================


class TestBug2E_GuardResultTypeValidation:
    """Verify that GuardResult rejects non-bool passed values with TypeError."""

    def test_string_passed_raises_type_error(self):
        """GuardResult('G1', 'yes') should raise TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            GuardResult("G1", "yes")

    def test_integer_passed_raises_type_error(self):
        """GuardResult('G1', 1) should raise TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            GuardResult("G1", 1)

    def test_none_passed_raises_type_error(self):
        """GuardResult('G1', None) should raise TypeError."""
        with pytest.raises(TypeError, match="must be bool"):
            GuardResult("G1", None)

    def test_bool_true_works(self):
        """GuardResult('G1', True) should work fine."""
        result = GuardResult("G1", True)
        assert result.passed is True
        assert result.guard_id == "G1"

    def test_bool_false_works(self):
        """GuardResult('G1', False) should work fine."""
        result = GuardResult("G1", False)
        assert result.passed is False
        assert result.guard_id == "G1"


# =========================================================================
# Bug 2F: Event callback error tracking
# =========================================================================


class TestBug2F_EventCallbackErrorTracking:
    """Verify that when an event callback raises, the event is NOT included
    in events_fired (error tracking).
    """

    def test_failing_callback_excludes_event_from_fired_list(self):
        """A callback that raises should cause its event_id to be excluded
        from events_fired.
        """

        def failing_callback(event_type, config, task_id, task, transition_params):
            raise RuntimeError("Callback exploded")

        sm_path = _make_custom_sm(
            events=[
                {"event_id": "E_BOOM", "type": "custom", "config": {}},
            ],
        )
        try:
            backend = MemoryBackend()
            backend.create_task({
                "task_id": "TASK_CB_FAIL",
                "task_name": "Callback failure test",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Test content.",
            })
            engine = TransitionEngine(
                backend=backend,
                state_machine_path=sm_path,
                event_callbacks=[failing_callback],
            )

            result = engine.transition_task("TASK_CB_FAIL", "DONE", "EXECUTOR")
            assert result["result"] == "PASS", (
                "Transition should still succeed even if callbacks fail"
            )
            assert "E_BOOM" not in result["events_fired"], (
                "Event E_BOOM should NOT be in events_fired because its "
                "callback raised an exception"
            )
        finally:
            os.unlink(sm_path)

    def test_successful_callback_includes_event_in_fired_list(self):
        """A callback that succeeds should include its event_id in events_fired."""
        callback_calls = []

        def good_callback(event_type, config, task_id, task, transition_params):
            callback_calls.append(event_type)

        sm_path = _make_custom_sm(
            events=[
                {"event_id": "E_OK", "type": "custom", "config": {}},
            ],
        )
        try:
            backend = MemoryBackend()
            backend.create_task({
                "task_id": "TASK_CB_OK",
                "task_name": "Callback success test",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Test content.",
            })
            engine = TransitionEngine(
                backend=backend,
                state_machine_path=sm_path,
                event_callbacks=[good_callback],
            )

            result = engine.transition_task("TASK_CB_OK", "DONE", "EXECUTOR")
            assert result["result"] == "PASS"
            assert "E_OK" in result["events_fired"], (
                "Event E_OK should be in events_fired because its callback succeeded"
            )
            assert len(callback_calls) == 1
        finally:
            os.unlink(sm_path)


# =========================================================================
# Bug 2G: Rate limiter capacity
# =========================================================================


class TestBug2G_RateLimiterCapacity:
    """Verify that _RateLimiter evicts LRU keys to stay within max_keys."""

    def test_max_keys_enforced(self):
        """Inserting 3 keys with max_keys=2 should evict the oldest key."""
        limiter = _RateLimiter(max_attempts=5, window_seconds=10, max_keys=2)

        limiter.check("key_a")
        assert len(limiter._attempts) == 1

        limiter.check("key_b")
        assert len(limiter._attempts) == 2

        # Third key should trigger eviction of key_a (LRU)
        limiter.check("key_c")
        assert len(limiter._attempts) <= 2, (
            f"Rate limiter should evict LRU entries to stay within max_keys=2, "
            f"but has {len(limiter._attempts)} keys"
        )
        assert "key_c" in limiter._attempts, "Newest key should be present"
        assert "key_b" in limiter._attempts, "Second key should still be present"
        assert "key_a" not in limiter._attempts, "Oldest key should have been evicted"

    def test_accessing_existing_key_refreshes_lru(self):
        """Accessing an existing key should move it to the MRU position,
        preventing its eviction.
        """
        limiter = _RateLimiter(max_attempts=5, window_seconds=10, max_keys=2)

        limiter.check("key_a")
        limiter.check("key_b")

        # Access key_a again to refresh it (move to MRU)
        limiter.check("key_a")

        # Now insert key_c; key_b should be evicted (LRU), not key_a
        limiter.check("key_c")
        assert len(limiter._attempts) <= 2
        assert "key_a" in limiter._attempts, "key_a was recently accessed, should survive"
        assert "key_c" in limiter._attempts, "key_c is newest, should be present"
        assert "key_b" not in limiter._attempts, "key_b is LRU and should be evicted"

    def test_max_keys_one(self):
        """With max_keys=1, only the most recent key should survive."""
        limiter = _RateLimiter(max_attempts=5, window_seconds=10, max_keys=1)

        limiter.check("alpha")
        assert len(limiter._attempts) == 1

        limiter.check("beta")
        assert len(limiter._attempts) == 1
        assert "beta" in limiter._attempts
        assert "alpha" not in limiter._attempts


# =========================================================================
# Bug 2H: Relationship truncation metadata
# =========================================================================


class TestBug2H_RelationshipTruncationMetadata:
    """Verify that when relationships exceed the configured limit, the
    response includes total_relationship_count and relationship_limit keys.
    """

    def test_truncated_response_includes_metadata(self):
        """When relationships exceed the limit, total_relationship_count
        and relationship_limit must be present in the response.
        """
        # Create many outgoing relationships to trigger truncation.
        # Default relationship_limit is 200; set it low for this test.
        rel_limit = 3
        out_rels = [
            {"type": "HAS_REVIEW", "node": {"review_type": "SELF_REVIEW"}, "node_labels": ["Review"]}
            for _ in range(rel_limit + 2)  # exceed the limit
        ]
        task_record = {
            "task": {"task_id": "T_TRUNC", "status": "ACTIVE", "role": "DEV"},
            "out_rels": out_rels,
            "in_rels": [],
        }
        driver, _, _ = _mock_driver([task_record])
        backend = _make_neo4j_backend(driver)
        backend._relationship_limit = rel_limit

        result = backend.get_task("T_TRUNC")

        assert result.get("relationships_truncated") is True, (
            "Response should indicate relationships were truncated"
        )
        assert "total_relationship_count" in result, (
            "Response should include total_relationship_count when truncated"
        )
        assert "relationship_limit" in result, (
            "Response should include relationship_limit when truncated"
        )
        assert result["relationship_limit"] == rel_limit
        assert len(result["relationships"]) <= rel_limit, (
            "Returned relationships should be capped at relationship_limit"
        )

    def test_non_truncated_response_omits_metadata(self):
        """When relationships are within the limit, truncation metadata
        should NOT be present.
        """
        out_rels = [
            {"type": "HAS_REVIEW", "node": {"review_type": "SELF_REVIEW"}, "node_labels": ["Review"]}
        ]
        task_record = {
            "task": {"task_id": "T_FIT", "status": "ACTIVE", "role": "DEV"},
            "out_rels": out_rels,
            "in_rels": [],
        }
        driver, _, _ = _mock_driver([task_record])
        backend = _make_neo4j_backend(driver)

        result = backend.get_task("T_FIT")

        assert "relationships_truncated" not in result, (
            "Response should NOT include truncation metadata when within limit"
        )
        assert "total_relationship_count" not in result
        assert "relationship_limit" not in result


# =========================================================================
# Bug 2I: Regex DoS in deliverables parsing
# =========================================================================


class TestBug2I_RegexDoSDeliverables:
    """Verify that _parse_deliverables_from_content handles adversarial input
    without catastrophic backtracking.
    """

    def test_adversarial_backticks_complete_within_timeout(self):
        """Content with 10K backticks should parse in under 2 seconds.

        Before the fix, the regex ``[^`]*`` pattern inside a possessive-like
        code block removal could cause exponential backtracking.
        """
        adversarial_content = "`" * 10_000
        start = time.monotonic()
        _parse_deliverables_from_content(adversarial_content)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, (
            f"_parse_deliverables_from_content took {elapsed:.2f}s on 10K backticks; "
            "expected < 2.0s. This suggests catastrophic backtracking (regex DoS)."
        )

    def test_adversarial_nested_backticks_complete_within_timeout(self):
        """Alternating backtick patterns should not cause catastrophic backtracking."""
        adversarial_content = ("``` " * 5000) + "\n## Deliverables\n- file.txt\n"
        start = time.monotonic()
        _parse_deliverables_from_content(adversarial_content)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, (
            f"_parse_deliverables_from_content took {elapsed:.2f}s; expected < 2.0s"
        )

    def test_large_content_is_capped(self):
        """Content exceeding the internal max length should be truncated
        before regex processing (defense in depth).
        """
        huge_content = "x" * 600_000 + "\n## Deliverables\n- tail.txt\n"
        start = time.monotonic()
        result = _parse_deliverables_from_content(huge_content)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, (
            f"Parsing huge content took {elapsed:.2f}s; cap should prevent DoS"
        )
        # The deliverables section is beyond the cap, so it should not be found
        assert "tail.txt" not in result, (
            "Deliverables beyond the cap boundary should not be parsed"
        )

    def test_normal_deliverables_still_parsed(self):
        """Normal content with a Deliverables section should parse correctly."""
        content = (
            "## Summary\nThis is a task.\n\n"
            "## Deliverables\n"
            "- `output/report.md`\n"
            "- `scripts/deploy.sh`\n\n"
            "## Notes\nDone.\n"
        )
        result = _parse_deliverables_from_content(content)
        assert "output/report.md" in result
        assert "scripts/deploy.sh" in result


# =========================================================================
# Integration: Full round-trip with secret in content
# =========================================================================


class TestIntegrationSecretBlocksTransition:
    """End-to-end: EG-05 blocks a transition when content has secrets."""

    def test_jwt_in_task_content_blocks_submission(self):
        """A task with a JWT token in content should fail submission."""
        backend, engine = _make_engine()
        _create_active_task(backend)
        backend.add_review("TASK_001", {
            "review_id": "R1",
            "review_type": "SELF_REVIEW",
            "rating": 8.0,
        })
        backend.add_report("TASK_001", {
            "report_id": "RP1",
            "report_type": "IMPLEMENTATION",
        })
        # Inject a JWT token into the content
        backend.update_task("TASK_001", {
            "content": (
                "Implement authentication.\n"
                "Test token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0\n"
                "Tests verify correctness."
            ),
        })

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        failed_ids = {g["guard_id"] for g in result["guard_results"] if not g["passed"]}
        assert "EG-05" in failed_ids, (
            "EG-05 should block submission when JWT token is in task content"
        )
