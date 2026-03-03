#!/usr/bin/env python3
"""Role configuration and role-based access control (RBAC) patterns.

Demonstrates:
  - How the state machine uses canonical roles (EXECUTOR, REVIEWER)
  - How role aliases map your organization's roles to canonical roles
  - Which roles can perform which transitions
  - What happens when an unauthorized role attempts a transition
  - Full lifecycle with aliased roles

Run with:

    python examples/configure_roles.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine

import governor.guards.executor_guards      # noqa: F401


def main():
    backend = MemoryBackend()

    # --- Role Aliases ---
    # The state machine JSON uses these canonical roles in allowed_roles:
    #   EXECUTOR — performs work, submits for review
    #   REVIEWER — reviews submissions, approves/rejects
    #
    # Role aliases let you map your team's titles to these canonical roles.
    # The mapping is case-insensitive (input is uppercased before lookup).
    role_aliases = {
        "DEV": "EXECUTOR",
        "DEVELOPER": "EXECUTOR",
        "QA": "EXECUTOR",
        "SRE": "EXECUTOR",
        "TEAM_LEAD": "REVIEWER",
    }

    engine = TransitionEngine(backend=backend, role_aliases=role_aliases)

    print("Role Configuration Demo")
    print("=" * 60)

    # --- Create a task ---
    task_id = "TASK_ROLES_001"
    backend.create_task({
        "task_id": task_id,
        "task_name": "Fix login timeout bug",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Fix the session timeout handling. Add tests to verify the fix.",
    })

    # --- Demo 1: Unauthorized role attempt ---
    # REVIEWER cannot submit (only EXECUTOR can via T01)
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "REVIEWER")
    print(f"\n[1] REVIEWER tries to submit: {result['result']}")
    print(f"    Error: {result.get('error_code', 'N/A')}")
    print(f"    REVIEWER is only allowed for review transitions (T02, T03)")

    # --- Demo 2: DEV submits (DEV -> EXECUTOR) ---
    backend.add_review(task_id, {
        "review_id": "REV_001",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 8.0,
        "content": "Fixed timeout handling. All tests pass.",
    })
    result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEV")
    print(f"\n[2] DEV submits:        {result['result']}")
    print(f"    DEV is aliased to EXECUTOR (allowed for submission)")

    # --- Demo 3: REVIEWER approves ---
    result = engine.transition_task(task_id, "COMPLETED", "REVIEWER")
    print(f"\n[3] REVIEWER approves:  {result['result']}")

    # --- Demo 4: Rework cycle ---
    print(f"\n{'=' * 60}")
    print("Rework Cycle Demo")
    print("=" * 60)

    task2_id = "TASK_ROLES_002"
    backend.create_task({
        "task_id": task2_id,
        "task_name": "Integrate payment API",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "MEDIUM",
        "content": "Integrate third-party payment API. Add tests to verify.",
    })

    # Submit
    backend.add_review(task2_id, {
        "review_id": "REV_002",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 7.0,
        "content": "Initial implementation done.",
    })
    engine.transition_task(task2_id, "READY_FOR_REVIEW", "SRE")
    print(f"\n[4] SRE submits:        PASS (SRE -> EXECUTOR)")

    # Reviewer requests rework (T03: READY_FOR_REVIEW -> REWORK)
    result = engine.transition_task(task2_id, "REWORK", "REVIEWER")
    print(f"[5] REVIEWER requests rework: {result['result']}")

    # Executor resubmits (T04: REWORK -> READY_FOR_REVIEW)
    result = engine.transition_task(task2_id, "READY_FOR_REVIEW", "DEV")
    print(f"[6] DEV resubmits:      {result['result']}")

    # Reviewer approves
    result = engine.transition_task(task2_id, "COMPLETED", "TEAM_LEAD")
    print(f"[7] TEAM_LEAD approves: {result['result']}")

    final = backend.get_task(task2_id)["task"]
    print(f"    Final status: {final['status']}")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("Role Alias Summary:")
    print(f"{'=' * 60}")
    for alias, canonical in sorted(role_aliases.items()):
        print(f"  {alias:15s} -> {canonical}")
    print(f"\nCanonical roles in state machine:")
    print(f"  EXECUTOR — submit for review (T01), resubmit after rework (T04)")
    print(f"  REVIEWER — approve (T02), request rework (T03)")
    print("=" * 60)


if __name__ == "__main__":
    main()
