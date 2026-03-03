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
                "Validates role authorization, evaluates all guards, and "
                "applies the state change if all guards pass."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task identifier"},
                    "target_state": {"type": "string", "description": "Target state (e.g. READY_FOR_REVIEW, COMPLETED)"},
                    "calling_role": {"type": "string", "description": "Role attempting the transition (e.g. EXECUTOR, REVIEWER)"},
                    "dry_run": {"type": "boolean", "description": "If true, evaluate guards without applying state change", "default": False},
                    "transition_params": {
                        "type": "object",
                        "description": (
                            "Optional transition context for guards. "
                            "Only project-local path hints are accepted."
                        ),
                        "properties": {
                            "project_root": {
                                "type": "string",
                                "description": "Workspace root used for deliverable checks.",
                            },
                            "deliverable_search_roots": {
                                "type": "array",
                                "description": "Optional additional subdirectories under project_root.",
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
                "Query what transitions are possible for a task given the calling role. "
                "Returns guard status for each transition so the agent knows what's blocking."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task identifier"},
                    "calling_role": {"type": "string", "description": "Role querying transitions"},
                },
                "required": ["task_id", "calling_role"],
            },
            "handler": _handle_get_available_transitions,
        },
        {
            "name": "governor_get_task_audit_trail",
            "description": (
                "Return transition audit events for a task, including guard evaluations "
                "for each transition attempt."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task identifier"},
                    "limit": {"type": "integer", "description": "Max events to return", "default": 50},
                },
                "required": ["task_id"],
            },
            "handler": _handle_get_task_audit_trail,
        },
        {
            "name": "governor_get_guard_failure_hotspots",
            "description": "Return guards with highest failure counts across transition events.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max guards to return", "default": 10},
                },
                "required": [],
            },
            "handler": _handle_get_guard_failure_hotspots,
        },
        {
            "name": "governor_get_rework_lineage",
            "description": (
                "Return a task's transition lineage with rework cycle count, useful for "
                "understanding churn."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task identifier"},
                },
                "required": ["task_id"],
            },
            "handler": _handle_get_rework_lineage,
        },
        {
            "name": "governor_get_policy_coverage",
            "description": "Return guard evaluation coverage and pass/fail totals.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "handler": _handle_get_policy_coverage,
        },
    ]
