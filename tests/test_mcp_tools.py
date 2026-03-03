"""Comprehensive tests for MCP tool schema and handlers.

Covers all 6 tools returned by create_governor_tools():
  1. governor_transition_task
  2. governor_get_available_transitions
  3. governor_get_task_audit_trail
  4. governor_get_guard_failure_hotspots
  5. governor_get_rework_lineage
  6. governor_get_policy_coverage
"""

import pytest

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
from governor.mcp.tools import create_governor_tools

import governor.guards.executor_guards  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TOOL_NAMES = [
    "governor_transition_task",
    "governor_get_available_transitions",
    "governor_get_task_audit_trail",
    "governor_get_guard_failure_hotspots",
    "governor_get_rework_lineage",
    "governor_get_policy_coverage",
]


def _make_engine(**kwargs):
    """Create a fresh MemoryBackend + TransitionEngine pair."""
    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEV": "EXECUTOR", "DEVELOPER": "EXECUTOR"},
        **kwargs,
    )
    return backend, engine


def _make_tools():
    """Create tools and return (backend, engine, tools_dict)."""
    backend, engine = _make_engine()
    tools_list = create_governor_tools(engine)
    tools = {t["name"]: t for t in tools_list}
    return backend, engine, tools


def _create_active_task(backend, task_id="TASK_001", task_type="IMPLEMENTATION"):
    """Create a standard ACTIVE task with test references in content."""
    backend.create_task({
        "task_id": task_id,
        "task_name": f"Test task {task_id}",
        "task_type": task_type,
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Implement feature X. Add tests to verify correctness.",
    })


def _prepare_submittable_task(backend, task_id="TASK_001", task_type="IMPLEMENTATION"):
    """Create an ACTIVE task with self-review and report so guards pass."""
    _create_active_task(backend, task_id=task_id, task_type=task_type)
    backend.add_review(task_id, {"review_type": "SELF_REVIEW", "rating": 8.0})
    backend.add_report(task_id, {"report_type": task_type, "content": "Done."})


# ===========================================================================
# Schema / structure tests
# ===========================================================================


class TestToolSchema:
    """Verify the shape and count of tools returned by create_governor_tools."""

    def test_tool_count_is_six(self):
        _, engine = _make_engine()
        tools = create_governor_tools(engine)
        assert len(tools) == 6

    def test_all_tool_names_present(self):
        _, engine = _make_engine()
        tools = create_governor_tools(engine)
        names = {t["name"] for t in tools}
        for expected in TOOL_NAMES:
            assert expected in names, f"Missing tool: {expected}"

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_has_required_keys(self, tool_name):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        tool = tools[tool_name]
        for key in ("name", "description", "input_schema", "handler"):
            assert key in tool, f"Tool '{tool_name}' missing key '{key}'"

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_description_is_nonempty_string(self, tool_name):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        desc = tools[tool_name]["description"]
        assert isinstance(desc, str)
        assert len(desc) > 0

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_handler_is_callable(self, tool_name):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        assert callable(tools[tool_name]["handler"])

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_input_schema_has_type_object(self, tool_name):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools[tool_name]["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

    def test_transition_tool_required_fields(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools["governor_transition_task"]["input_schema"]
        assert set(schema["required"]) == {"task_id", "target_state", "calling_role"}

    def test_transition_tool_has_dry_run_property(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        props = tools["governor_transition_task"]["input_schema"]["properties"]
        assert "dry_run" in props
        assert props["dry_run"]["type"] == "boolean"

    def test_transition_tool_has_transition_params_property(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        props = tools["governor_transition_task"]["input_schema"]["properties"]
        assert "transition_params" in props
        assert props["transition_params"]["type"] == "object"
        assert props["transition_params"]["additionalProperties"] is False
        assert "project_root" in props["transition_params"]["properties"]
        assert "deliverable_search_roots" in props["transition_params"]["properties"]

    def test_available_transitions_required_fields(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools["governor_get_available_transitions"]["input_schema"]
        assert set(schema["required"]) == {"task_id", "calling_role"}

    def test_audit_trail_required_fields(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools["governor_get_task_audit_trail"]["input_schema"]
        assert "task_id" in schema["required"]

    def test_audit_trail_has_limit_property(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        props = tools["governor_get_task_audit_trail"]["input_schema"]["properties"]
        assert "limit" in props
        assert props["limit"]["type"] == "integer"

    def test_hotspots_required_fields_is_empty(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools["governor_get_guard_failure_hotspots"]["input_schema"]
        assert schema["required"] == []

    def test_hotspots_has_limit_property(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        props = tools["governor_get_guard_failure_hotspots"]["input_schema"]["properties"]
        assert "limit" in props

    def test_rework_lineage_required_fields(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools["governor_get_rework_lineage"]["input_schema"]
        assert "task_id" in schema["required"]

    def test_policy_coverage_required_fields_is_empty(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        schema = tools["governor_get_policy_coverage"]["input_schema"]
        assert schema["required"] == []

    def test_policy_coverage_properties_is_empty(self):
        _, engine = _make_engine()
        tools = {t["name"]: t for t in create_governor_tools(engine)}
        props = tools["governor_get_policy_coverage"]["input_schema"]["properties"]
        assert props == {}


# ===========================================================================
# governor_transition_task tests
# ===========================================================================


class TestTransitionTaskTool:
    """Tests for the governor_transition_task MCP tool handler."""

    def test_successful_transition(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
        )
        assert result["result"] == "PASS"
        assert result["from_state"] == "ACTIVE"
        assert result["to_state"] == "READY_FOR_REVIEW"
        assert result["dry_run"] is False

        # Verify state actually changed
        task_data = backend.get_task("TASK_001")
        assert task_data["task"]["status"] == "READY_FOR_REVIEW"

    def test_successful_transition_with_transition_params(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
            transition_params={"project_root": "."},
        )
        assert result["result"] == "PASS"

    def test_failed_guard_transition(self):
        """Task without self-review should fail EG-01."""
        backend, _, tools = _make_tools()
        _create_active_task(backend)
        # No self-review added, so EG-01 should block

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
        )
        assert result["result"] == "FAIL"
        assert result["rejection_reason"] is not None

        # Verify at least one guard failed
        failed_guards = [g for g in result["guard_results"] if not g["passed"]]
        assert len(failed_guards) >= 1

        # EG-01 should be among the failures
        failed_ids = {g["guard_id"] for g in failed_guards}
        assert "EG-01" in failed_ids

    def test_dry_run_does_not_apply_state_change(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
            dry_run=True,
        )
        assert result["result"] == "PASS"
        assert result["dry_run"] is True

        # State must remain ACTIVE
        task_data = backend.get_task("TASK_001")
        assert task_data["task"]["status"] == "ACTIVE"

    def test_dry_run_with_failing_guards(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)
        # No review -> guard fails

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
            dry_run=True,
        )
        assert result["result"] == "FAIL"
        assert result["dry_run"] is True

        # State must remain ACTIVE
        task_data = backend.get_task("TASK_001")
        assert task_data["task"]["status"] == "ACTIVE"

    def test_task_not_found(self):
        _, _, tools = _make_tools()

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="NONEXISTENT_999",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
        )
        assert result["result"] == "FAIL"
        assert result["error_code"] == "TASK_NOT_FOUND"

    def test_role_not_authorized(self):
        """REVIEWER cannot perform ACTIVE -> READY_FOR_REVIEW (only EXECUTOR)."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="REVIEWER",
        )
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ROLE_NOT_AUTHORIZED"

        # State unchanged
        task_data = backend.get_task("TASK_001")
        assert task_data["task"]["status"] == "ACTIVE"

    def test_illegal_transition(self):
        """ACTIVE -> COMPLETED is not a defined transition."""
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="COMPLETED",
            calling_role="EXECUTOR",
        )
        assert result["result"] == "FAIL"
        assert result["error_code"] == "ILLEGAL_TRANSITION"

    def test_temporal_fields_set_on_submit(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
        )
        assert result["result"] == "PASS"
        assert "submitted_date" in result["temporal_updates"]

    def test_full_lifecycle_via_tool(self):
        """ACTIVE -> READY_FOR_REVIEW -> COMPLETED through the tool handler."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)
        handler = tools["governor_transition_task"]["handler"]

        # Submit
        r1 = handler(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        assert r1["result"] == "PASS"

        # Approve
        r2 = handler(task_id="TASK_001", target_state="COMPLETED", calling_role="REVIEWER")
        assert r2["result"] == "PASS"
        assert "completed_date" in r2["temporal_updates"]

        task_data = backend.get_task("TASK_001")
        assert task_data["task"]["status"] == "COMPLETED"

    def test_rework_cycle_via_tool(self):
        """ACTIVE -> READY_FOR_REVIEW -> REWORK -> READY_FOR_REVIEW -> COMPLETED."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)
        handler = tools["governor_transition_task"]["handler"]

        # Submit
        r1 = handler(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        assert r1["result"] == "PASS"

        # Rework
        r2 = handler(task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER")
        assert r2["result"] == "PASS"

        # Resubmit
        r3 = handler(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        assert r3["result"] == "PASS"

        # Approve
        r4 = handler(task_id="TASK_001", target_state="COMPLETED", calling_role="REVIEWER")
        assert r4["result"] == "PASS"

        task_data = backend.get_task("TASK_001")
        assert task_data["task"]["status"] == "COMPLETED"

    def test_guard_results_populated_on_pass(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_transition_task"]["handler"]
        result = handler(
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
        )
        assert result["result"] == "PASS"
        # T01 has 8 guards (EG-01 through EG-08, including EG-05)
        assert len(result["guard_results"]) == 8
        for gr in result["guard_results"]:
            assert "guard_id" in gr
            assert "passed" in gr
            assert gr["passed"] is True


# ===========================================================================
# governor_get_available_transitions tests
# ===========================================================================


class TestGetAvailableTransitionsTool:
    """Tests for the governor_get_available_transitions MCP tool handler."""

    def test_shows_transitions_for_active_task(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="EXECUTOR")

        assert result["task_id"] == "TASK_001"
        assert result["current_state"] == "ACTIVE"
        assert "transitions" in result
        targets = {t["target_state"] for t in result["transitions"]}
        assert "READY_FOR_REVIEW" in targets

    def test_shows_guard_missing_details(self):
        """Without self-review, guards_missing should include EG-01."""
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="EXECUTOR")

        submit_transition = next(
            t for t in result["transitions"] if t["target_state"] == "READY_FOR_REVIEW"
        )
        # EG-01 should fail because no self-review
        missing_ids = {g["guard_id"] for g in submit_transition["guards_missing"]}
        assert "EG-01" in missing_ids
        assert submit_transition["ready"] is False

    def test_ready_true_when_all_guards_pass(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="EXECUTOR")

        submit_transition = next(
            t for t in result["transitions"] if t["target_state"] == "READY_FOR_REVIEW"
        )
        assert submit_transition["ready"] is True
        assert submit_transition["role_authorized"] is True
        assert submit_transition["guards_met"] == submit_transition["guards_total"]

    def test_role_authorized_false_for_wrong_role(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="REVIEWER")

        submit_transition = next(
            t for t in result["transitions"] if t["target_state"] == "READY_FOR_REVIEW"
        )
        assert submit_transition["role_authorized"] is False
        assert submit_transition["ready"] is False

    def test_task_not_found(self):
        _, _, tools = _make_tools()

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="NONEXISTENT_999", calling_role="EXECUTOR")

        assert "error" in result
        assert result["error"] == "TASK_NOT_FOUND"

    def test_ready_for_review_shows_rework_and_completed(self):
        """From READY_FOR_REVIEW, REVIEWER should see COMPLETED and REWORK."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        # Move to READY_FOR_REVIEW
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001",
            target_state="READY_FOR_REVIEW",
            calling_role="EXECUTOR",
        )

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="REVIEWER")

        assert result["current_state"] == "READY_FOR_REVIEW"
        targets = {t["target_state"] for t in result["transitions"]}
        assert "COMPLETED" in targets
        assert "REWORK" in targets

    def test_completed_task_has_no_transitions(self):
        """COMPLETED is terminal -- no outbound transitions."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        # ACTIVE -> READY_FOR_REVIEW -> COMPLETED
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="COMPLETED", calling_role="REVIEWER"
        )

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="REVIEWER")

        assert result["current_state"] == "COMPLETED"
        assert result["transitions"] == []

    def test_transition_includes_description(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_get_available_transitions"]["handler"]
        result = handler(task_id="TASK_001", calling_role="EXECUTOR")

        submit_transition = next(
            t for t in result["transitions"] if t["target_state"] == "READY_FOR_REVIEW"
        )
        assert isinstance(submit_transition["description"], str)
        assert len(submit_transition["description"]) > 0


# ===========================================================================
# governor_get_task_audit_trail tests
# ===========================================================================


class TestGetTaskAuditTrailTool:
    """Tests for the governor_get_task_audit_trail MCP tool handler."""

    def test_returns_events_after_transitions(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        # Perform a transition to generate events
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_task_audit_trail"]["handler"]
        result = handler(task_id="TASK_001")

        assert result["task_id"] == "TASK_001"
        assert "events" in result
        assert len(result["events"]) >= 1

        # Each event should have transition metadata
        event = result["events"][0]
        assert "task_id" in event
        assert "transition_id" in event
        assert "from_state" in event
        assert "to_state" in event
        assert "result" in event

    def test_empty_for_new_task(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_get_task_audit_trail"]["handler"]
        result = handler(task_id="TASK_001")

        assert result["task_id"] == "TASK_001"
        assert result["events"] == []

    def test_respects_limit_param(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        # Generate multiple events: submit, rework, resubmit
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER"
        )
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_task_audit_trail"]["handler"]

        # Request only 2 events
        result = handler(task_id="TASK_001", limit=2)
        assert len(result["events"]) == 2

    def test_default_limit_returns_all_events(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER"
        )

        handler = tools["governor_get_task_audit_trail"]["handler"]
        result = handler(task_id="TASK_001")

        # Default limit=50, so both events should be included
        assert len(result["events"]) >= 2

    def test_includes_guard_results_in_events(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_task_audit_trail"]["handler"]
        result = handler(task_id="TASK_001")

        event = result["events"][0]
        assert "guard_results" in event
        assert len(event["guard_results"]) > 0

    def test_records_failed_transitions(self):
        """Failed transitions should also appear in the audit trail."""
        backend, _, tools = _make_tools()
        _create_active_task(backend)
        # No review -> will fail

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_task_audit_trail"]["handler"]
        result = handler(task_id="TASK_001")

        assert len(result["events"]) >= 1
        # The event should have result=FAIL
        fail_events = [e for e in result["events"] if e["result"] == "FAIL"]
        assert len(fail_events) >= 1

    def test_events_are_task_scoped(self):
        """Events for TASK_001 should not include events for TASK_002."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend, task_id="TASK_001")
        _prepare_submittable_task(backend, task_id="TASK_002")

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )
        tools["governor_transition_task"]["handler"](
            task_id="TASK_002", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_task_audit_trail"]["handler"]
        result = handler(task_id="TASK_001")

        for event in result["events"]:
            assert event["task_id"] == "TASK_001"


# ===========================================================================
# governor_get_guard_failure_hotspots tests
# ===========================================================================


class TestGetGuardFailureHotspotsTool:
    """Tests for the governor_get_guard_failure_hotspots MCP tool handler."""

    def test_returns_hotspot_data(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        # Attempt transition without review -> generates guard failures
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_guard_failure_hotspots"]["handler"]
        result = handler()

        assert "hotspots" in result
        assert len(result["hotspots"]) > 0

        # Each hotspot should have guard_id, evaluations, failures
        hotspot = result["hotspots"][0]
        assert "guard_id" in hotspot
        assert "evaluations" in hotspot
        assert "failures" in hotspot
        assert hotspot["failures"] >= 1

    def test_empty_when_no_events(self):
        _, _, tools = _make_tools()

        handler = tools["governor_get_guard_failure_hotspots"]["handler"]
        result = handler()

        assert "hotspots" in result
        assert result["hotspots"] == []

    def test_respects_limit(self):
        backend, _, tools = _make_tools()

        # Create multiple tasks and fail them to generate varied guard failures
        for i in range(3):
            task_id = f"TASK_HOT_{i}"
            _create_active_task(backend, task_id=task_id)
            tools["governor_transition_task"]["handler"](
                task_id=task_id, target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
            )

        handler = tools["governor_get_guard_failure_hotspots"]["handler"]
        result = handler(limit=2)

        assert len(result["hotspots"]) <= 2

    def test_hotspots_ranked_by_failure_count(self):
        backend, _, tools = _make_tools()

        # Generate multiple failures
        for i in range(3):
            task_id = f"TASK_RANK_{i}"
            _create_active_task(backend, task_id=task_id)
            tools["governor_transition_task"]["handler"](
                task_id=task_id, target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
            )

        handler = tools["governor_get_guard_failure_hotspots"]["handler"]
        result = handler()

        hotspots = result["hotspots"]
        if len(hotspots) >= 2:
            # Should be sorted descending by failures
            for i in range(len(hotspots) - 1):
                assert hotspots[i]["failures"] >= hotspots[i + 1]["failures"]

    def test_includes_both_pass_and_fail_counts(self):
        backend, _, tools = _make_tools()

        # First: fail (no review)
        _create_active_task(backend, task_id="TASK_MIX_1")
        tools["governor_transition_task"]["handler"](
            task_id="TASK_MIX_1", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        # Second: pass (with review)
        _prepare_submittable_task(backend, task_id="TASK_MIX_2")
        tools["governor_transition_task"]["handler"](
            task_id="TASK_MIX_2", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_guard_failure_hotspots"]["handler"]
        result = handler()

        # EG-01 should show in hotspots with at least 2 evaluations, 1 failure
        eg01 = next((h for h in result["hotspots"] if h["guard_id"] == "EG-01"), None)
        assert eg01 is not None
        assert eg01["evaluations"] >= 2
        assert eg01["failures"] >= 1


# ===========================================================================
# governor_get_rework_lineage tests
# ===========================================================================


class TestGetReworkLineageTool:
    """Tests for the governor_get_rework_lineage MCP tool handler."""

    def test_tracks_rework_count_correctly(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        transition = tools["governor_transition_task"]["handler"]

        # Submit -> Rework -> Resubmit -> Rework -> Resubmit
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER")
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER")
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")

        handler = tools["governor_get_rework_lineage"]["handler"]
        result = handler(task_id="TASK_001")

        assert result["task_id"] == "TASK_001"
        assert result["rework_count"] == 2

    def test_empty_for_new_task(self):
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        handler = tools["governor_get_rework_lineage"]["handler"]
        result = handler(task_id="TASK_001")

        assert result["task_id"] == "TASK_001"
        assert result["rework_count"] == 0
        assert result["lineage"] == []

    def test_zero_rework_when_no_rework_transition(self):
        """Submit and approve directly -- rework_count should be 0."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        transition = tools["governor_transition_task"]["handler"]
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_001", target_state="COMPLETED", calling_role="REVIEWER")

        handler = tools["governor_get_rework_lineage"]["handler"]
        result = handler(task_id="TASK_001")

        assert result["rework_count"] == 0

    def test_lineage_contains_pass_events_only(self):
        """Lineage should only contain PASS events (successful transitions)."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        transition = tools["governor_transition_task"]["handler"]
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER")

        handler = tools["governor_get_rework_lineage"]["handler"]
        result = handler(task_id="TASK_001")

        for entry in result["lineage"]:
            assert entry["result"] == "PASS"

    def test_lineage_entries_have_transition_metadata(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        transition = tools["governor_transition_task"]["handler"]
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")

        handler = tools["governor_get_rework_lineage"]["handler"]
        result = handler(task_id="TASK_001")

        assert len(result["lineage"]) >= 1
        entry = result["lineage"][0]
        assert "transition_id" in entry
        assert "from_state" in entry
        assert "to_state" in entry
        assert "result" in entry
        assert "occurred_at" in entry

    def test_single_rework_cycle(self):
        """One rework cycle: submit, rework, resubmit."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        transition = tools["governor_transition_task"]["handler"]
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER")
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")

        handler = tools["governor_get_rework_lineage"]["handler"]
        result = handler(task_id="TASK_001")

        assert result["rework_count"] == 1
        assert len(result["lineage"]) == 3


# ===========================================================================
# governor_get_policy_coverage tests
# ===========================================================================


class TestGetPolicyCoverageTool:
    """Tests for the governor_get_policy_coverage MCP tool handler."""

    def test_returns_guards_and_totals_after_transitions(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        # Generate guard evaluations via a transition
        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        assert "guards" in result
        assert "totals" in result
        assert len(result["guards"]) > 0

        totals = result["totals"]
        assert "evaluations" in totals
        assert "passes" in totals
        assert "fails" in totals
        assert totals["evaluations"] > 0

    def test_empty_coverage_before_any_transitions(self):
        _, _, tools = _make_tools()

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        assert result["guards"] == []
        assert result["totals"]["evaluations"] == 0
        assert result["totals"]["passes"] == 0
        assert result["totals"]["fails"] == 0

    def test_guard_entries_have_correct_structure(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        for guard in result["guards"]:
            assert "guard_id" in guard
            assert "evaluations" in guard
            assert "passes" in guard
            assert "fails" in guard

    def test_totals_are_sum_of_guards(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        sum_evals = sum(g["evaluations"] for g in result["guards"])
        sum_passes = sum(g["passes"] for g in result["guards"])
        sum_fails = sum(g["fails"] for g in result["guards"])

        assert result["totals"]["evaluations"] == sum_evals
        assert result["totals"]["passes"] == sum_passes
        assert result["totals"]["fails"] == sum_fails

    def test_coverage_accumulates_across_transitions(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend, task_id="TASK_COV_1")
        _prepare_submittable_task(backend, task_id="TASK_COV_2")

        transition = tools["governor_transition_task"]["handler"]
        transition(task_id="TASK_COV_1", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_COV_2", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        # EG-01 should have at least 2 evaluations (one per transition)
        eg01 = next((g for g in result["guards"] if g["guard_id"] == "EG-01"), None)
        assert eg01 is not None
        assert eg01["evaluations"] >= 2

    def test_coverage_tracks_failures(self):
        """Failed guard evaluations should appear in the fails count."""
        backend, _, tools = _make_tools()
        _create_active_task(backend)
        # No review -> EG-01 will fail

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        eg01 = next((g for g in result["guards"] if g["guard_id"] == "EG-01"), None)
        assert eg01 is not None
        assert eg01["fails"] >= 1

    def test_coverage_after_mixed_pass_and_fail(self):
        """One failing transition + one passing transition."""
        backend, _, tools = _make_tools()

        # Fail: no review
        _create_active_task(backend, task_id="TASK_FAIL")
        tools["governor_transition_task"]["handler"](
            task_id="TASK_FAIL", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        # Pass: with review
        _prepare_submittable_task(backend, task_id="TASK_PASS")
        tools["governor_transition_task"]["handler"](
            task_id="TASK_PASS", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        totals = result["totals"]
        assert totals["passes"] >= 1
        assert totals["fails"] >= 1
        assert totals["evaluations"] == totals["passes"] + totals["fails"]

    def test_guards_sorted_by_guard_id(self):
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        handler = tools["governor_get_policy_coverage"]["handler"]
        result = handler()

        guard_ids = [g["guard_id"] for g in result["guards"]]
        assert guard_ids == sorted(guard_ids)


# ===========================================================================
# Cross-tool integration tests
# ===========================================================================


class TestCrossToolIntegration:
    """Tests that verify multiple tools work together coherently."""

    def test_transition_generates_audit_trail(self):
        """A transition should produce events visible in the audit trail."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        audit = tools["governor_get_task_audit_trail"]["handler"](task_id="TASK_001")
        assert len(audit["events"]) >= 1

    def test_failed_transition_updates_hotspots(self):
        """A failed guard transition should show up in failure hotspots."""
        backend, _, tools = _make_tools()
        _create_active_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        hotspots = tools["governor_get_guard_failure_hotspots"]["handler"]()
        assert len(hotspots["hotspots"]) > 0
        failed_guard_ids = {h["guard_id"] for h in hotspots["hotspots"] if h["failures"] > 0}
        assert "EG-01" in failed_guard_ids

    def test_rework_lineage_matches_audit_trail_rework_events(self):
        """Rework count from lineage should match REWORK events in audit trail."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        transition = tools["governor_transition_task"]["handler"]
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")
        transition(task_id="TASK_001", target_state="REWORK", calling_role="REVIEWER")
        transition(task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR")

        lineage = tools["governor_get_rework_lineage"]["handler"](task_id="TASK_001")
        assert lineage["rework_count"] == 1

        audit = tools["governor_get_task_audit_trail"]["handler"](task_id="TASK_001")
        rework_events = [
            e for e in audit["events"]
            if e.get("to_state") == "REWORK" and e.get("result") == "PASS"
        ]
        assert len(rework_events) == lineage["rework_count"]

    def test_policy_coverage_reflects_transition_outcomes(self):
        """Coverage totals should reflect guard pass/fail from transitions."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state="READY_FOR_REVIEW", calling_role="EXECUTOR"
        )

        coverage = tools["governor_get_policy_coverage"]["handler"]()
        assert coverage["totals"]["evaluations"] > 0
        # All guards passed on this transition
        assert coverage["totals"]["passes"] > 0

    def test_available_transitions_then_execute(self):
        """Query available transitions, then successfully execute one."""
        backend, _, tools = _make_tools()
        _prepare_submittable_task(backend)

        available = tools["governor_get_available_transitions"]["handler"](
            task_id="TASK_001", calling_role="EXECUTOR"
        )
        ready_transitions = [t for t in available["transitions"] if t["ready"]]
        assert len(ready_transitions) >= 1

        target = ready_transitions[0]["target_state"]
        result = tools["governor_transition_task"]["handler"](
            task_id="TASK_001", target_state=target, calling_role="EXECUTOR"
        )
        assert result["result"] == "PASS"
