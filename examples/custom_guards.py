#!/usr/bin/env python3
"""Custom guard registration and usage patterns.

Demonstrates:
  - Registering a custom guard with @register_guard
  - Creating guards that inspect task content
  - Creating guards that inspect relationships (reviews, handoffs)
  - Using fix_hint for actionable failure messages
  - Using warning=True for non-blocking advisories
  - Invoking custom guards manually for testing
  - Integrating custom guards into the state machine via JSON config

Run with:

    python examples/custom_guards.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import (
    TransitionEngine,
    GuardContext,
    GuardResult,
    register_guard,
)

# Import built-in guards first — custom registrations below will add to the registry
import governor.guards.executor_guards      # noqa: F401


# ---------------------------------------------------------------------------
# Example 1: Content length guard
# ---------------------------------------------------------------------------

@register_guard("CUSTOM-01")
def guard_content_minimum_length(ctx: GuardContext) -> GuardResult:
    """CUSTOM-01: Require task content to be at least 50 characters.

    Short task descriptions are often underspecified. This guard enforces
    a minimum length to encourage detailed task content.
    """
    content = ctx.task.get("content", "")
    if len(content) < 50:
        return GuardResult(
            "CUSTOM-01", False,
            f"Content too short: {len(content)} chars (minimum 50)",
            fix_hint="Add more detail to the task content",
        )
    return GuardResult("CUSTOM-01", True, f"Content length OK: {len(content)} chars")


# ---------------------------------------------------------------------------
# Example 2: Minimum self-review rating guard
# ---------------------------------------------------------------------------

@register_guard("CUSTOM-02")
def guard_min_self_review_rating(ctx: GuardContext) -> GuardResult:
    """CUSTOM-02: Self-review rating must be >= 7.0 to submit.

    Prevents executors from self-scoring low and still submitting for review.
    If the executor rates their own work below 7.0, they should improve it first.
    """
    for r in ctx.relationships:
        if r.get("type") != "HAS_REVIEW":
            continue
        node = r.get("node") or {}
        if node.get("review_type") == "SELF_REVIEW":
            rating = float(node.get("rating", 0))
            if rating >= 7.0:
                return GuardResult(
                    "CUSTOM-02", True,
                    f"Self-review rating {rating} meets minimum threshold",
                )
            return GuardResult(
                "CUSTOM-02", False,
                f"Self-review rating {rating} is below minimum 7.0",
                fix_hint="Improve work quality before submission, then update the self-review",
            )
    return GuardResult(
        "CUSTOM-02", False, "No self-review found",
        fix_hint="Create a self-review with a rating >= 7.0",
    )


# ---------------------------------------------------------------------------
# Example 3: Non-blocking warning guard
# ---------------------------------------------------------------------------

@register_guard("CUSTOM-03")
def guard_recommend_report(ctx: GuardContext) -> GuardResult:
    """CUSTOM-03: Recommend (but don't require) a linked report.

    Uses warning=True to pass the guard but surface an advisory message.
    The transition proceeds, but the caller sees the recommendation.
    """
    has_report = any(r.get("type") == "REPORTS_ON" for r in ctx.relationships)
    if has_report:
        return GuardResult("CUSTOM-03", True, "Report linked")
    return GuardResult(
        "CUSTOM-03", True,
        "No report linked (advisory — non-blocking)",
        fix_hint="Consider linking a report for better traceability",
        warning=True,
    )


# ---------------------------------------------------------------------------
# Demo: Test guards manually and via the engine
# ---------------------------------------------------------------------------

def main():
    print("Custom Guards Demo")
    print("=" * 60)

    backend = MemoryBackend()
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEVELOPER": "EXECUTOR"},
    )

    # --- Test CUSTOM-01: Content length ---
    # Create a task with very short content
    backend.create_task({
        "task_id": "TASK_SHORT",
        "task_name": "Short task",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "LOW",
        "content": "Do the thing.",
    })

    # Invoke the guard directly to test it in isolation
    task_data = backend.get_task("TASK_SHORT")
    ctx = GuardContext("TASK_SHORT", task_data)
    result = guard_content_minimum_length(ctx)

    print(f"\n--- CUSTOM-01: Content Length ---")
    print(f"Guard:  {result.guard_id}")
    print(f"Passed: {result.passed}")
    print(f"Reason: {result.reason}")
    if result.fix_hint:
        print(f"Fix:    {result.fix_hint}")

    # --- Test CUSTOM-02: Rating threshold ---
    # Add a low-rated self-review
    backend.add_review("TASK_SHORT", {
        "review_id": "REV_LOW",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 5.0,
        "content": "Work incomplete, known issues remain.",
    })

    task_data = backend.get_task("TASK_SHORT")
    ctx = GuardContext("TASK_SHORT", task_data)
    result = guard_min_self_review_rating(ctx)

    print(f"\n--- CUSTOM-02: Minimum Rating (low rating) ---")
    print(f"Passed: {result.passed}")
    print(f"Reason: {result.reason}")

    # --- Test CUSTOM-03: Warning guard ---
    result = guard_recommend_report(ctx)

    print(f"\n--- CUSTOM-03: Report Advisory (warning) ---")
    print(f"Passed:  {result.passed} (passes even without report)")
    print(f"Warning: {result.warning}")
    print(f"Reason:  {result.reason}")

    # --- Integration note ---
    print(f"\n{'=' * 60}")
    print("To use custom guards in the transition engine, add them to your")
    print("state_machine.json under the appropriate transition's guards list:")
    print()
    print('  "guards": ["EG-01", "EG-02", "CUSTOM-01", "CUSTOM-02", "CUSTOM-03"]')
    print()
    print("Guards are resolved from the registry by ID at evaluation time.")
    print("Any guard registered with @register_guard before engine use will")
    print("be available for any transition that references it.")
    print("=" * 60)


if __name__ == "__main__":
    main()
