#!/usr/bin/env python3
"""End-to-end demo: full task lifecycle through all governed transitions.

Demonstrates:
  - Creating a task in ACTIVE state
  - Checking available transitions before acting
  - Dry-run validation before committing
  - Adding a self-review (required by EG-01 submission guard)
  - Submitting for review (ACTIVE -> READY_FOR_REVIEW)
  - Reviewer approval (READY_FOR_REVIEW -> COMPLETED)
  - Inspecting temporal field updates (submitted_date, completed_date)
  - Handling guard failures with actionable fix hints

Uses MemoryBackend for zero-dependency execution. Neo4jBackend also supports
the same lifecycle helper methods used below (`create_task`, `add_report`,
`add_review`). Run with:

    python examples/full_task_lifecycle.py
"""

import sys
import os
import argparse

# Add parent directory so governor package is importable without installation
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine

# Import guard modules — guards register themselves at import time via @register_guard.
# With strict mode enabled by default, missing guard registrations raise an error.
import governor.guards.executor_guards      # noqa: F401  (EG-01 through EG-08)


def main():
    parser = argparse.ArgumentParser(description="Governor full lifecycle demo.")
    parser.add_argument("--task_id", default="TASK_DEMO_001", help="Task ID for the demo run.")
    parser.add_argument(
        "--apply_fixes",
        action="store_true",
        help="Accepted for compatibility with demo tooling; memory demo always applies fixes inline.",
    )
    args = parser.parse_args()

    # --- Setup ---
    # MemoryBackend stores tasks, reviews, reports, and handoffs in plain dicts.
    # Neo4jBackend now provides equivalent lifecycle helpers for parity.
    backend = MemoryBackend()

    # Role aliases let you use your organization's role names.
    # The state machine uses canonical roles: EXECUTOR, REVIEWER.
    # Here we map DEVELOPER -> EXECUTOR so developers can use executor transitions.
    engine = TransitionEngine(
        backend=backend,
        role_aliases={"DEVELOPER": "EXECUTOR"},
    )

    print("=" * 60)
    print("Governor — Full Task Lifecycle Demo")
    print("=" * 60)

    # --- Step 1: Create a task ---
    # Every task needs: task_id, task_name, task_type, role, status, priority, content.
    # Tasks start in ACTIVE state — the executor is working on them.
    task_id = args.task_id
    backend.create_task({
        "task_id": task_id,
        "task_name": "Implement user authentication",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": (
            "Implement OAuth2 authentication flow with PKCE.\n\n"
            "## Deliverables\n"
            "- `auth.py` — OAuth2 handler\n"
            "- `auth_test.py` — Test suite\n\n"
            "## Test Plan\n"
            "Run test suite to verify login flow handles happy path and error cases."
        ),
    })
    print(f"\n[1] Created task: {task_id} (status=ACTIVE)")

    # --- Step 2: Check available transitions ---
    # Before attempting a transition, check what's possible and what guards are unmet.
    print("\n[2] Available transitions for EXECUTOR from ACTIVE:")
    available = engine.get_available_transitions(task_id, "DEVELOPER")
    for t in available["transitions"]:
        status = "READY" if t["ready"] else f"NOT READY ({len(t['guards_missing'])} guards unmet)"
        print(f"    -> {t['target_state']:25s} {status}")
        for g in t["guards_missing"]:
            print(f"       {g['guard_id']}: {g['reason']}")

    # --- Step 3: Dry-run the submission ---
    # Dry-run evaluates all guards but does NOT apply the state change.
    # Use this to pre-validate before committing.
    dry_result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER", dry_run=True)
    print(f"\n[3] Dry-run submission: {dry_result['result']} (state unchanged)")
    assert dry_result["dry_run"] is True
    assert backend.get_task(task_id)["task"]["status"] == "ACTIVE"

    # --- Step 4: Try submitting WITHOUT a self-review (should fail) ---
    # EG-01 requires a SELF_REVIEW before submission. Let's see the guard fail.
    print("\n[4] Submit without self-review (expect failure):")
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER")
    print(f"    Result: {result['result']}")
    for gr in result["guard_results"]:
        if not gr["passed"]:
            print(f"    FAIL {gr['guard_id']}: {gr['reason']}")
            print(f"         Fix: {gr['fix_hint']}")
    assert result["result"] == "FAIL"

    # --- Step 5: Add self-review and report, then retry ---
    # The self-review satisfies EG-01. A linked report satisfies EG-03 (deliverables)
    # when filesystem deliverables aren't present (e.g. in this demo environment).
    backend.add_report(task_id, {
        "report_id": "REPORT_IMPL_001",
        "report_type": "IMPLEMENTATION",
        "content": "OAuth2 PKCE flow implemented. Auth handler and test suite delivered.",
    })
    backend.add_review(task_id, {
        "review_id": "REVIEW_SELF_001",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 8.5,
        "content": "Implemented OAuth2 PKCE flow. All 12 tests pass. Edge cases covered.",
    })
    print("\n[5] Added report + self-review (EG-01 and EG-03 now satisfied)")
    if args.apply_fixes:
        print("    apply_fixes enabled: demo auto-applies remediation steps.")

    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER")
    print(f"    Submit for review: {result['result']}")
    if result["result"] == "FAIL":
        print(f"    Rejected: {result['rejection_reason']}")
        return

    print(f"    Temporal updates: {result['temporal_updates']}")
    assert backend.get_task(task_id)["task"]["status"] == "READY_FOR_REVIEW"

    # --- Step 6: Reviewer approves (READY_FOR_REVIEW -> COMPLETED) ---
    # The REVIEWER role reviews the submission. T02 re-evaluates EG guards independently.
    result = engine.transition_task(task_id, "COMPLETED", "REVIEWER")
    print(f"\n[6] Reviewer approves: {result['result']}")
    if result["result"] == "PASS":
        print("    Task COMPLETED!")
        print(f"    Temporal updates: {result['temporal_updates']}")
        print(f"    Events fired: {result['events_fired']}")
    else:
        print(f"    Rejected: {result['rejection_reason']}")

    # --- Final verification ---
    final_task = backend.get_task(task_id)["task"]
    print(f"\n{'=' * 60}")
    print(f"Final status:   {final_task['status']}")
    print(f"Submitted:      {final_task.get('submitted_date', 'N/A')}")
    print(f"Completed:      {final_task.get('completed_date', 'N/A')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
