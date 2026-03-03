"""Governor transition engine — core state machine enforcement."""

from governor.engine.transition_engine import (
    TransitionEngine,
    GuardContext,
    GuardResult,
    configure,
    transition_task,
    get_available_transitions,
    register_guard,
)
from governor.engine.validation import validate_state_machine
from governor.engine.async_engine import AsyncTransitionEngine
from governor.engine.enums import (
    TaskState,
    TransitionResult,
    ErrorCode,
    GuardID,
)

__all__ = [
    "TransitionEngine",
    "AsyncTransitionEngine",
    "GuardContext",
    "GuardResult",
    "configure",
    "transition_task",
    "get_available_transitions",
    "register_guard",
    "validate_state_machine",
    "TaskState",
    "TransitionResult",
    "ErrorCode",
    "GuardID",
]
