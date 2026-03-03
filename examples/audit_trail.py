#!/usr/bin/env python3
"""Audit trail demo: trace guard failures, rework, and task lineage.

Shows why governance data belongs in a graph database. Creates 5 tasks,
runs them through the lifecycle (some pass, some rework), and prints
an audit trail with guard results.

Runs on MemoryBackend (no Neo4j needed). Cypher equivalents are shown
in comments for each query pattern.

    python examples/audit_trail.py
"""

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine
import governor.guards.executor_guards  # noqa: F401 — register built-in guards


def main():
    backend = MemoryBackend()
    engine = TransitionEngine(backend=backend)

    # -- Create 5 tasks with varied scenarios -----------------------------

    tasks = [
        {
            "task_id": "AUDIT_001",
            "task_name": "Research API latency",
            "task_type": "INVESTIGATION",
            "role": "RESEARCHER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "Investigate API latency spike. Source: logs. Evidence: monitoring confirms issue. Verified via cross-check.",
        },
        {
            "task_id": "AUDIT_002",
            "task_name": "Fix connection pooling",
            "task_type": "IMPLEMENTATION",
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "CRITICAL",
            "content": "Added connection pooling. Tests confirm 60% improvement.",
        },
        {
            "task_id": "AUDIT_003",
            "task_name": "Deploy pooling fix",
            "task_type": "DEPLOY",
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "Deploy connection pooling to production. Rollback: revert to previous image.",
        },
        {
            "task_id": "AUDIT_004",
            "task_name": "Incomplete investigation",
            "task_type": "INVESTIGATION",
            "role": "RESEARCHER",
            "status": "ACTIVE",
            "priority": "MEDIUM",
            "content": "Quick look at the issue.",  # Deliberately thin — will fail guards
        },
        {
            "task_id": "AUDIT_005",
            "task_name": "Security audit",
            "task_type": "AUDIT",
            "role": "AUDITOR",
            "status": "ACTIVE",
            "priority": "CRITICAL",
            "content": "Audit of auth system. Source: code review. Evidence: pen test results. Verified: OWASP checklist.",
        },
    ]

    for t in tasks:
        backend.create_task(t)

    # Add self-reviews and reports for tasks that should pass
    for tid in ["AUDIT_001", "AUDIT_002", "AUDIT_003", "AUDIT_005"]:
        backend.add_review(tid, {"review_type": "SELF_REVIEW", "rating": 8.0})
        backend.add_report(tid, {
            "report_type": "INVESTIGATION",
            "content": f"Report for {tid}",
            "metadata": '{"sources": ["monitoring", "logs"]}',
        })

    # AUDIT_004 gets NO self-review and NO report (will fail EG-01, EG-02, EG-03)

    # -- Run lifecycle and collect audit trail -----------------------------

    print("=" * 70)
    print("GOVERNOR AUDIT TRAIL DEMO")
    print("=" * 70)

    audit_log = []

    for t in tasks:
        tid = t["task_id"]
        result = engine.transition_task(tid, "READY_FOR_REVIEW", "EXECUTOR")

        entry = {
            "task_id": tid,
            "task_name": t["task_name"],
            "verdict": result["result"],
            "guards_total": len(result["guard_results"]),
            "guards_passed": sum(1 for g in result["guard_results"] if g["passed"]),
            "guards_failed": [g["guard_id"] for g in result["guard_results"] if not g["passed"]],
        }
        audit_log.append(entry)

        status = "PASS" if result["result"] == "PASS" else "FAIL"
        print(f"\n[{status}] {tid}: {t['task_name']}")
        for gr in result["guard_results"]:
            icon = "+" if gr["passed"] else "x"
            print(f"  [{icon}] {gr['guard_id']}: {gr['reason'][:70]}")

    # -- Rework demo: fix AUDIT_004 and resubmit --------------------------

    print(f"\n{'=' * 70}")
    print("REWORK CYCLE: Fixing AUDIT_004")
    print("=" * 70)

    # Add missing artifacts
    backend.add_review("AUDIT_004", {"review_type": "SELF_REVIEW", "rating": 7.0})
    backend.add_report("AUDIT_004", {
        "report_type": "INVESTIGATION",
        "content": "Expanded investigation with source evidence. Verified findings.",
    })

    # Update content with evidence
    backend.update_task("AUDIT_004", {
        "content": "Detailed investigation of the issue. Source: application logs. Evidence: metrics dashboard confirms. Verified via team review.",
    })

    result2 = engine.transition_task("AUDIT_004", "READY_FOR_REVIEW", "EXECUTOR")
    print(f"\n[{'PASS' if result2['result'] == 'PASS' else 'FAIL'}] AUDIT_004 after rework")
    for gr in result2["guard_results"]:
        icon = "+" if gr["passed"] else "x"
        print(f"  [{icon}] {gr['guard_id']}: {gr['reason'][:70]}")

    # -- Summary table ----------------------------------------------------

    print(f"\n{'=' * 70}")
    print(f"{'Task ID':<15} {'Name':<30} {'Result':<8} {'Passed':<8} {'Failed Guards'}")
    print("-" * 70)
    for e in audit_log:
        failed = ", ".join(e["guards_failed"]) if e["guards_failed"] else "-"
        print(f"{e['task_id']:<15} {e['task_name']:<30} {e['verdict']:<8} "
              f"{e['guards_passed']}/{e['guards_total']:<5} {failed}")

    # -- Neo4j Cypher equivalents (for graph-powered audit) ---------------

    print(f"\n{'=' * 70}")
    print("NEO4J CYPHER EQUIVALENTS")
    print("=" * 70)
    print("""
// Query 1: Full audit trail for a task (relationship traversal)
MATCH (t:Task {task_id: $task_id})-[r]->(n)
RETURN t.task_name, type(r) AS rel, labels(n) AS node_type, properties(n) AS detail
ORDER BY n.created_date

// Query 2: Which guards fail most often? (aggregation)
MATCH (t:Task)
WHERE t.status = 'ACTIVE'  // stuck in ACTIVE = guards blocked them
RETURN t.task_type, count(*) AS blocked_count
ORDER BY blocked_count DESC

// Query 3: Trace rework lineage (path query)
MATCH (t:Task)-[:HAS_REVIEW]->(r:Review {review_type: 'SELF_REVIEW'})
WHERE t.status = 'REWORK'
RETURN t.task_id, t.task_name, r.rating, t.revision_count
ORDER BY t.revision_count DESC
""")

    # --- Graph-Only Analytical Queries (require Neo4j) ---
    #
    # These queries exploit capabilities unique to graph databases:
    # variable-length path traversal, relationship-aware aggregation,
    # and multi-hop pattern matching. They cannot be expressed as simple
    # SQL or dict lookups — they require a graph engine.

    print(f"\n{'=' * 70}")
    print("GRAPH-ONLY ANALYTICAL QUERIES (require Neo4j)")
    print("=" * 70)

    # Query 1 — Trace the full rework chain for a task
    # Insight: Shows the complete governance trail — every review, handoff,
    # and state change that led to the current state. In a relational DB
    # this requires recursive CTEs across multiple join tables; in Neo4j
    # it's a single variable-length path traversal.
    print("""
// Query 1: Trace the full rework chain for a task (variable-length path traversal)
// Why graph: Variable-length path traversal across heterogeneous relationship
// types (reviews + handoffs) in a single query — no recursive CTEs needed.
MATCH path = (t:Task {task_id: $task_id})-[:HAS_REVIEW|HANDOFF_TO*1..6]->(n)
RETURN [node IN nodes(path) | {
  labels: labels(node),
  id: coalesce(node.task_id, node.review_id, node.handoff_id),
  status: node.status
}] AS chain
""")

    # Query 2 — Find guard failure co-occurrence patterns
    # Insight: Reveals which guards tend to fail together, exposing
    # systemic issues (e.g., tasks missing self-reviews also tend to
    # lack reports). In SQL this requires self-joins on unnested arrays;
    # in Cypher, UNWIND + pair filtering is natural.
    print("""
// Query 2: Find guard failure co-occurrence patterns
// Why graph: UNWIND + pair filtering on stored lists is native to Cypher.
// In SQL, this requires unnesting arrays into rows, self-joining, and
// filtering the diagonal — 3x the query complexity.
MATCH (t:Task)
WHERE t.last_guard_failures IS NOT NULL
WITH t, split(t.last_guard_failures, ',') AS failures
WHERE size(failures) > 1
UNWIND failures AS g1
UNWIND failures AS g2
WITH g1, g2 WHERE g1 < g2
RETURN g1, g2, count(*) AS co_occurrence
ORDER BY co_occurrence DESC LIMIT 10
""")

    # Query 3 — Cross-task impact analysis: in-flight tasks by type
    # Insight: Gives a real-time operational snapshot of what's active
    # across the system. Sampling task IDs per bucket is trivial with
    # collect()[..5] in Cypher; in SQL it requires window functions.
    print("""
// Query 3: Cross-task impact analysis — in-flight tasks by type
// Why graph: collect() with slice is a one-liner for sampled aggregation.
// In SQL, getting "top 5 sample IDs per group" requires ROW_NUMBER()
// window functions and a subquery.
MATCH (t:Task)
WHERE t.status IN ['ACTIVE', 'READY_FOR_REVIEW']
RETURN t.task_type, count(*) AS in_flight,
       collect(t.task_id)[..5] AS sample_task_ids
ORDER BY in_flight DESC
""")

    # Query 4 — Agent efficiency: average rework cycles by role and task type
    # Insight: Identifies which role + task type combinations produce the
    # most rework, pointing to training gaps or unclear requirements.
    # Expressible in SQL, but graph adjacency to reviews/handoffs makes
    # it easy to extend with "also show the guard that failed most" in
    # the same query — something that requires additional joins in SQL.
    print("""
// Query 4: Agent efficiency — average rework cycles by role and task type
// Why graph: While this specific aggregation is possible in SQL, the graph
// model makes it trivial to extend — e.g., adding "most common failing
// guard per group" requires one extra MATCH hop, not a new join table.
MATCH (t:Task)
WHERE t.revision_count > 0
RETURN t.role, t.task_type,
       avg(t.revision_count) AS avg_reworks,
       max(t.revision_count) AS max_reworks,
       count(*) AS total_tasks
ORDER BY avg_reworks DESC
""")


if __name__ == "__main__":
    main()
