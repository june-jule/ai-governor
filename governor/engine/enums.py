"""Type-safe enumerations for Governor engine constants.

Replaces magic strings with proper enums for guard IDs, task states,
transition results, and error codes. Use these in application code for
IDE auto-complete and refactoring safety.
"""

from enum import Enum


class TaskState(str, Enum):
    """Legal task states defined by the state machine."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    READY_FOR_GOVERNOR = "READY_FOR_GOVERNOR"
    COMPLETED = "COMPLETED"
    REWORK = "REWORK"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class TransitionResult(str, Enum):
    """Overall result of a transition attempt."""

    PASS = "PASS"
    FAIL = "FAIL"


class ErrorCode(str, Enum):
    """Error codes returned by transition_task()."""

    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    BACKEND_ERROR = "BACKEND_ERROR"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    ROLE_NOT_AUTHORIZED = "ROLE_NOT_AUTHORIZED"
    GUARD_NOT_FOUND = "GUARD_NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    EVENT_WRITE_FAILED = "EVENT_WRITE_FAILED"
    CRUD_FAILED = "CRUD_FAILED"
    RATE_LIMITED = "RATE_LIMITED"


class GuardID(str, Enum):
    """Built-in executor guard identifiers (EG-01 through EG-08)."""

    SELF_REVIEW_EXISTS = "EG-01"
    REPORT_EXISTS = "EG-02"
    DELIVERABLES_EXIST = "EG-03"
    NO_IMPLIED_DEPLOYS = "EG-04"
    NO_SECRETS_IN_CONTENT = "EG-05"
    DEPLOY_ROLLBACK_PLAN = "EG-06"
    AUDIT_MULTI_SOURCE = "EG-07"
    IMPLEMENTATION_TESTS = "EG-08"
