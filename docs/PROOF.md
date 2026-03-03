# Proof (Anonymized)

This document provides **inspectable, anonymized evidence** for key claims about the repository’s governance workflow (guarded state transitions, closeout protocol, and bounded context bundles).

## Scope (what this proves)

- **Guarded submission**: executors cannot submit work without required deliverables + required closeout artifacts (Report + Self-Review).
- **Deterministic, bounded context**: task context can be assembled into a bounded “bundle” (kernel + policies + handoffs + reports), rather than unbounded footers.
- **Redaction discipline**: evidence is shown in a way that preserves structure while removing sensitive identifiers.

## Redaction policy

The examples below have been redacted to avoid leaking sensitive data.

- **Removed/normalized**: proprietary IDs, internal project names, service URLs, customer data, absolute paths, and any credential-like strings.
- **Preserved**: state names (e.g. `ACTIVE`), guard IDs (e.g. `EG-01`), tool names, and high-level reason strings needed to validate the governance mechanics.
- **Notation**: placeholders like `<TASK_ID>`, `<HANDOFF_ID>`, `<BUNDLE_ID>` represent unique identifiers.

## Evidence 1 — Guarded submission blocks without closeout artifacts

**Input**: query available transitions for a task currently in `ACTIVE`.

**Observed output (redacted excerpt)**:

```json
{
  "task_id": "<TASK_ID>",
  "current_state": "ACTIVE",
  "transitions": [
    {
      "transition_id": "T01",
      "target_state": "READY_FOR_REVIEW",
      "description": "Executor Governor submission gate",
      "role_authorized": true,
      "guards_total": 8,
      "guards_met": 5,
      "guards_missing": [
        { "guard_id": "EG-01", "reason": "No SELF_REVIEW found" },
        { "guard_id": "EG-03", "reason": "Missing deliverables: docs/PROOF.md" },
        { "guard_id": "EG-08", "reason": "IMPLEMENTATION task missing test/verification references in task content or footer." }
      ],
      "ready": false
    }
  ]
}
```

**Interpretation**:

- The submission transition exists, the role is authorized, but it is **blocked by explicit guards**.
- This shows governance is enforced at the transition boundary (not by convention).

## Evidence 2 — Remediation loop (guards → fixes → rescan)

This repo’s workflow expects a remediation loop:

1. **Run** transition readiness checks (or dry-run a transition).
2. **Fix** missing artifacts (deliverables, self-review, report, verification notes).
3. **Re-run** readiness checks to confirm all guards pass.

**What to check after remediation**:

- `EG-03` should clear once `docs/PROOF.md` exists in-repo.
- `EG-01` should clear once a `SELF_REVIEW` node exists for the task.
- `EG-08` should clear once verification language is present (e.g. “verify”, “validation”, “check”) in the task content/footer.

**Observed output after remediation (redacted excerpt)**:

```json
{
  "task_id": "<TASK_ID>",
  "current_state": "ACTIVE",
  "transitions": [
    {
      "transition_id": "T01",
      "target_state": "READY_FOR_REVIEW",
      "guards_total": 8,
      "guards_met": 8,
      "guards_missing": [],
      "ready": true
    }
  ]
}
```

**Final acceptance signal**: a dry-run submission passes (no state change), indicating the transition is safe to execute.

```json
{
  "result": "PASS",
  "transition_id": "T01",
  "from_state": "ACTIVE",
  "to_state": "READY_FOR_REVIEW",
  "dry_run": true,
  "guard_results": [
    { "guard_id": "EG-01", "passed": true },
    { "guard_id": "EG-02", "passed": true },
    { "guard_id": "EG-03", "passed": true },
    { "guard_id": "EG-08", "passed": true }
  ]
}
```

## Evidence 3 — Bounded context bundle is generated with limits

**Input**: generate a bounded context bundle for the same task (kernel + effective policies + handoffs + reports).

**Observed output (redacted excerpt)**:

```json
{
  "bundle_version": "1.0",
  "bundle_id": "<BUNDLE_ID>",
  "task_kernel": {
    "task_id": "<TASK_ID>",
    "status": "ACTIVE",
    "role": "ORCHESTRATOR"
  },
  "limits": {
    "char_limit": 20000,
    "char_used": 6441,
    "truncated": false
  }
}
```

**Interpretation**:

- Context assembly is **explicitly bounded** by a character budget.
- The bundle has deterministic structure (kernel + policies + handoffs + reports) suitable for audits and cold starts.

## Small metrics table (with provenance)

The table below is derived from the **submission gate evaluation outputs** shown above (transition `T01`), for a single task at the moments it was queried.

| Metric | Before remediation | After remediation |
|---|---:|---:|
| Guards evaluated | 8 | 8 |
| Guards met | 5 | 8 |
| Guards missing | 3 | 0 |
| Pass rate | 62.5% | 100% |
| Top missing guards | `EG-01`, `EG-03`, `EG-08` | — |

## Notes on what this is not

- This document is **not** a disclosure of production infrastructure or private workloads.
- It is **not** a claim about a specific customer, dataset, or deployment environment.

