"""Tests for the backend abstraction layer."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from governor.backend.memory_backend import MemoryBackend


class TestMemoryBackend:
    def setup_method(self):
        self.backend = MemoryBackend()
        self.backend.create_task({
            "task_id": "TASK_001",
            "task_name": "Test Task",
            "task_type": "IMPLEMENTATION",
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "Implement the feature.",
        })

    def test_create_task(self):
        result = self.backend.create_task({
            "task_id": "TASK_002",
            "task_name": "Another Task",
            "task_type": "INVESTIGATION",
            "role": "ANALYST",
            "status": "ACTIVE",
            "priority": "MEDIUM",
            "content": "Investigate the issue.",
        })
        assert result["task_id"] == "TASK_002"
        assert self.backend.task_exists("TASK_002")

    def test_create_task_duplicate_id_raises(self):
        with pytest.raises(ValueError, match="Task already exists"):
            self.backend.create_task({
                "task_id": "TASK_001",
                "task_name": "Duplicate",
                "task_type": "IMPLEMENTATION",
                "role": "DEVELOPER",
                "status": "ACTIVE",
                "priority": "HIGH",
                "content": "Duplicate create should fail.",
            })

    def test_get_task(self):
        data = self.backend.get_task("TASK_001")
        assert data["task"]["task_id"] == "TASK_001"
        assert data["task"]["status"] == "ACTIVE"
        assert isinstance(data["relationships"], list)

    def test_get_task_not_found(self):
        with pytest.raises(ValueError, match="Task not found"):
            self.backend.get_task("NONEXISTENT")

    def test_update_task(self):
        result = self.backend.update_task("TASK_001", {"status": "ACTIVE"})
        assert result["success"] is True
        assert result["new_status"] == "ACTIVE"

        data = self.backend.get_task("TASK_001")
        assert data["task"]["status"] == "ACTIVE"

    def test_update_task_with_expected_current_status_conflict(self):
        result = self.backend.update_task(
            "TASK_001",
            {"status": "READY_FOR_REVIEW"},
            expected_current_status="REWORK",
        )
        assert result["success"] is False
        assert result["error_code"] == "STATE_CONFLICT"

    def test_update_task_clear_property(self):
        self.backend.update_task("TASK_001", {"submitted_date": "2026-01-01"})
        self.backend.update_task("TASK_001", {"submitted_date": None})
        data = self.backend.get_task("TASK_001")
        assert "submitted_date" not in data["task"]

    def test_update_task_not_found(self):
        with pytest.raises(ValueError, match="Task not found"):
            self.backend.update_task("NONEXISTENT", {"status": "ACTIVE"})

    def test_task_exists(self):
        assert self.backend.task_exists("TASK_001") is True
        assert self.backend.task_exists("NONEXISTENT") is False

    def test_add_and_get_reviews(self):
        self.backend.add_review("TASK_001", {
            "review_id": "REV_001",
            "review_type": "SELF_REVIEW",
            "rating": 8.0,
        })
        reviews = self.backend.get_reviews_for_task("TASK_001")
        assert len(reviews) == 1
        assert reviews[0]["review_type"] == "SELF_REVIEW"

    def test_add_and_get_reports(self):
        self.backend.add_report("TASK_001", {
            "report_id": "RPT_001",
            "report_type": "INVESTIGATION",
        })
        reports = self.backend.get_reports_for_task("TASK_001")
        assert len(reports) == 1
        assert reports[0]["report_type"] == "INVESTIGATION"

    def test_add_handoff_shows_in_relationships(self):
        self.backend.add_handoff("TASK_001", {
            "handoff_id": "HO_001",
            "from_role": "REVIEWER",
            "to_role": "DEVELOPER",
        })
        data = self.backend.get_task("TASK_001")
        handoff_rels = [r for r in data["relationships"] if r["type"] == "HANDOFF_TO"]
        assert len(handoff_rels) == 1
        assert handoff_rels[0]["node"]["from_role"] == "REVIEWER"

    def test_relationships_include_all_types(self):
        self.backend.add_review("TASK_001", {"review_id": "R1", "review_type": "SELF_REVIEW"})
        self.backend.add_report("TASK_001", {"report_id": "RPT1", "report_type": "SUMMARY"})
        self.backend.add_handoff("TASK_001", {"handoff_id": "H1", "from_role": "A", "to_role": "B"})

        data = self.backend.get_task("TASK_001")
        types = {r["type"] for r in data["relationships"]}
        assert "HAS_REVIEW" in types
        assert "REPORTS_ON" in types
        assert "HANDOFF_TO" in types

    def test_get_all_tasks(self):
        tasks = self.backend.get_all_tasks()
        assert "TASK_001" in tasks

    def test_transition_event_analytics(self):
        self.backend.record_transition_event(
            {
                "task_id": "TASK_001",
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
        self.backend.record_transition_event(
            {
                "task_id": "TASK_001",
                "transition_id": "T03",
                "from_state": "READY_FOR_REVIEW",
                "to_state": "REWORK",
                "calling_role": "REVIEWER",
                "result": "PASS",
                "dry_run": False,
                "guard_results": [{"guard_id": "EG-01", "passed": False}],
                "occurred_at": "2026-03-02T00:01:00+00:00",
            }
        )

        audit = self.backend.get_task_audit_trail("TASK_001")
        assert len(audit) == 2
        hotspots = self.backend.get_guard_failure_hotspots(limit=5)
        assert hotspots[0]["guard_id"] == "EG-01"
        coverage = self.backend.get_policy_coverage()
        assert coverage["totals"]["evaluations"] == 2
        lineage = self.backend.get_rework_lineage("TASK_001")
        assert lineage["rework_count"] == 1
