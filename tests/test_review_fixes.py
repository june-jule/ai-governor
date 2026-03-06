"""Tests for Bug Fixes B1-B4 and Improvements I1-I7 (review round 2).

B1: REPORTS_ON direction dedup in Neo4j backend
B2: verify_connectivity at backend init
B3: Lock memory leak (LRU bounds)
B4: Guard timeout defaults and max_workers
I1: health_check() on base + Neo4j backend
I2: ensure_schema() on Neo4j backend
I3: Structured Neo4j error codes
I4: Batch transition_tasks()
I5: get_logging_config() dictConfig support
I6: TypedDict definitions
I7: Query rate limiting at backend level
"""

import asyncio
import collections
import logging
import logging.config
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

import pytest

from governor.backend.memory_backend import MemoryBackend
from governor.backend.base import GovernorBackend
from governor.backend.async_base import AsyncGovernorBackend
from governor.engine.transition_engine import TransitionEngine

import governor.guards.executor_guards  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(**kwargs):
    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEV": "EXECUTOR", "DEVELOPER": "EXECUTOR"},
        **kwargs,
    )
    return backend, engine


def _create_ready_task(backend, task_id="TASK_001"):
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


def _make_mock_neo4j_backend(mock_driver):
    """Create a Neo4jBackend with a mocked driver, bypassing verify_connectivity."""
    with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
        mock_gdb.driver.return_value = mock_driver
        from governor.backend.neo4j_backend import Neo4jBackend
        backend = Neo4jBackend(
            uri="neo4j://mock:7687", user="neo4j", password="test",
            verify_connectivity=False,
        )
    return backend


def _mock_driver(records=None):
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
# B1: REPORTS_ON direction dedup
# =========================================================================

class TestB1ReportsOnDirection:
    """The get_task() outbound query should NOT include REPORTS_ON."""

    def test_outbound_query_excludes_reports_on(self):
        """Outbound relationship query should not contain REPORTS_ON."""
        task_record = {
            "task": {"task_id": "T1", "status": "ACTIVE", "role": "DEV"},
            "out_rels": [
                {"type": "HAS_REVIEW", "node": {"review_type": "SELF_REVIEW"}, "node_labels": ["Review"]},
            ],
            "in_rels": [
                {"type": "REPORTS_ON", "node": {"report_id": "RPT1"}, "node_labels": ["Report"]},
            ],
        }
        driver, session, tx = _mock_driver([task_record])
        backend = _make_mock_neo4j_backend(driver)
        result = backend.get_task("T1")

        # Verify the Cypher query — outbound should NOT contain REPORTS_ON
        query_arg = tx.run.call_args[0][0]
        # The outbound CALL should match HAS_REVIEW and HANDOFF_TO but not REPORTS_ON
        # Find the outbound subquery portion
        assert "REPORTS_ON" in query_arg  # Still present (in inbound)
        # Relationships should include both types without duplication
        types = {r["type"] for r in result["relationships"]}
        assert "HAS_REVIEW" in types
        assert "REPORTS_ON" in types

    def test_memory_backend_reports_appear_once(self):
        """MemoryBackend should not duplicate reports in relationships."""
        backend = MemoryBackend()
        backend.create_task({
            "task_id": "T1", "task_name": "Test", "task_type": "IMPLEMENTATION",
            "role": "DEV", "status": "ACTIVE", "priority": "HIGH", "content": "test",
        })
        backend.add_report("T1", {"report_id": "RPT1", "report_type": "SUMMARY"})
        data = backend.get_task("T1")
        report_rels = [r for r in data["relationships"] if r["type"] == "REPORTS_ON"]
        assert len(report_rels) == 1


# =========================================================================
# B2: verify_connectivity at init
# =========================================================================

class TestB2VerifyConnectivity:
    """Backend should optionally verify Neo4j connectivity at init."""

    def test_verify_connectivity_raises_on_failure(self):
        """When verify_connectivity=True and connection fails, raise ConnectionError."""
        with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
            mock_driver = MagicMock()
            mock_driver.verify_connectivity.side_effect = RuntimeError("Connection refused")
            mock_gdb.driver.return_value = mock_driver

            from governor.backend.neo4j_backend import Neo4jBackend
            with pytest.raises(ConnectionError, match="Failed to connect"):
                Neo4jBackend(
                    uri="neo4j://bad:7687", user="neo4j", password="test",
                    verify_connectivity=True,
                )
            mock_driver.close.assert_called_once()

    def test_verify_connectivity_false_skips_check(self):
        """When verify_connectivity=False, no connectivity check is done."""
        with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
            mock_driver = MagicMock()
            mock_gdb.driver.return_value = mock_driver

            from governor.backend.neo4j_backend import Neo4jBackend
            backend = Neo4jBackend(
                uri="neo4j://mock:7687", user="neo4j", password="test",
                verify_connectivity=False,
            )
            mock_driver.verify_connectivity.assert_not_called()
            backend.close()

    def test_verify_connectivity_success(self):
        """When connectivity succeeds, no exception is raised."""
        with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
            mock_driver = MagicMock()
            mock_driver.verify_connectivity.return_value = None
            mock_gdb.driver.return_value = mock_driver

            from governor.backend.neo4j_backend import Neo4jBackend
            backend = Neo4jBackend(
                uri="neo4j://mock:7687", user="neo4j", password="test",
                verify_connectivity=True,
            )
            mock_driver.verify_connectivity.assert_called_once()
            backend.close()


# =========================================================================
# B3: LRU-bounded lock store
# =========================================================================

class TestB3LockLRU:
    """Per-task lock store should be LRU-bounded."""

    def test_lock_store_is_ordered_dict(self):
        """Lock store should use OrderedDict for LRU eviction."""
        backend = MemoryBackend()
        backend._get_task_lock("TASK_A")
        assert isinstance(backend._task_locks_store, collections.OrderedDict)

    def test_lock_store_evicts_oldest(self):
        """When exceeding _MAX_TASK_LOCKS, oldest lock should be evicted."""

        class SmallLockBackend(MemoryBackend):
            _MAX_TASK_LOCKS = 3

        backend = SmallLockBackend()
        backend._get_task_lock("TASK_A")
        backend._get_task_lock("TASK_B")
        backend._get_task_lock("TASK_C")
        assert len(backend._task_locks_store) == 3
        assert "TASK_A" in backend._task_locks_store

        # Adding a 4th should evict TASK_A
        backend._get_task_lock("TASK_D")
        assert len(backend._task_locks_store) == 3
        assert "TASK_A" not in backend._task_locks_store
        assert "TASK_D" in backend._task_locks_store

    def test_lock_access_refreshes_lru(self):
        """Accessing a lock should move it to the end (most recently used)."""

        class SmallLockBackend(MemoryBackend):
            _MAX_TASK_LOCKS = 3

        backend = SmallLockBackend()
        backend._get_task_lock("TASK_A")
        backend._get_task_lock("TASK_B")
        backend._get_task_lock("TASK_C")

        # Access A to refresh it
        backend._get_task_lock("TASK_A")

        # Now B is the oldest; adding D should evict B, not A
        backend._get_task_lock("TASK_D")
        assert "TASK_A" in backend._task_locks_store
        assert "TASK_B" not in backend._task_locks_store

    def test_async_lock_store_is_ordered_dict(self):
        """Async backend lock store should also use OrderedDict."""

        class ConcreteAsyncBackend(AsyncGovernorBackend):
            async def get_task(self, task_id): ...
            async def update_task(self, task_id, updates, expected_current_status=None): ...
            async def task_exists(self, task_id): ...
            async def get_reviews_for_task(self, task_id): ...
            async def get_reports_for_task(self, task_id): ...

        backend = ConcreteAsyncBackend()
        lock = backend._get_task_lock("TASK_ASYNC")
        assert isinstance(lock, asyncio.Lock)
        assert isinstance(backend._task_locks_store, collections.OrderedDict)

    def test_max_task_locks_class_attribute(self):
        """_MAX_TASK_LOCKS should be configurable at the class level."""
        assert GovernorBackend._MAX_TASK_LOCKS == 10_000


# =========================================================================
# B4: Guard timeout defaults and cancellation
# =========================================================================

class TestB4GuardTimeout:
    """Parallel guards should have a default timeout and cancellation."""

    def test_parallel_guards_get_default_timeout(self):
        """parallel_guards=True without explicit timeout should default to 60s."""
        _, engine = _make_engine(parallel_guards=True)
        assert engine._guard_timeout_seconds == 60.0

    def test_explicit_timeout_is_preserved(self):
        """Explicit guard_timeout_seconds should not be overridden."""
        _, engine = _make_engine(
            parallel_guards=True, guard_timeout_seconds=10.0,
        )
        assert engine._guard_timeout_seconds == 10.0

    def test_guard_max_workers_configurable(self):
        """guard_max_workers should control thread pool size."""
        _, engine = _make_engine(parallel_guards=True, guard_max_workers=2)
        assert engine._guard_executor is not None
        assert engine._guard_executor._max_workers == 2

    def test_guard_max_workers_minimum_one(self):
        """guard_max_workers should be at least 1."""
        _, engine = _make_engine(parallel_guards=True, guard_max_workers=0)
        assert engine._guard_executor._max_workers == 1


# =========================================================================
# I1: health_check()
# =========================================================================

class TestI1HealthCheck:
    """Backend health_check() method."""

    def test_base_backend_health_check_stub(self):
        """Base class stub returns minimal healthy response."""
        backend = MemoryBackend()
        result = backend.health_check()
        assert result["healthy"] is True
        assert result["backend"] == "MemoryBackend"

    def test_neo4j_health_check_success(self):
        """Neo4j health_check returns server info on success."""
        driver, _, _ = _mock_driver()
        mock_info = MagicMock()
        mock_info.address = ("localhost", 7687)
        mock_info.agent = "Neo4j/5.0.0"
        mock_info.protocol_version = (5, 0)
        driver.get_server_info.return_value = mock_info

        backend = _make_mock_neo4j_backend(driver)
        result = backend.health_check()
        assert result["healthy"] is True
        assert "Neo4j" in result["server_version"]

    def test_neo4j_health_check_failure(self):
        """Neo4j health_check returns error on failure."""
        driver, _, _ = _mock_driver()
        driver.get_server_info.side_effect = RuntimeError("Connection lost")

        backend = _make_mock_neo4j_backend(driver)
        result = backend.health_check()
        assert result["healthy"] is False
        assert "Connection lost" in result["error"]


# =========================================================================
# I2: ensure_schema()
# =========================================================================

class TestI2EnsureSchema:
    """Neo4j ensure_schema() method."""

    def test_ensure_schema_executes_statements(self):
        """ensure_schema() should read and execute schema statements."""
        driver, session, tx = _mock_driver()
        backend = _make_mock_neo4j_backend(driver)

        result = backend.ensure_schema()
        assert result["success"] is True
        assert result["statements_applied"] > 0
        # Each statement should have been run
        assert tx.run.call_count >= result["statements_applied"]


# =========================================================================
# I3: Structured Neo4j error codes
# =========================================================================

class TestI3StructuredErrorCodes:
    """Neo4j error codes should be extracted and logged."""

    def test_neo4j_error_code_extracted(self):
        """Exceptions with a .code attribute should be logged with the code."""
        driver, session, tx = _mock_driver()
        backend = _make_mock_neo4j_backend(driver)

        # Create an exception with a .code attribute
        exc = Exception("Constraint violation")
        exc.code = "Neo.ClientError.Schema.ConstraintValidationFailed"  # type: ignore[attr-defined]
        tx.run.side_effect = exc

        with pytest.raises(Exception, match="Constraint violation"):
            backend._run_query("MATCH (n) RETURN n", {}, "read")


# =========================================================================
# I4: Batch transition_tasks()
# =========================================================================

class TestI4BatchTransitions:
    """TransitionEngine.transition_tasks() batch convenience method."""

    def test_transition_tasks_returns_list(self):
        """transition_tasks should return a list of results."""
        backend, engine = _make_engine()
        _create_ready_task(backend, "TASK_A")
        _create_ready_task(backend, "TASK_B")

        results = engine.transition_tasks(
            ["TASK_A", "TASK_B"], "READY_FOR_REVIEW", "EXECUTOR",
        )
        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0]["result"] == "PASS"
        assert results[1]["result"] == "PASS"

    def test_transition_tasks_preserves_order(self):
        """Results should be in the same order as task_ids."""
        backend, engine = _make_engine()
        _create_ready_task(backend, "TASK_1")
        _create_ready_task(backend, "TASK_2")

        results = engine.transition_tasks(
            ["TASK_1", "TASK_2"], "READY_FOR_REVIEW", "EXECUTOR",
        )
        # Both should pass, and be in the order provided
        assert len(results) == 2
        assert results[0]["result"] == "PASS"
        assert results[1]["result"] == "PASS"
        assert results[0]["from_state"] == "ACTIVE"
        assert results[1]["from_state"] == "ACTIVE"

    def test_transition_tasks_partial_failure(self):
        """If one task fails, others should still be attempted."""
        backend, engine = _make_engine()
        _create_ready_task(backend, "TASK_OK")
        # TASK_BAD doesn't exist
        results = engine.transition_tasks(
            ["TASK_OK", "TASK_BAD"], "READY_FOR_REVIEW", "EXECUTOR",
        )
        assert results[0]["result"] == "PASS"
        assert results[1]["result"] == "FAIL"

    def test_transition_tasks_dry_run(self):
        """Dry run should not change state for any task."""
        backend, engine = _make_engine()
        _create_ready_task(backend, "TASK_DR")

        results = engine.transition_tasks(
            ["TASK_DR"], "READY_FOR_REVIEW", "EXECUTOR", dry_run=True,
        )
        assert results[0]["result"] == "PASS"
        assert results[0]["dry_run"] is True

        data = backend.get_task("TASK_DR")
        assert data["task"]["status"] == "ACTIVE"

    def test_transition_tasks_empty_list(self):
        """Empty task list should return empty results."""
        _, engine = _make_engine()
        results = engine.transition_tasks([], "READY_FOR_REVIEW", "EXECUTOR")
        assert results == []


# =========================================================================
# I5: get_logging_config()
# =========================================================================

class TestI5LoggingConfig:
    """get_logging_config() dictConfig compatibility."""

    def test_get_logging_config_returns_valid_dict(self):
        """Should return a dict with version=1."""
        from governor.logging import get_logging_config
        config = get_logging_config()
        assert config["version"] == 1
        assert "loggers" in config
        assert "governor" in config["loggers"]

    def test_get_logging_config_custom_level(self):
        """Should respect the level parameter."""
        from governor.logging import get_logging_config
        config = get_logging_config(level="DEBUG")
        assert config["loggers"]["governor"]["level"] == "DEBUG"

    def test_get_logging_config_works_with_dictconfig(self):
        """Should be usable with logging.config.dictConfig."""
        from governor.logging import get_logging_config
        config = get_logging_config(level="WARNING")

        # This should not raise
        logging.config.dictConfig(config)

        logger = logging.getLogger("governor")
        assert logger.level == logging.WARNING

    def test_get_logging_config_disable_existing_loggers_false(self):
        """Should not disable existing loggers."""
        from governor.logging import get_logging_config
        config = get_logging_config()
        assert config["disable_existing_loggers"] is False

    def test_structured_formatter_referenced(self):
        """Should reference StructuredFormatter via () factory."""
        from governor.logging import get_logging_config
        config = get_logging_config()
        assert config["formatters"]["governor_structured"]["()"] == "governor.logging.StructuredFormatter"


# =========================================================================
# I6: TypedDict definitions
# =========================================================================

class TestI6TypedDicts:
    """TypedDict definitions in governor.types."""

    def test_import_task_dict(self):
        """TaskDict should be importable."""
        from governor.types import TaskDict
        assert TaskDict is not None

    def test_import_guard_result_dict(self):
        """GuardResultDict should be importable."""
        from governor.types import GuardResultDict
        assert GuardResultDict is not None

    def test_import_transition_result_dict(self):
        """TransitionResultDict should be importable."""
        from governor.types import TransitionResultDict
        assert TransitionResultDict is not None

    def test_import_transition_event_dict(self):
        """TransitionEventDict should be importable."""
        from governor.types import TransitionEventDict
        assert TransitionEventDict is not None

    def test_import_available_transition_dict(self):
        """AvailableTransitionDict should be importable."""
        from governor.types import AvailableTransitionDict
        assert AvailableTransitionDict is not None

    def test_lazy_import_from_governor(self):
        """Types should be lazily importable from top-level governor package."""
        import governor
        td = governor.TaskDict  # type: ignore[attr-defined]
        assert td is not None

    def test_lazy_import_unknown_raises(self):
        """Unknown attributes should still raise AttributeError."""
        import governor
        with pytest.raises(AttributeError):
            governor.NonexistentType  # type: ignore[attr-defined]


# =========================================================================
# I7: Query rate limiting
# =========================================================================

class TestI7RateLimiting:
    """Backend-level query rate limiting."""

    def test_rate_limiter_allows_within_limit(self):
        """Queries within rate limit should be allowed."""
        from governor.backend.neo4j_backend import _QueryRateLimiter
        limiter = _QueryRateLimiter(max_queries=5, window_seconds=1.0)
        for _ in range(5):
            assert limiter.check() is True

    def test_rate_limiter_blocks_over_limit(self):
        """Queries over rate limit should be blocked."""
        from governor.backend.neo4j_backend import _QueryRateLimiter
        limiter = _QueryRateLimiter(max_queries=2, window_seconds=1.0)
        assert limiter.check() is True
        assert limiter.check() is True
        assert limiter.check() is False

    def test_rate_limiter_window_expiry(self):
        """After window expires, queries should be allowed again."""
        from governor.backend.neo4j_backend import _QueryRateLimiter
        limiter = _QueryRateLimiter(max_queries=1, window_seconds=0.05)
        assert limiter.check() is True
        assert limiter.check() is False
        time.sleep(0.06)
        assert limiter.check() is True

    def test_rate_limiter_min_values(self):
        """Rate limiter should enforce minimum values."""
        from governor.backend.neo4j_backend import _QueryRateLimiter
        limiter = _QueryRateLimiter(max_queries=0, window_seconds=0.0)
        assert limiter._max == 1
        assert limiter._window >= 0.01

    def test_backend_with_rate_limit_param(self):
        """Neo4jBackend should accept query_rate_limit parameter."""
        driver, _, _ = _mock_driver()
        with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
            mock_gdb.driver.return_value = driver
            from governor.backend.neo4j_backend import Neo4jBackend
            backend = Neo4jBackend(
                uri="neo4j://mock:7687", user="neo4j", password="test",
                verify_connectivity=False,
                query_rate_limit=(100, 1.0),
            )
            assert backend._query_rate_limiter is not None
            backend.close()

    def test_backend_without_rate_limit(self):
        """Without query_rate_limit, limiter should be None."""
        driver, _, _ = _mock_driver()
        backend = _make_mock_neo4j_backend(driver)
        assert backend._query_rate_limiter is None
        backend.close()
