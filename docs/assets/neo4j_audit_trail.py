#!/usr/bin/env python3
"""Generate Cypher CREATE statements for a realistic Governor demo subgraph.

Run this script, then paste the output into Neo4j Browser to create a demo
governance subgraph. After running the Cypher, visualize it with:

    MATCH (t:Task {task_id: 'TASK_DEMO_001'})-[r]->(n) RETURN *

The subgraph shows a single task's full governance trail: two reviews
(one triggering rework, one passing), one report, and two handoffs
(submission + rework return). Properties match the schema defined in
schema/neo4j_schema.cypher and mirror the lifecycle demonstrated in
examples/full_task_lifecycle.py.
"""


def generate_cypher() -> str:
    """Return Cypher CREATE statements for a demo governance subgraph."""
    return """\
// =================================================================
// Governor Demo Subgraph — Realistic Governance Trail
// =================================================================
//
// Run this in Neo4j Browser to create a demo governance subgraph,
// then run:
//   MATCH (t:Task {task_id: 'TASK_DEMO_001'})-[r]->(n) RETURN *
// to visualize the full audit trail.
//
// The subgraph models a task that:
//   1. Was submitted for review (ACTIVE -> READY_FOR_REVIEW)
//   2. Failed review due to missing tests (READY_FOR_REVIEW -> REWORK)
//   3. Was reworked and resubmitted
//   4. Passed review (READY_FOR_REVIEW -> COMPLETED)

// --- Task Node (center of the subgraph) ---
CREATE (t:Task {
  task_id: 'TASK_DEMO_001',
  task_name: 'Implement user authentication',
  task_type: 'IMPLEMENTATION',
  role: 'DEVELOPER',
  status: 'COMPLETED',
  priority: 'HIGH',
  content: 'Implement OAuth2 authentication flow with PKCE.\\n\\n## Deliverables\\n- auth.py\\n- auth_test.py',
  revision_count: 1,
  created_date: datetime('2025-06-15T09:00:00Z'),
  submitted_date: datetime('2025-06-15T14:30:00Z'),
  completed_date: datetime('2025-06-15T16:45:00Z')
})

// --- Review 1: Self-review before first submission ---
CREATE (r1:Review {
  review_id: 'REVIEW_SELF_001',
  review_type: 'SELF_REVIEW',
  reviewer_role: 'DEVELOPER',
  rating: 7.0,
  content: 'OAuth2 PKCE flow implemented. Basic tests pass but edge cases need coverage.',
  date: datetime('2025-06-15T14:00:00Z'),
  status: 'SUPERSEDED'
})

// --- Review 2: Reviewer rejects — missing test coverage ---
CREATE (r2:Review {
  review_id: 'REVIEW_GOV_001',
  review_type: 'GOVERNOR_REVIEW',
  reviewer_role: 'REVIEWER',
  rating: 5.5,
  content: 'EG-08 failed: test references missing for 2 of 3 deliverables. Rework required.',
  date: datetime('2025-06-15T15:00:00Z'),
  status: 'COMPLETED'
})

// --- Review 3: Self-review after rework ---
CREATE (r3:Review {
  review_id: 'REVIEW_SELF_002',
  review_type: 'SELF_REVIEW',
  reviewer_role: 'DEVELOPER',
  rating: 8.5,
  content: 'Added comprehensive test suite. All 12 tests pass including error cases.',
  date: datetime('2025-06-15T16:00:00Z'),
  status: 'COMPLETED'
})

// --- Report: Implementation report attached to the task ---
CREATE (rpt:Report {
  report_id: 'REPORT_IMPL_001',
  report_type: 'IMPLEMENTATION',
  content: 'OAuth2 PKCE flow implemented with auth.py handler and auth_test.py suite. 12 tests cover happy path, token refresh, and error handling.',
  report_date: datetime('2025-06-15T16:15:00Z')
})

// --- Handoff 1: Submission handoff (executor -> reviewer) ---
CREATE (h1:Handoff {
  handoff_id: 'HANDOFF_DEV_REVIEWER_001',
  from_role: 'DEVELOPER',
  to_role: 'REVIEWER',
  handoff_type: 'TASK_SUBMISSION',
  summary: 'OAuth2 implementation ready for review. All guards pass.',
  status: 'COMPLETED',
  created_date: datetime('2025-06-15T16:20:00Z')
})

// --- Handoff 2: Rework handoff (reviewer -> executor) ---
CREATE (h2:Handoff {
  handoff_id: 'HANDOFF_REVIEWER_DEV_001',
  from_role: 'REVIEWER',
  to_role: 'DEVELOPER',
  handoff_type: 'REWORK_REQUEST',
  summary: 'EG-08 failed: add test references for auth.py and token_refresh.py.',
  status: 'COMPLETED',
  created_date: datetime('2025-06-15T15:05:00Z')
})

// --- Relationships ---
CREATE (t)-[:HAS_REVIEW {created_at: datetime('2025-06-15T14:00:00Z')}]->(r1)
CREATE (t)-[:HAS_REVIEW {created_at: datetime('2025-06-15T15:00:00Z')}]->(r2)
CREATE (t)-[:HAS_REVIEW {created_at: datetime('2025-06-15T16:00:00Z')}]->(r3)
CREATE (rpt)-[:REPORTS_ON {created_at: datetime('2025-06-15T16:15:00Z')}]->(t)
CREATE (t)-[:HANDOFF_TO {created_at: datetime('2025-06-15T16:20:00Z')}]->(h1)
CREATE (t)-[:HANDOFF_TO {created_at: datetime('2025-06-15T15:05:00Z')}]->(h2)

;"""


def main() -> None:
    print(generate_cypher())


if __name__ == "__main__":
    main()
