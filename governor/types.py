"""TypedDict definitions for Governor data structures.

These types are provided for **documentation and IDE support only**.
Existing function signatures remain ``Dict[str, Any]`` for backward
compatibility — no runtime behaviour changes.

Requires ``typing_extensions`` on Python < 3.12.  Install via::

    pip install ai-governor[types]
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 12):
    from typing import NotRequired, TypedDict
else:
    try:
        from typing_extensions import NotRequired, TypedDict
    except ImportError:  # pragma: no cover
        raise ImportError(
            "governor.types requires 'typing_extensions' on Python < 3.12. "
            "Install it with: pip install typing_extensions"
        )


# ------------------------------------------------------------------
# Task
# ------------------------------------------------------------------

class TaskDict(TypedDict, total=False):
    """Shape of a task dict returned by ``GovernorBackend.get_task()``."""

    task_id: str
    task_name: str
    task_type: str
    role: str
    status: str
    priority: str
    content: str
    deliverables: str
    created_date: str
    last_updated: str
    submitted_date: NotRequired[str]
    completed_date: NotRequired[str]
    blocked_date: NotRequired[str]
    failed_date: NotRequired[str]
    blocking_reason: NotRequired[str]
    failure_reason: NotRequired[str]
    revision_count: NotRequired[int]


# ------------------------------------------------------------------
# Guard result
# ------------------------------------------------------------------

class GuardResultDict(TypedDict):
    """Shape of a single guard evaluation result."""

    guard_id: str
    passed: bool
    reason: str
    fix_hint: str
    warning: bool


# ------------------------------------------------------------------
# Transition result
# ------------------------------------------------------------------

class TransitionResultDict(TypedDict, total=False):
    """Shape of the dict returned by ``TransitionEngine.transition_task()``."""

    result: str
    transition_id: str
    from_state: str
    to_state: str
    task_id: str
    dry_run: bool
    guard_results: list[GuardResultDict]
    events_fired: NotRequired[list[str]]
    error: NotRequired[str]
    message: NotRequired[str]


# ------------------------------------------------------------------
# Transition event (audit trail)
# ------------------------------------------------------------------

class TransitionEventDict(TypedDict, total=False):
    """Shape of a transition event persisted by the backend."""

    event_id: str
    task_id: str
    transition_id: str
    from_state: str
    to_state: str
    calling_role: str
    result: str
    timestamp: str
    guard_results: list[GuardResultDict]
    dry_run: bool


# ------------------------------------------------------------------
# Available-transition entry
# ------------------------------------------------------------------

class AvailableTransitionDict(TypedDict):
    """One entry in ``get_available_transitions()`` response."""

    transition_id: str
    target_state: str
    description: str
    allowed_roles: list[str]
    role_authorized: bool
    guards_total: int
    guards_met: int
    guards_missing: list[GuardResultDict]
    guard_warnings: list[GuardResultDict]
    guard_mode: str
    warnings_count: int
    ready: bool
