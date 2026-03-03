# State Machine Design

Architecture document for the Governor task state machine. This is the single
source of truth for all legal state transitions, role authorization, and guard
evaluation.

---

## States

The state machine defines 6 states. A task is always in exactly one state.

| State | Terminal? | Description |
|-------|-----------|-------------|
| `ACTIVE` | No | Executor is working on the task |
| `READY_FOR_REVIEW` | No | Executor submitted work for review |
| `COMPLETED` | Yes | Reviewer approved; task finished successfully |
| `REWORK` | No | Reviewer returned task for revision |
| `BLOCKED` | No | Task is blocked by an external dependency or issue |
| `FAILED` | Yes | Task has been permanently failed and will not be retried |

**Terminal states:** `COMPLETED` and `FAILED` have no outbound transitions. Once a
task reaches either terminal state, its lifecycle is finished.

`BLOCKED` is a parking state for tasks that cannot progress due to external
dependencies, environment issues, or upstream blockers. A blocked task can be
unblocked back to `ACTIVE` or permanently failed.

---

## Transitions

9 transitions define the full state machine (v2.0.0).

| ID | From | To | Description | Allowed Roles | Guards |
|----|------|----|-------------|---------------|--------|
| T01 | ACTIVE | READY_FOR_REVIEW | Executor submission gate | EXECUTOR | EG-01, EG-02, EG-03, EG-04, EG-05, EG-06, EG-07, EG-08 |
| T02 | READY_FOR_REVIEW | COMPLETED | Reviewer approves | REVIEWER | EG-01, EG-02, EG-03, EG-04, EG-05, EG-06, EG-07, EG-08 |
| T03 | READY_FOR_REVIEW | REWORK | Reviewer returns for revision | REVIEWER | (none) |
| T04 | REWORK | READY_FOR_REVIEW | Executor resubmits after revision | EXECUTOR | EG-01, EG-02, EG-03, EG-04, EG-05, EG-06, EG-07, EG-08 |
| T05 | ACTIVE | BLOCKED | Executor or reviewer blocks the task | EXECUTOR, REVIEWER | (none) |
| T06 | BLOCKED | ACTIVE | Executor or reviewer unblocks the task | EXECUTOR, REVIEWER | (none) |
| T07 | REWORK | FAILED | Reviewer permanently fails a rework task | REVIEWER | (none) |
| T08 | ACTIVE | FAILED | Reviewer permanently fails an active task | REVIEWER | (none) |
| T09 | BLOCKED | FAILED | Reviewer permanently fails a blocked task | REVIEWER | (none) |

### Transition Diagram

```
                                    ┌──────────┐
                            T08     │          │
                      ┌────────────>│  FAILED  │
                      │             │          │
ACTIVE ──T01──> READY_FOR_REVIEW    └──────────┘
  │  ^                │    ^          ^    ^
  │  │            T03 │    │ T04      │    │
  │  │                v    │          │    │
  │  │              REWORK ───T07─────┘    │
  │  │                                     │
  │  T06                                   │
  │  │                                     │
  v  │                                     │
BLOCKED ──────────────T09──────────────────┘

                                COMPLETED
                                   ^
                                   │ T02
                                   │
                            READY_FOR_REVIEW
```

**Reading the diagram:**
- T01-T04 form the core review cycle (unchanged from v1).
- T05/T06 allow parking a task when blocked by external issues.
- T07/T08/T09 provide permanent failure from REWORK, ACTIVE, or BLOCKED states.
- COMPLETED and FAILED are terminal -- no outbound edges.

---

## Temporal Fields

Each transition can set or clear temporal fields on the task:

| Field | Set By | Cleared By |
|-------|--------|------------|
| `submitted_date` | T01, T04 (-> READY_FOR_REVIEW) | T03 (-> REWORK) |
| `completed_date` | T02 (-> COMPLETED) | -- |
| `blocked_date` | T05 (-> BLOCKED) | T06 (-> ACTIVE) |
| `failed_date` | T07, T08, T09 (-> FAILED) | -- |

---

## Transition Parameters

Some transitions accept or require additional parameters in the `transition_params`
dictionary:

| Parameter | Type | Required By | Description |
|-----------|------|-------------|-------------|
| `blocking_reason` | `str` | T05 (ACTIVE -> BLOCKED) | Why the task is blocked. Stored on the task and in the transition event. |
| `unblock_reason` | `str` | T06 (BLOCKED -> ACTIVE) | Why the block was resolved. Stored in the transition event. |
| `failure_reason` | `str` | T07, T08, T09 (-> FAILED) | Why the task is permanently failed. Stored on the task and in the transition event. |

**Example: Blocking a task**

```python
result = engine.transition_task(
    "TASK_001",
    "BLOCKED",
    "DEVELOPER",
    transition_params={"blocking_reason": "Waiting for API key from vendor"},
)
```

**Example: Permanently failing a blocked task**

```python
result = engine.transition_task(
    "TASK_001",
    "FAILED",
    "REVIEWER",
    transition_params={"failure_reason": "Vendor contract cancelled; task no longer relevant"},
)
```

---

## Role Model

The state machine uses two canonical role categories:

| Role | Description | Transitions |
|------|-------------|-------------|
| `EXECUTOR` | Performs the work, submits for review | T01, T04, T05, T06 |
| `REVIEWER` | Reviews submissions, approves or rejects | T02, T03, T05, T06, T07, T08, T09 |

**Role aliases:** The engine supports configurable role aliases via the
`role_aliases` parameter at initialization.

```python
engine = TransitionEngine(
    backend=backend,
    role_aliases={
        "DEVELOPER": "EXECUTOR",
        "QA": "REVIEWER",
    },
)
```

---

## Guard Model

Guards are functions that evaluate preconditions for a transition. Every guard
produces a `GuardResult`:

```
GuardResult:
  guard_id:  str       # e.g. "EG-02", "CUSTOM-01"
  passed:    bool      # True = passed, False = failed
  reason:    str       # Human-readable explanation
  fix_hint:  str       # Actionable suggestion for fixing a failure
  warning:   bool      # If True, guard passed but with advisory
```

**Evaluation rules:**

- All guards for a transition are always evaluated (no short-circuit).
- A transition FAILS if **any** guard returns `passed=False`.
- Guards with `warning=True` do not block the transition but are surfaced in the
  response.

**Guard types:**

1. **Registered guards** -- referenced by string ID (e.g. `"EG-01"`), resolved
   from the guard registry. See the [Guard Catalog](GUARD_CATALOG.md).
2. **Inline property guards** -- defined as objects in the state machine JSON
   with `guard_id`, `check`, `severity`, and `fix_hint`.

## Transition Event Model

Each transition attempt (dry-run, failed, or successful) can be persisted as a
`TransitionEvent` with associated `GuardEvaluation` entities. This creates a
graph-native audit log for:

- per-task lifecycle reconstruction
- guard hotspot analytics
- policy coverage tracking
- rework/churn lineage

---

## Illegal Transitions

Any transition not listed above is **illegal** and will be rejected with error
code `ILLEGAL_TRANSITION`. Examples:

| Attempted Transition | Why Illegal |
|----------------------|-------------|
| COMPLETED -> ACTIVE | COMPLETED is terminal |
| FAILED -> ACTIVE | FAILED is terminal |
| ACTIVE -> COMPLETED | Must go through READY_FOR_REVIEW first |
| BLOCKED -> COMPLETED | Must unblock to ACTIVE first, then follow T01/T02 |
| BLOCKED -> REWORK | No direct path; must unblock first |

## Concurrent Writes

Governor applies transitions with optimistic concurrency. Backends receive
`expected_current_status` during update operations and must only mutate when
the current state still matches. If another actor changed state first, the
engine returns `STATE_CONFLICT` and no transition is applied.

---

## Response Format

### Successful Transition

```json
{
  "result": "PASS",
  "transition_id": "T01",
  "from_state": "ACTIVE",
  "to_state": "READY_FOR_REVIEW",
  "guard_results": [
    {"guard_id": "EG-01", "passed": true, "reason": "Self-review exists", "fix_hint": ""}
  ],
  "dry_run": false,
  "events_fired": [],
  "temporal_updates": {"submitted_date": "2026-01-15"},
  "rejection_reason": null
}
```

### Guards Not Met

```json
{
  "result": "FAIL",
  "transition_id": "T01",
  "from_state": "ACTIVE",
  "to_state": "READY_FOR_REVIEW",
  "guard_results": [
    {"guard_id": "EG-01", "passed": false, "reason": "No SELF_REVIEW found", "fix_hint": "Create a self-review before submission"}
  ],
  "dry_run": false,
  "events_fired": [],
  "temporal_updates": {},
  "rejection_reason": "No SELF_REVIEW found"
}
```

### Concurrent State Conflict

```json
{
  "result": "FAIL",
  "error_code": "STATE_CONFLICT",
  "message": "Task state changed concurrently during transition. Expected 'ACTIVE', found 'REWORK'.",
  "from_state": "ACTIVE",
  "to_state": "READY_FOR_REVIEW",
  "guard_results": [],
  "dry_run": false,
  "events_fired": [],
  "temporal_updates": {},
  "rejection_reason": "Task state changed concurrently during transition. Expected 'ACTIVE', found 'REWORK'."
}
```
