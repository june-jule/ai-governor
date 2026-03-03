#!/usr/bin/env python3
"""AuraDB cloud deployment: connect Governor to Neo4j AuraDB.

Demonstrates how to run Governor against a cloud-hosted Neo4j AuraDB
instance instead of a local database. Covers environment configuration,
encrypted connection setup, schema initialization, and a full governed
task lifecycle (create -> submit -> approve).

Setup (AuraDB Free tier):

    1. Go to https://console.neo4j.io and create a free AuraDB instance.
    2. Copy the connection URI (starts with ``neo4j+s://``), username,
       and the generated password.
    3. Set environment variables:

           export GOVERNOR_NEO4J_URI="neo4j+s://xxxxxxxx.databases.neo4j.io"
           export GOVERNOR_NEO4J_USER="neo4j"
           export GOVERNOR_NEO4J_PASSWORD="your-generated-password"

    4. Install dependencies:

           pip install ai-governor neo4j

    5. Run the schema setup (one-time):

           cypher-shell -a "$GOVERNOR_NEO4J_URI" \\
               -u "$GOVERNOR_NEO4J_USER" \\
               -p "$GOVERNOR_NEO4J_PASSWORD" \\
               < schema/neo4j_schema.cypher

       Or use the programmatic setup shown in this example.

    6. Run this example:

           python examples/auradb_cloud.py

URI formats:
    - ``neo4j+s://``  — AuraDB (encrypted, required for cloud)
    - ``neo4j://``     — Local Neo4j (unencrypted, for development)

This file is a **pattern reference**. Adapt the task data, roles, and
guard configuration to your environment.
"""

import sys
import os

# Add parent directory so governor package is importable without installation
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from governor.backend.neo4j_backend import Neo4jBackend
from governor.engine.transition_engine import TransitionEngine

# Import guard modules — guards register themselves at import time via @register_guard.
import governor.guards.executor_guards  # noqa: F401  (EG-01 through EG-08)


# -- Schema setup (programmatic alternative to cypher-shell) ---------------

SCHEMA_STATEMENTS = [
    # Uniqueness constraints
    "CREATE CONSTRAINT task_id_unique IF NOT EXISTS FOR (t:Task) REQUIRE t.task_id IS UNIQUE",
    "CREATE CONSTRAINT review_id_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE",
    "CREATE CONSTRAINT report_id_unique IF NOT EXISTS FOR (r:Report) REQUIRE r.report_id IS UNIQUE",
    "CREATE CONSTRAINT transition_event_id_unique IF NOT EXISTS FOR (te:TransitionEvent) REQUIRE te.event_id IS UNIQUE",
    "CREATE CONSTRAINT guard_eval_id_unique IF NOT EXISTS FOR (ge:GuardEvaluation) REQUIRE ge.eval_id IS UNIQUE",
    # Performance indexes
    "CREATE INDEX task_status_idx IF NOT EXISTS FOR (t:Task) ON (t.status)",
    "CREATE INDEX task_role_idx IF NOT EXISTS FOR (t:Task) ON (t.role)",
    "CREATE INDEX task_status_role_idx IF NOT EXISTS FOR (t:Task) ON (t.status, t.role)",
]


def apply_schema(backend: Neo4jBackend) -> None:
    """Apply schema constraints and indexes.

    Safe to run repeatedly — every statement uses ``IF NOT EXISTS``.
    This is the programmatic equivalent of running:

        cypher-shell < schema/neo4j_schema.cypher
    """
    print("Applying schema constraints and indexes...")
    for stmt in SCHEMA_STATEMENTS:
        try:
            backend.execute_query(stmt)
        except Exception as exc:
            # Some AuraDB plans restrict certain index types.
            # Log and continue — the core constraints are what matter.
            print(f"  Warning: {exc}")
    print("Schema setup complete.\n")


# -- Cleanup helper (for repeatable demo runs) ----------------------------

def cleanup_demo_tasks(backend: Neo4jBackend, task_ids: list) -> None:
    """Remove demo tasks so the example is idempotent."""
    for task_id in task_ids:
        try:
            backend.execute_query(
                "MATCH (t:Task {task_id: $task_id}) "
                "OPTIONAL MATCH (t)-[r]->(n) "
                "DETACH DELETE t, n",
                {"task_id": task_id},
            )
        except Exception:
            pass


def main():
    # ==================================================================
    # Step 1: Connect to AuraDB using environment variables
    # ==================================================================
    # Neo4jBackend.from_env() reads:
    #   GOVERNOR_NEO4J_URI      — e.g. neo4j+s://xxxx.databases.neo4j.io
    #   GOVERNOR_NEO4J_USER     — e.g. neo4j
    #   GOVERNOR_NEO4J_PASSWORD — your generated password
    #   GOVERNOR_NEO4J_DATABASE — optional, defaults to "neo4j"
    #
    # AuraDB requires the neo4j+s:// scheme (TLS encrypted).
    # Local Neo4j uses neo4j:// (unencrypted).

    print("=" * 60)
    print("Governor — AuraDB Cloud Example")
    print("=" * 60)

    try:
        backend = Neo4jBackend.from_env()
    except ValueError as exc:
        print(f"\nConfiguration error: {exc}")
        print("\nSet the required environment variables:")
        print('  export GOVERNOR_NEO4J_URI="neo4j+s://xxxx.databases.neo4j.io"')
        print('  export GOVERNOR_NEO4J_USER="neo4j"')
        print('  export GOVERNOR_NEO4J_PASSWORD="your-password"')
        sys.exit(1)
    except ImportError as exc:
        print(f"\nMissing dependency: {exc}")
        print("\nInstall the Neo4j driver:")
        print("  pip install neo4j")
        sys.exit(1)

    # Use as context manager so the driver connection is closed on exit.
    with backend:

        # ==============================================================
        # Step 2: Verify connectivity
        # ==============================================================
        print("\n[1] Verifying AuraDB connection...")
        try:
            result = backend.execute_query("RETURN 1 AS connected")
            assert result[0]["connected"] == 1
            print("    Connected to AuraDB successfully.")
        except Exception as exc:
            print(f"    Connection failed: {exc}")
            print("\n    Check your URI, credentials, and network access.")
            sys.exit(1)

        # ==============================================================
        # Step 3: Apply schema (safe to re-run)
        # ==============================================================
        print("\n[2] Setting up schema...")
        apply_schema(backend)

        # ==============================================================
        # Step 4: Configure the Governor engine
        # ==============================================================
        engine = TransitionEngine(
            backend=backend,
            role_aliases={"DEVELOPER": "EXECUTOR"},
        )

        # ==============================================================
        # Step 5: Full task lifecycle on AuraDB
        # ==============================================================
        task_id = "AURADB_DEMO_001"

        # Clean up from previous runs
        cleanup_demo_tasks(backend, [task_id])

        # -- Create task --
        print(f"[3] Creating task: {task_id}")
        backend.create_task({
            "task_id": task_id,
            "task_name": "Implement rate limiting middleware",
            "task_type": "IMPLEMENTATION",
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": (
                "Add token bucket rate limiting to the API gateway.\n\n"
                "## Deliverables\n"
                "- `rate_limiter.py` -- Token bucket implementation\n"
                "- `test_rate_limiter.py` -- Test suite\n\n"
                "## Test Plan\n"
                "Run test suite. Verify 429 responses under load."
            ),
        })
        print("    Task created in AuraDB (status=ACTIVE)")

        # -- Check available transitions --
        print(f"\n[4] Available transitions from ACTIVE:")
        available = engine.get_available_transitions(task_id, "DEVELOPER")
        for t in available["transitions"]:
            status = "READY" if t["ready"] else f"NOT READY ({len(t['guards_missing'])} guards unmet)"
            print(f"    -> {t['target_state']:25s} {status}")

        # -- Add self-review (satisfies EG-01) --
        print(f"\n[5] Adding self-review and report...")
        backend.add_review(task_id, {
            "review_type": "SELF_REVIEW",
            "reviewer_role": "DEVELOPER",
            "rating": 8.5,
            "content": "Token bucket rate limiter implemented. 15 tests pass including edge cases.",
        })

        # -- Add report (satisfies EG-02/EG-03) --
        backend.add_report(task_id, {
            "report_type": "IMPLEMENTATION",
            "content": "Rate limiter delivered. Handles burst traffic with configurable refill rate.",
        })
        print("    Self-review and report persisted to AuraDB.")

        # -- Dry-run submission --
        print(f"\n[6] Dry-run submission (validate without state change):")
        dry_result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER", dry_run=True)
        print(f"    Dry-run result: {dry_result['result']}")
        for gr in dry_result["guard_results"]:
            icon = "+" if gr["passed"] else "x"
            print(f"    [{icon}] {gr['guard_id']}: {gr['reason'][:60]}")

        # -- Submit for review (ACTIVE -> READY_FOR_REVIEW) --
        print(f"\n[7] Submitting for review:")
        result = engine.transition_task(task_id, "READY_FOR_REVIEW", "DEVELOPER")
        print(f"    Result: {result['result']}")
        if result["result"] == "FAIL":
            print(f"    Blocked: {result.get('rejection_reason', 'See guard results')}")
            for gr in result["guard_results"]:
                if not gr["passed"]:
                    print(f"    FAIL {gr['guard_id']}: {gr['reason']}")
                    print(f"         Fix: {gr['fix_hint']}")
            return

        print(f"    Temporal updates: {result.get('temporal_updates', {})}")

        # -- Reviewer approves (READY_FOR_REVIEW -> COMPLETED) --
        print(f"\n[8] Reviewer approves:")
        result = engine.transition_task(task_id, "COMPLETED", "REVIEWER")
        print(f"    Result: {result['result']}")
        if result["result"] == "PASS":
            print("    Task COMPLETED.")

        # ==============================================================
        # Step 6: Verify final state in AuraDB
        # ==============================================================
        print(f"\n[9] Final task state from AuraDB:")
        task_data = backend.get_task(task_id)
        task = task_data["task"]
        print(f"    Status:     {task['status']}")
        print(f"    Submitted:  {task.get('submitted_date', 'N/A')}")
        print(f"    Completed:  {task.get('completed_date', 'N/A')}")

        # ==============================================================
        # Step 7: Query the audit trail (graph-powered)
        # ==============================================================
        print(f"\n[10] Audit trail from AuraDB:")
        trail = backend.get_task_audit_trail(task_id)
        for event in trail:
            guards_passed = sum(1 for g in event.get("guard_results", []) if g.get("passed"))
            guards_total = len(event.get("guard_results", []))
            print(
                f"    {event.get('from_state', '?'):20s} -> {event.get('to_state', '?'):20s} "
                f"[{event.get('result', '?')}] guards={guards_passed}/{guards_total}"
            )

        # -- Cleanup --
        cleanup_demo_tasks(backend, [task_id])
        print(f"\n{'=' * 60}")
        print("Demo complete. Task cleaned up from AuraDB.")
        print("=" * 60)


if __name__ == "__main__":
    main()
