"""Governor — quality gate for AI agent output.

State machine enforcement with pluggable guards and swappable backends.
"""

__version__ = "0.3.0"

from governor.engine.transition_engine import (
    configure,
    transition_task,
    get_available_transitions,
    GuardContext,
    GuardResult,
    register_guard,
)

# Auto-register built-in guards so users don't need a manual import.
import governor.guards.executor_guards  # noqa: F401

__all__ = [
    "configure",
    "transition_task",
    "get_available_transitions",
    "GuardContext",
    "GuardResult",
    "register_guard",
]

# TypedDict definitions (requires typing_extensions on Python < 3.12).
# Lazy import to avoid hard dependency.
def __getattr__(name: str):  # type: ignore[override]
    _type_names = {
        "TaskDict", "GuardResultDict", "TransitionResultDict",
        "TransitionEventDict", "AvailableTransitionDict",
    }
    if name in _type_names:
        from governor import types as _types
        return getattr(_types, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
