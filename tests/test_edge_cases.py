"""Edge case tests for issues identified in code review.

Covers:
- Fix #3: Cypher property name validation (whitelist)
- Fix #4: Silent parallel guard timeout default
- Fix #5: Connection failures, race conditions, malformed data
- Fix #7: Relationship truncation guard safety
- Fix #8: Task data validation on create/update
"""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from governor.backend.memory_backend import MemoryBackend
from governor.backend.base import validate_task_data
from governor.engine.transition_engine import TransitionEngine, GuardContext


# =====================================================================
# Fix #3: Cypher property name whitelist validation
# =====================================================================


class TestCypherPropertyValidation:
    """Verify that the Neo4j backend rejects disallowed property names."""

    def test_allowed_property_names_accepted(self):
        """Standard task properties should pass validation."""
        from governor.backend.neo4j_backend import _validate_property_name

        for name in ["task_id", "status", "priority", "content", "revision_count"]:
            _validate_property_name(name)  # should not raise

    def test_disallowed_property_names_rejected(self):
        """Arbitrary or crafted property names should be rejected."""
        from governor.backend.neo4j_backend import _validate_property_name

        with pytest.raises(ValueError, match="not in the allowed set"):
            _validate_property_name("__injected__")

        with pytest.raises(ValueError, match="not in the allowed set"):
            _validate_property_name("MATCH")

        with pytest.raises(ValueError, match="not in the allowed set"):
            _validate_property_name("arbitrary_field")

    def test_python_identifier_that_is_not_allowed(self):
        """str.isidentifier() would accept these, but the whitelist should not."""
        from governor.backend.neo4j_backend import _validate_property_name

        # These are valid Python identifiers but NOT in our whitelist
        for name in ["class_", "return_", "lambda_", "exec", "eval"]:
            with pytest.raises(ValueError):
                _validate_property_name(name)


# =====================================================================
# Fix #4: Silent parallel guard timeout default
# =====================================================================


class TestParallelGuardTimeoutWarning:
    """Verify that parallel_guards without explicit timeout emits warning."""

    def test_parallel_guards_without_timeout_warns(self):
        backend = MemoryBackend()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            engine = TransitionEngine(
                backend=backend,
                parallel_guards=True,
                # No guard_timeout_seconds — should warn
            )
            engine.shutdown()

        # Should have at least one UserWarning about the default timeout
        timeout_warnings = [x for x in w if "guard_timeout_seconds" in str(x.message)]
        assert len(timeout_warnings) >= 1, (
            f"Expected warning about default timeout, got: {[str(x.message) for x in w]}"
        )

    def test_parallel_guards_with_explicit_timeout_no_warning(self):
        backend = MemoryBackend()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            engine = TransitionEngine(
                backend=backend,
                parallel_guards=True,
                guard_timeout_seconds=30.0,
            )
            engine.shutdown()

        timeout_warnings = [x for x in w if "guard_timeout_seconds" in str(x.message)]
        assert len(timeout_warnings) == 0


# =====================================================================
# Fix #5: Connection failures, malformed data
# =====================================================================


class TestMalformedTaskData:
    """Verify the engine handles malformed task data gracefully."""

    def test_transition_with_nonexistent_task(self):
        backend = MemoryBackend()
        engine = TransitionEngine(backend=backend)
        result = engine.transition_task("NONEXISTENT", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "TASK_NOT_FOUND"

    def test_transition_with_garbage_status(self):
        """A task with a non-state-machine status should fail gracefully."""
        backend = MemoryBackend()
        # Bypass validation to inject bad status directly
        backend._tasks["BAD_TASK"] = {
            "task_id": "BAD_TASK",
            "status": "NONEXISTENT_STATUS",
            "role": "EXECUTOR",
            "task_type": "IMPLEMENTATION",
            "priority": "HIGH",
            "content": "test",
        }
        engine = TransitionEngine(backend=backend)
        result = engine.transition_task("BAD_TASK", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ILLEGAL_TRANSITION"

    def test_transition_with_empty_task_id(self):
        backend = MemoryBackend()
        engine = TransitionEngine(backend=backend)
        result = engine.transition_task("", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"

    def test_backend_exception_during_read(self):
        """Simulate a backend failure during get_task."""
        backend = MagicMock(spec=MemoryBackend)
        backend.get_task.side_effect = RuntimeError("Connection lost")
        engine = TransitionEngine(backend=backend)
        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
        assert result["result"] == "FAIL"
        assert result["error_code"] == "BACKEND_ERROR"


class TestConcurrentStateConflict:
    """Verify optimistic concurrency detection."""

    def test_state_conflict_returns_error(self):
        backend = MemoryBackend()
        backend.create_task({
            "task_id": "TASK_CONFLICT",
            "task_name": "Conflict test",
            "task_type": "IMPLEMENTATION",
            "role": "EXECUTOR",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "test",
        })
        # Manually update task status to BLOCKED to simulate concurrent change
        result = backend.update_task(
            "TASK_CONFLICT",
            {"status": "ACTIVE"},  # same status, no change
            expected_current_status="READY_FOR_REVIEW",  # wrong expectation
        )
        assert result["success"] is False
        assert result["error_code"] == "STATE_CONFLICT"


# =====================================================================
# Fix #7: Relationship truncation awareness
# =====================================================================


class TestRelationshipTruncationWarning:
    """Verify that GuardContext warns when relationships are truncated."""

    def test_truncated_relationships_set_flag(self):
        task_data = {
            "task": {"task_id": "T1", "status": "ACTIVE"},
            "relationships": [{"type": "HAS_REVIEW", "node": {}, "node_labels": ["Review"]}],
            "relationships_truncated": True,
        }
        ctx = GuardContext("T1", task_data, {})
        assert ctx.relationships_truncated is True

    def test_non_truncated_relationships_no_flag(self):
        task_data = {
            "task": {"task_id": "T2", "status": "ACTIVE"},
            "relationships": [],
        }
        ctx = GuardContext("T2", task_data, {})
        assert ctx.relationships_truncated is False


# =====================================================================
# Fix #8: Task data validation
# =====================================================================


class TestTaskDataValidation:
    """Verify task data validation on create."""

    def test_missing_task_id_rejected(self):
        errors = validate_task_data({"status": "ACTIVE"})
        assert any("task_id" in e for e in errors)

    def test_missing_status_rejected(self):
        errors = validate_task_data({"task_id": "T1"})
        assert any("status" in e for e in errors)

    def test_invalid_status_rejected_strict(self):
        errors = validate_task_data(
            {"task_id": "T1", "status": "NONEXISTENT"},
            strict=True,
        )
        assert any("Invalid status" in e for e in errors)

    def test_invalid_priority_rejected_strict(self):
        errors = validate_task_data(
            {"task_id": "T1", "status": "ACTIVE", "priority": "SUPER_HIGH"},
            strict=True,
        )
        assert any("Invalid priority" in e for e in errors)

    def test_valid_task_passes(self):
        errors = validate_task_data({
            "task_id": "T1",
            "status": "ACTIVE",
            "priority": "HIGH",
            "task_type": "IMPLEMENTATION",
        })
        assert errors == []

    def test_custom_task_type_allowed_non_strict(self):
        errors = validate_task_data(
            {"task_id": "T1", "status": "ACTIVE", "task_type": "CUSTOM_TYPE"},
            strict=False,
        )
        assert errors == []

    def test_memory_backend_create_validates(self):
        backend = MemoryBackend()
        with pytest.raises(ValueError, match="Invalid task data"):
            backend.create_task({"task_id": "T1", "status": "GARBAGE_STATUS"})

    def test_memory_backend_create_accepts_valid(self):
        backend = MemoryBackend()
        task = backend.create_task({
            "task_id": "T_VALID",
            "task_name": "Valid task",
            "task_type": "IMPLEMENTATION",
            "role": "EXECUTOR",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "valid",
        })
        assert task["task_id"] == "T_VALID"

    def test_memory_backend_create_non_strict(self):
        """Non-strict mode allows custom task_type values."""
        backend = MemoryBackend()
        task = backend.create_task(
            {
                "task_id": "T_CUSTOM",
                "task_name": "Custom type",
                "task_type": "MY_CUSTOM_TYPE",
                "role": "EXECUTOR",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "custom",
            },
            strict=False,
        )
        assert task["task_id"] == "T_CUSTOM"


# =====================================================================
# Zombie thread tracking (Fix #2)
# =====================================================================


class TestZombieThreadTracking:
    """Verify zombie thread counter is exposed."""

    def test_zombie_count_starts_at_zero(self):
        backend = MemoryBackend()
        engine = TransitionEngine(backend=backend)
        assert engine.zombie_thread_count == 0


# =====================================================================
# Fix #9: Field size validation parity across backends
# =====================================================================


class TestFieldSizeValidation:
    """Memory backends must enforce the same size limit as Neo4j backends."""

    def test_validate_task_data_rejects_oversized_field(self):
        """validate_task_data catches oversized fields at the base layer."""
        from governor.backend.base import MAX_FIELD_SIZE

        oversized = "x" * (MAX_FIELD_SIZE + 1)
        errors = validate_task_data(
            {"task_id": "T1", "status": "ACTIVE", "content": oversized},
        )
        assert any("exceeds maximum size" in e for e in errors)

    def test_validate_task_data_accepts_max_size_field(self):
        """Fields exactly at the limit should pass."""
        from governor.backend.base import MAX_FIELD_SIZE

        at_limit = "x" * MAX_FIELD_SIZE
        errors = validate_task_data(
            {"task_id": "T1", "status": "ACTIVE", "content": at_limit},
        )
        assert not any("exceeds maximum size" in e for e in errors)

    def test_memory_backend_normalize_rejects_oversized(self):
        """MemoryBackend's normalize function should reject oversized fields."""
        from governor.backend.memory_backend import _normalize_task_field
        from governor.backend.base import MAX_FIELD_SIZE

        oversized = "x" * (MAX_FIELD_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            _normalize_task_field("content", oversized)

    def test_memory_backend_create_rejects_oversized_content(self):
        """Creating a task with oversized content should fail."""
        from governor.backend.base import MAX_FIELD_SIZE

        backend = MemoryBackend()
        oversized = "x" * (MAX_FIELD_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            backend.create_task({
                "task_id": "T_BIG",
                "status": "ACTIVE",
                "content": oversized,
            })
