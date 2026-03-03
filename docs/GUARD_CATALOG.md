# Guard Catalog

Reference for all built-in guards. Guards run on every transition and decide what
passes.

---

## Overview

Guards enforce the state machine. Every governed
transition defines a list of guard IDs. The engine evaluates **all** guards for a
transition (no short-circuit) and returns a composite PASS/FAIL result.

**EG Guards** (Executor Governor) gate submissions and reviews across the
review cycle.

---

## EG Guards -- Submission Gate (ACTIVE -> READY_FOR_REVIEW)

These guards validate evidence and deliverables before submission.

**Normalization note:** Policy-critical enums (`task_type`, `status`, `role`,
`priority`) are normalized to uppercase at engine/backend boundaries, so guard
severity logic is case-insensitive for values like `deploy`, `Deploy`, `DEPLOY`.

| Guard ID | Check | Severity | Task Type Filter | Fix Hint |
|----------|-------|----------|------------------|----------|
| EG-01 | Self-review must exist | CRITICAL | All | Create a self-review |
| EG-02 | Report must exist (severity varies by task type) | HIGH | All | Link a report |
| EG-03 | Report or filesystem deliverables exist (see note below) | HIGH | All | Link a report or ensure deliverables exist |
| EG-04 | No deploy commands in non-DEPLOY tasks | HIGH | All except DEPLOY | Remove deploy commands |
| EG-05 | No secrets or credentials in task content | HIGH | All | Remove secrets from content |
| EG-06 | DEPLOY tasks must mention rollback strategy | HIGH | DEPLOY only | Add rollback strategy |
| EG-07 | AUDIT tasks reference >= 2 evidence sources (heuristic, see note below) | MEDIUM | AUDIT only | Add evidence sources |
| EG-08 | IMPLEMENTATION tasks must reference tests | MEDIUM | IMPLEMENTATION only | Add test references |

### EG-03: What It Actually Checks

EG-03 checks that at least one of the following is true:

1. All declared deliverable files exist on the filesystem, OR
2. At least one report is linked to the task (via `REPORTS_ON` relationship)

A linked report **satisfies the deliverables requirement** even if specific
deliverable files are missing. The guard does not verify that the report content
references or describes the deliverables. This is intentional — it keeps the
guard fast and avoids NLP-level content validation — but it means EG-03 is a
structural check, not a content-level verification of deliverables.

### EG-07: Heuristic Evidence Check

EG-07 scans task content and linked report content for evidence-related keywords
(`source`, `evidence`, `verified`, `confirmed`, `cross-check`, `reference`) and
checks report metadata for explicit source lists. It passes if it finds >= 2
keyword matches or >= 2 explicit metadata sources.

This is a **lightweight heuristic placeholder**, not rigorous multi-source
evidence validation. Production deployments handling real audit compliance should
override EG-07 with a domain-specific guard that validates evidence against
actual source systems.

### EG-02 Severity by Task Type

| Task Type | Blocking? |
|-----------|-----------|
| INVESTIGATION, AUDIT | Yes |
| IMPLEMENTATION, DEPLOY | No (warning) |

---

## Reviewer Guards (READY_FOR_REVIEW -> COMPLETED)

T02 re-uses the EG guard set, ensuring independent validation of the same
evidence contracts.

---

## Extension Points

Register new guards or override built-in ones with `@register_guard`:

```python
from governor.engine.transition_engine import GuardContext, GuardResult, register_guard

@register_guard("CUSTOM-01")
def my_custom_guard(ctx: GuardContext) -> GuardResult:
    """A custom guard for your domain."""
    if some_check(ctx.task):
        return GuardResult("CUSTOM-01", True, "Check passed")
    return GuardResult("CUSTOM-01", False, "Check failed",
                       fix_hint="Fix the thing")
```

**Guard contract:**

- **Input:** `GuardContext` with `task`, `relationships`, `transition_params`, `backend`.
- **Output:** `GuardResult` with `guard_id`, `passed`, `reason`, `fix_hint`, `warning`.
- Guards must be **pure evaluators** — no state mutation.

Then reference your guard ID in your state machine JSON.
