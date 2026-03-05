"""MCP tool definitions for Governor.

Exposes Governor's core API as MCP tools:

- ``governor_transition_task`` — execute or dry-run a state transition
- ``governor_get_available_transitions`` — query possible transitions
- ``governor_get_task_audit_trail`` — fetch persisted transition events
- ``governor_get_guard_failure_hotspots`` — rank guards by failures
- ``governor_get_rework_lineage`` — reconstruct rework cycles for a task
- ``governor_get_policy_coverage`` — pass/fail coverage totals per guard

Usage::

    pip install ai-governor[mcp]

    from governor.mcp.tools import create_governor_tools
    tools = create_governor_tools(engine)

These tools can be registered with any MCP server implementation.
"""

from typing import Any, Dict, List, Optional

from governor.engine.transition_engine import TransitionEngine


def create_governor_tools(engine: TransitionEngine) -> List[Dict[str, Any]]:
    """Create MCP tool definitions wrapping a TransitionEngine.

    Args:
        engine: A configured TransitionEngine instance.

    Returns:
        List of MCP tool definition dicts, each with 'name', 'description',
        'input_schema', and 'handler' keys.
    """

    def _handle_transition_task(
        task_id: str,
        target_state: str,
        calling_role: str,
        dry_run: bool = False,
        transition_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return engine.transition_task(
            task_id=task_id,
            target_state=target_state,
            calling_role=calling_role,
            dry_run=dry_run,
            transition_params=transition_params,
        )

    def _handle_get_available_transitions(
        task_id: str,
        calling_role: str,
    ) -> Dict[str, Any]:
        return engine.get_available_transitions(
            task_id=task_id,
            calling_role=calling_role,
        )

    def _handle_get_task_audit_trail(task_id: str, limit: int = 50) -> Dict[str, Any]:
        return {
            "task_id": task_id,
            "events": engine.get_task_audit_trail(task_id=task_id, limit=limit),
        }

    def _handle_get_guard_failure_hotspots(limit: int = 10) -> Dict[str, Any]:
        return {"hotspots": engine.get_guard_failure_hotspots(limit=limit)}

    def _handle_get_policy_coverage() -> Dict[str, Any]:
        return engine.get_policy_coverage()

    def _handle_get_rework_lineage(task_id: str) -> Dict[str, Any]:
        return engine.get_rework_lineage(task_id=task_id)

    return [
        {
            "name": "governor_transition_task",
            "description": (
                "Execute or dry-run a state transition for a task. "
                "Validates role authorization, evaluates all registered guards, and "
                "applies the state change atomically if all guards pass. "
                "Returns a result dict with 'result' ('PASS'/'FAIL'), 'guard_results' "
                "(per-guard verdicts with fix hints), and 'events_fired'. "
                "Each guard_result includes: guard_id, passed (bool), reason, fix_hint, "
                "and warning (bool). A warning=true guard passed but flagged a non-blocking "
                "advisory — the transition still succeeds, but the caller should address "
                "the concern. "
                "Use dry_run=true to preview guard outcomes without mutating state. "
                "Example: transition_task('TASK_001', 'READY_FOR_REVIEW', 'EXECUTOR') "
                "returns FAIL with guard_results showing exactly which guards blocked and why."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task identifier (e.g. 'TASK_001')",
                        "minLength": 1,
                    },
                    "target_state": {
                        "type": "string",
                        "description": "Target state to transition to",
                        "enum": [
                            "PENDING", "ACTIVE", "READY_FOR_REVIEW",
                            "READY_FOR_GOVERNOR", "COMPLETED", "REWORK",
                            "BLOCKED", "FAILED", "ARCHIVED",
                        ],
                    },
                    "calling_role": {
                        "type": "string",
                        "description": "Role attempting the transition (e.g. 'EXECUTOR', 'REVIEWER')",
                        "minLength": 1,
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, evaluate guards without applying state change. Defaults to false.",
                        "default": False,
                    },
                    "transition_params": {
                        "type": "object",
                        "description": "Optional context passed to guards (e.g. project_root for deliverable checks).",
                        "properties": {
                            "project_root": {
                                "type": "string",
                                "description": "Workspace root used for deliverable checks.",
                            },
                            "deliverable_search_roots": {
                                "type": "array",
                                "description": "Additional subdirectories under project_root to search for deliverables.",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["task_id", "target_state", "calling_role"],
            },
            "handler": _handle_transition_task,
        },
        {
            "name": "governor_get_available_transitions",
            "description": (
                "Query which transitions are possible for a task given the calling role. "
                "Returns the task's current state and a list of reachable transitions, each "
                "annotated with guard readiness: guards_total, guards_met, guards_missing "
                "(with fix hints), guard_warnings (guards that passed but flagged non-blocking "
                "advisories), warnings_count, and a boolean 'ready' flag. "
                "Warnings do not block the transition but indicate concerns the agent should "
                "address. "
                "Use this to show the agent what it needs to fix before submitting. "
                "Example: get_available_transitions('TASK_001', 'EXECUTOR') might show "
                "READY_FOR_REVIEW is reachable but guards_missing=['EG-01: No self-review']."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task identifier (e.g. 'TASK_001')",
                        "minLength": 1,
                    },
                    "calling_role": {
                        "type": "string",
                        "description": "Role querying transitions (e.g. 'EXECUTOR', 'REVIEWER')",
                        "minLength": 1,
                    },
                },
                "required": ["task_id", "calling_role"],
            },
            "handler": _handle_get_available_transitions,
        },
        {
            "name": "governor_get_task_audit_trail",
            "description": (
                "Fetch the transition audit trail for a task — every transition attempt "
                "(PASS and FAIL) with embedded guard evaluations, timestamps, and calling roles. "
                "Returns events ordered newest-first. "
                "Use this to understand why a task is stuck or to review its full lifecycle history."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task identifier (e.g. 'TASK_001')",
                        "minLength": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events to return (default 50, min 1)",
                        "default": 50,
                        "minimum": 1,
                    },
                },
                "required": ["task_id"],
            },
            "handler": _handle_get_task_audit_trail,
        },
        {
            "name": "governor_get_guard_failure_hotspots",
            "description": (
                "Rank guards by failure count across all recorded transition events. "
                "Returns a list of {guard_id, evaluations, failures} sorted by most failures. "
                "Use this to identify which guards are blocking agents most often — "
                "high failure counts may indicate unclear requirements or missing tooling."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max guards to return (default 10, min 1)",
                        "default": 10,
                        "minimum": 1,
                    },
                },
                "required": [],
            },
            "handler": _handle_get_guard_failure_hotspots,
        },
        {
            "name": "governor_get_rework_lineage",
            "description": (
                "Reconstruct the full transition lineage for a task, with rework cycle count. "
                "Returns {task_id, rework_count, lineage: [{transition_id, from_state, to_state, occurred_at}]}. "
                "Use this to understand churn — how many times a task bounced between REWORK and resubmission."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task identifier (e.g. 'TASK_001')",
                        "minLength": 1,
                    },
                },
                "required": ["task_id"],
            },
            "handler": _handle_get_rework_lineage,
        },
        {
            "name": "governor_get_policy_coverage",
            "description": (
                "Return guard evaluation coverage across all recorded transitions. "
                "Shows per-guard {guard_id, evaluations, passes, fails} plus aggregate totals. "
                "Use this to verify that all guards are being exercised and to spot guards "
                "with 100% pass rates (may indicate the guard is too lenient)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "handler": _handle_get_policy_coverage,
        },
    ]
