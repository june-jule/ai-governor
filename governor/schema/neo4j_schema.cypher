// Governor — Minimal Neo4j Schema
// Creates constraints and indexes for Task, Review, Report, Policy, Handoff,
// TransitionEvent, and GuardEvaluation nodes.
// Run this against your Neo4j database to set up the schema.

// ============================================================
// Constraints (uniqueness)
// ============================================================

CREATE CONSTRAINT task_id_unique IF NOT EXISTS
FOR (t:Task) REQUIRE t.task_id IS UNIQUE;

CREATE CONSTRAINT review_id_unique IF NOT EXISTS
FOR (r:Review) REQUIRE r.review_id IS UNIQUE;

CREATE CONSTRAINT report_id_unique IF NOT EXISTS
FOR (r:Report) REQUIRE r.report_id IS UNIQUE;

CREATE CONSTRAINT policy_id_unique IF NOT EXISTS
FOR (p:Policy) REQUIRE p.policy_id IS UNIQUE;

CREATE CONSTRAINT handoff_id_unique IF NOT EXISTS
FOR (h:Handoff) REQUIRE h.handoff_id IS UNIQUE;

CREATE CONSTRAINT transition_event_id_unique IF NOT EXISTS
FOR (te:TransitionEvent) REQUIRE te.event_id IS UNIQUE;

CREATE CONSTRAINT guard_eval_id_unique IF NOT EXISTS
FOR (ge:GuardEvaluation) REQUIRE ge.eval_id IS UNIQUE;

// ============================================================
// Indexes (for common queries)
// ============================================================

CREATE INDEX task_status_idx IF NOT EXISTS
FOR (t:Task) ON (t.status);

CREATE INDEX task_role_idx IF NOT EXISTS
FOR (t:Task) ON (t.role);

CREATE INDEX review_type_idx IF NOT EXISTS
FOR (r:Review) ON (r.review_type);

CREATE INDEX policy_type_idx IF NOT EXISTS
FOR (p:Policy) ON (p.policy_type);

CREATE INDEX handoff_status_idx IF NOT EXISTS
FOR (h:Handoff) ON (h.status);

CREATE INDEX transition_event_time_idx IF NOT EXISTS
FOR (te:TransitionEvent) ON (te.occurred_at);

CREATE INDEX transition_event_result_idx IF NOT EXISTS
FOR (te:TransitionEvent) ON (te.result);

CREATE INDEX guard_eval_guard_id_idx IF NOT EXISTS
FOR (ge:GuardEvaluation) ON (ge.guard_id);

// Guard pass/fail analytics queries
CREATE INDEX guard_eval_passed_idx IF NOT EXISTS
FOR (ge:GuardEvaluation) ON (ge.passed);

// ============================================================
// Composite Indexes (production query patterns)
// ============================================================

// "All active tasks for a given role" — the most common operational query
CREATE INDEX task_status_role_idx IF NOT EXISTS
FOR (t:Task) ON (t.status, t.role);

// "All critical active tasks" — priority-based alerting and triage
CREATE INDEX task_status_priority_idx IF NOT EXISTS
FOR (t:Task) ON (t.status, t.priority);

// "All active DEPLOY tasks" — deployment pipeline monitoring
CREATE INDEX task_status_type_idx IF NOT EXISTS
FOR (t:Task) ON (t.status, t.task_type);

// "Recently created tasks by status" — time-range dashboard queries
CREATE INDEX task_status_created_date_idx IF NOT EXISTS
FOR (t:Task) ON (t.status, t.created_date);

// "Filtered audit trail queries" — result + time range lookups
CREATE INDEX transition_event_result_time_idx IF NOT EXISTS
FOR (te:TransitionEvent) ON (te.result, te.occurred_at);

// ============================================================
// Task Dependency Indexes (graph analytics)
// ============================================================

// DEPENDS_ON relationship — task-to-task dependency graph
CREATE INDEX task_depends_on_created_idx IF NOT EXISTS
FOR ()-[d:DEPENDS_ON]->() ON (d.created_date);

// BLOCKS relationship — inverse dependency graph
CREATE INDEX task_blocks_created_idx IF NOT EXISTS
FOR ()-[b:BLOCKS]->() ON (b.created_date);

// ============================================================
// Temporal field indexes (v2.0.0 — BLOCKED/FAILED states)
// ============================================================

// "All blocked tasks by date" — stale-blocker alerting
CREATE INDEX task_blocked_date_idx IF NOT EXISTS
FOR (t:Task) ON (t.blocked_date);

// "All failed tasks by date" — failure trend analytics
CREATE INDEX task_failed_date_idx IF NOT EXISTS
FOR (t:Task) ON (t.failed_date);

// "Blocked tasks by role" — per-team blocker dashboards
CREATE INDEX task_status_blocked_date_idx IF NOT EXISTS
FOR (t:Task) ON (t.status, t.blocked_date);

// ============================================================
// Audit event TTL support (retention policy)
// ============================================================

// "Transition events older than N days" — retention queries
CREATE INDEX transition_event_occurred_at_idx IF NOT EXISTS
FOR (te:TransitionEvent) ON (te.occurred_at);

// "Guard evaluations linked to old events" — cascading cleanup
CREATE INDEX guard_eval_event_idx IF NOT EXISTS
FOR ()-[r:HAS_GUARD_EVALUATION]->() ON (r.created_date);
