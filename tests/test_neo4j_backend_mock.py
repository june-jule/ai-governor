"""Tests for Neo4jBackend using mocked Neo4j driver (no real database needed)."""

from unittest.mock import MagicMock, patch

import pytest


class TestNeo4jBackendMock:

    def _make_backend(self, mock_driver):
        """Create a Neo4jBackend with a mocked driver."""
        with patch("governor.backend.neo4j_backend._Neo4jDriver") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            from governor.backend.neo4j_backend import Neo4jBackend
            backend = Neo4jBackend(uri="neo4j://mock:7687", user="neo4j", password="test")
        return backend

    def _mock_driver(self, records=None):
        """Create a mock driver that returns given records."""
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

    def test_get_task_returns_correct_structure(self):
        task_record = {
            "task": {"task_id": "T1", "status": "ACTIVE", "role": "DEV"},
            "out_rels": [{"type": "HAS_REVIEW", "node": {"review_type": "SELF_REVIEW"}, "node_labels": ["Review"]}],
            "in_rels": [],
        }
        driver, session, _ = self._mock_driver([task_record])
        backend = self._make_backend(driver)
        result = backend.get_task("T1")
        assert result["task"]["task_id"] == "T1"
        assert len(result["relationships"]) == 1
        assert result["relationships"][0]["type"] == "HAS_REVIEW"

    def test_get_task_not_found(self):
        driver, _, _ = self._mock_driver([])
        backend = self._make_backend(driver)
        with pytest.raises(ValueError, match="Task not found"):
            backend.get_task("NONEXISTENT")

    def test_update_task_builds_set_clauses(self):
        record = {"task_id": "T1", "status": "DONE"}
        driver, session, tx = self._mock_driver([record])
        backend = self._make_backend(driver)
        result = backend.update_task("T1", {"status": "DONE"}, expected_current_status="ACTIVE")
        assert result["success"] is True
        session.execute_write.assert_called_once()
        tx.run.assert_called_once()
        query_arg = tx.run.call_args[0][0]
        assert "t.status" in query_arg
        assert "expected_current_status" in query_arg

    def test_update_task_rejects_invalid_property_name(self):
        driver, _, _ = self._mock_driver([])
        backend = self._make_backend(driver)
        with pytest.raises(ValueError, match="not in the allowed set"):
            backend.update_task("T1", {"drop table;--": "bad"})

    def test_task_exists_true(self):
        driver, _, _ = self._mock_driver([{"cnt": 1}])
        backend = self._make_backend(driver)
        assert backend.task_exists("T1") is True

    def test_task_exists_false(self):
        driver, _, _ = self._mock_driver([{"cnt": 0}])
        backend = self._make_backend(driver)
        assert backend.task_exists("T1") is False

    def test_update_task_returns_state_conflict(self):
        # First write returns no rows, then task_exists query returns cnt=1, then status query.
        driver, _, tx = self._mock_driver([])
        backend = self._make_backend(driver)
        tx.run.side_effect = [
            iter([]),
            iter([{"cnt": 1}]),
            iter([{"status": "REWORK"}]),
        ]

        result = backend.update_task("T1", {"status": "DONE"}, expected_current_status="ACTIVE")
        assert result["success"] is False
        assert result["error_code"] == "STATE_CONFLICT"
        assert result["actual_current_status"] == "REWORK"

    def test_context_manager(self):
        driver, _, _ = self._mock_driver()
        backend = self._make_backend(driver)
        with backend as b:
            assert b is backend
        driver.close.assert_called_once()

    def test_import_error_without_neo4j(self):
        with patch("governor.backend.neo4j_backend._Neo4jDriver", None):
            from governor.backend.neo4j_backend import Neo4jBackend
            with pytest.raises(ImportError, match="neo4j"):
                Neo4jBackend(uri="neo4j://localhost", user="x", password="x")

    def test_get_task_uses_relationship_limit_param(self):
        task_record = {
            "task": {"task_id": "T1", "status": "ACTIVE", "role": "DEV"},
            "out_rels": [],
            "in_rels": [],
        }
        driver, _, tx = self._mock_driver([task_record])
        backend = self._make_backend(driver)
        backend.get_task("T1")
        params_arg = tx.run.call_args[0][1]
        # fetch_limit = relationship_limit + 1 (extra row to detect truncation)
        assert "fetch_limit" in params_arg
        assert params_arg["fetch_limit"] == backend._relationship_limit + 1

    def test_record_transition_event_executes_write_query(self):
        driver, session, tx = self._mock_driver([{"event_id": "evt-1"}])
        backend = self._make_backend(driver)
        result = backend.record_transition_event(
            {
                "task_id": "T1",
                "transition_id": "T01",
                "from_state": "ACTIVE",
                "to_state": "READY_FOR_REVIEW",
                "calling_role": "EXECUTOR",
                "result": "PASS",
                "dry_run": False,
                "guard_results": [{"guard_id": "EG-01", "passed": True}],
                "occurred_at": "2026-03-02T00:00:00+00:00",
            }
        )
        assert result["success"] is True
        session.execute_write.assert_called_once()
        assert "TransitionEvent" in tx.run.call_args[0][0]

    def test_record_transition_event_includes_guard_results_in_query(self):
        """Verify the Cypher query contains FOREACH for GuardEvaluation (Bug 1 regression)."""
        driver, session, tx = self._mock_driver([{"event_id": "evt-2"}])
        backend = self._make_backend(driver)
        backend.record_transition_event(
            {
                "task_id": "T1",
                "transition_id": "T01",
                "from_state": "ACTIVE",
                "to_state": "READY_FOR_REVIEW",
                "calling_role": "EXECUTOR",
                "result": "PASS",
                "dry_run": False,
                "guard_results": [{"guard_id": "EG-01", "passed": True, "reason": "ok"}],
                "occurred_at": "2026-03-02T00:00:00+00:00",
            }
        )
        query_arg = tx.run.call_args[0][0]
        assert "FOREACH" in query_arg
        assert "GuardEvaluation" in query_arg
        params_arg = tx.run.call_args[0][1]
        assert "guard_results" in params_arg
        assert len(params_arg["guard_results"]) == 1

    def test_normalize_task_field_rejects_oversized_string(self):
        """Verify ValueError for strings exceeding max size (Bug 4)."""
        from governor.backend.neo4j_backend import _normalize_task_field, _MAX_FIELD_SIZE
        oversized = "x" * (_MAX_FIELD_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            _normalize_task_field("content", oversized)

    def test_normalize_task_field_accepts_normal_string(self):
        """Normal strings should pass through (Bug 4 regression)."""
        from governor.backend.neo4j_backend import _normalize_task_field
        assert _normalize_task_field("content", "hello world") == "hello world"
        assert _normalize_task_field("status", "active") == "ACTIVE"
        assert _normalize_task_field("content", None) is None
