// Governor — Neo4j Visualization & Analytics Queries
// Copy-paste these into Neo4j Browser or Bloom for operational dashboards.

// ============================================================
// 1. Full State Machine Graph (all tasks + transitions)
// ============================================================

// Show all tasks with their latest transition events
MATCH (t:Task)
OPTIONAL MATCH (t)-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
WITH t, te ORDER BY te.occurred_at DESC
WITH t, collect(te)[0] AS latest_event
RETURN t.task_id AS task_id,
       t.status AS status,
       t.role AS role,
       t.priority AS priority,
       latest_event.from_state AS last_from,
       latest_event.to_state AS last_to,
       latest_event.occurred_at AS last_transition;

// ============================================================
// 2. Task Lifecycle Timeline (for a specific task)
// ============================================================

// Visualize the full transition history of a task
// Replace $task_id with the actual task ID
MATCH (t:Task {task_id: $task_id})-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
OPTIONAL MATCH (te)-[:HAS_GUARD_EVALUATION]->(ge:GuardEvaluation)
WITH te, collect(ge) AS guards
ORDER BY te.occurred_at
RETURN te.event_id AS event_id,
       te.from_state AS from_state,
       te.to_state AS to_state,
       te.result AS result,
       te.calling_role AS calling_role,
       te.occurred_at AS occurred_at,
       size(guards) AS guard_count,
       size([g IN guards WHERE g.passed = true]) AS guards_passed,
       size([g IN guards WHERE g.passed = false]) AS guards_failed;

// ============================================================
// 3. Guard Pass/Fail Analytics
// ============================================================

// Guard failure rate by guard_id (most-failing guards first)
MATCH (ge:GuardEvaluation)
WITH ge.guard_id AS guard_id,
     count(*) AS total,
     sum(CASE WHEN ge.passed = true THEN 1 ELSE 0 END) AS passed,
     sum(CASE WHEN ge.passed = false THEN 1 ELSE 0 END) AS failed
RETURN guard_id, total, passed, failed,
       round(100.0 * failed / total, 1) AS fail_pct
ORDER BY fail_pct DESC;

// ============================================================
// 4. Active Tasks by Role (operational dashboard)
// ============================================================

MATCH (t:Task)
WHERE t.status IN ['ACTIVE', 'READY_FOR_REVIEW', 'REWORK']
RETURN t.role AS role,
       t.status AS status,
       count(*) AS task_count,
       collect(t.task_id)[..5] AS sample_ids
ORDER BY role, status;

// ============================================================
// 5. Transition Success/Failure Rate Over Time
// ============================================================

// Daily transition outcomes (last 30 days)
MATCH (te:TransitionEvent)
WHERE te.occurred_at >= datetime() - duration('P30D')
WITH date(te.occurred_at) AS day, te.result AS result
RETURN day,
       sum(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END) AS passed,
       sum(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) AS failed
ORDER BY day;

// ============================================================
// 6. Task Evidence Graph (reviews + reports)
// ============================================================

// Show a task with all its evidence relationships
// Replace $task_id with the actual task ID
MATCH (t:Task {task_id: $task_id})
OPTIONAL MATCH (t)-[:HAS_REVIEW]->(rev:Review)
OPTIONAL MATCH (t)-[:REPORTS_ON]-(rep:Report)
RETURN t, rev, rep;

// ============================================================
// 7. Bottleneck Detection — Tasks Stuck in State
// ============================================================

// Tasks that have been in their current state for > 7 days
MATCH (t:Task)-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
WHERE te.result = 'PASS'
WITH t, te ORDER BY te.occurred_at DESC
WITH t, collect(te)[0] AS latest
WHERE latest.occurred_at < datetime() - duration('P7D')
  AND t.status IN ['ACTIVE', 'READY_FOR_REVIEW', 'REWORK']
RETURN t.task_id AS task_id,
       t.status AS status,
       t.role AS role,
       t.priority AS priority,
       latest.occurred_at AS stuck_since,
       duration.between(latest.occurred_at, datetime()).days AS days_stuck
ORDER BY days_stuck DESC;

// ============================================================
// 8. Guard Evaluation Details (for debugging)
// ============================================================

// All guard evaluations for a specific transition event
// Replace $event_id with the actual event ID
MATCH (te:TransitionEvent {event_id: $event_id})-[:HAS_GUARD_EVALUATION]->(ge:GuardEvaluation)
RETURN ge.guard_id AS guard_id,
       ge.passed AS passed,
       ge.reason AS reason,
       ge.fix_hint AS fix_hint
ORDER BY ge.guard_id;

// ============================================================
// 9. State Machine Version Drift Detection
// ============================================================

// Check which state machine versions have been used in transitions
MATCH (te:TransitionEvent)
WHERE te.state_machine_version IS NOT NULL
RETURN te.state_machine_version AS sm_version,
       count(*) AS transition_count,
       min(te.occurred_at) AS first_seen,
       max(te.occurred_at) AS last_seen
ORDER BY last_seen DESC;
