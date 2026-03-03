# MCP Tools Reference

This document defines the MCP tools exposed by Governor via
`governor.mcp.tools.create_governor_tools`.

It is intended for external integrators implementing MCP clients, gateways,
or tool routers.

---

## Tool List

- `governor_transition_task`
- `governor_get_available_transitions`
- `governor_get_task_audit_trail`
- `governor_get_guard_failure_hotspots`
- `governor_get_rework_lineage`
- `governor_get_policy_coverage`

---

## `governor_transition_task`

Execute or dry-run a state transition for a task.

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "task_id": {
      "type": "string",
      "description": "Task identifier"
    },
    "target_state": {
      "type": "string",
      "description": "Target state (e.g. READY_FOR_REVIEW, COMPLETED)"
    },
    "calling_role": {
      "type": "string",
      "description": "Role attempting the transition (e.g. EXECUTOR, REVIEWER)"
    },
    "dry_run": {
      "type": "boolean",
      "description": "If true, evaluate guards without applying state change",
      "default": false
    },
    "transition_params": {
      "type": "object",
      "description": "Optional transition context for guards. Only project-local path hints are accepted.",
      "properties": {
        "project_root": {
          "type": "string",
          "description": "Workspace root used for deliverable checks."
        },
        "deliverable_search_roots": {
          "type": "array",
          "description": "Optional additional subdirectories under project_root.",
          "items": {
            "type": "string"
          }
        }
      },
      "additionalProperties": false
    }
  },
  "required": [
    "task_id",
    "target_state",
    "calling_role"
  ]
}
```

### Example Request

```json
{
  "task_id": "TASK_001",
  "target_state": "READY_FOR_REVIEW",
  "calling_role": "EXECUTOR",
  "dry_run": false,
  "transition_params": {
    "project_root": ".",
    "deliverable_search_roots": ["src", "docs"]
  }
}
```

### Example Success Response

```json
{
  "result": "PASS",
  "transition_id": "T01",
  "from_state": "ACTIVE",
  "to_state": "READY_FOR_REVIEW",
  "guard_results": [
    {
      "guard_id": "EG-01",
      "passed": true,
      "reason": "Self-review exists",
      "fix_hint": ""
    }
  ],
  "dry_run": false,
  "events_fired": [],
  "temporal_updates": {
    "submitted_date": "2026-03-02"
  },
  "rejection_reason": null
}
```

### Example Conflict Response

```json
{
  "result": "FAIL",
  "error_code": "STATE_CONFLICT",
  "message": "Task state changed concurrently during transition. Expected 'ACTIVE', found 'REWORK'.",
  "guard_results": [],
  "dry_run": false,
  "events_fired": [],
  "temporal_updates": {},
  "rejection_reason": "Task state changed concurrently during transition. Expected 'ACTIVE', found 'REWORK'.",
  "from_state": "ACTIVE",
  "to_state": "READY_FOR_REVIEW"
}
```

---

## `governor_get_available_transitions`

Return transitions available for a task given a calling role, including guard
readiness details.

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "task_id": {
      "type": "string",
      "description": "Task identifier"
    },
    "calling_role": {
      "type": "string",
      "description": "Role querying transitions"
    }
  },
  "required": [
    "task_id",
    "calling_role"
  ]
}
```

### Example Request

```json
{
  "task_id": "TASK_001",
  "calling_role": "EXECUTOR"
}
```

### Example Response

```json
{
  "task_id": "TASK_001",
  "current_state": "ACTIVE",
  "transitions": [
    {
      "transition_id": "T01",
      "target_state": "READY_FOR_REVIEW",
      "description": "Executor submission gate",
      "allowed_roles": ["EXECUTOR"],
      "role_authorized": true,
      "guards_total": 8,
      "guards_met": 7,
      "guards_missing": [
        {
          "guard_id": "EG-03",
          "reason": "Missing deliverables: docs/PROOF.md",
          "fix_hint": "Ensure all stated deliverables exist on filesystem"
        }
      ],
      "ready": false
    }
  ]
}
```

---

## `governor_get_task_audit_trail`

Return persisted transition events for a task, including guard evaluations.

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "task_id": {
      "type": "string",
      "description": "Task identifier"
    },
    "limit": {
      "type": "integer",
      "description": "Max events to return",
      "default": 50
    }
  },
  "required": [
    "task_id"
  ]
}
```

### Example Request

```json
{
  "task_id": "TASK_001",
  "limit": 10
}
```

### Example Response

```json
{
  "task_id": "TASK_001",
  "events": [
    {
      "event_id": "EVT_000002",
      "task_id": "TASK_001",
      "transition_id": "T03",
      "from_state": "READY_FOR_REVIEW",
      "to_state": "REWORK",
      "calling_role": "REVIEWER",
      "result": "PASS",
      "dry_run": false,
      "rejection_reason": null,
      "occurred_at": "2026-03-02T13:00:00+00:00",
      "guard_results": []
    },
    {
      "event_id": "EVT_000001",
      "task_id": "TASK_001",
      "transition_id": "T01",
      "from_state": "ACTIVE",
      "to_state": "READY_FOR_REVIEW",
      "calling_role": "EXECUTOR",
      "result": "PASS",
      "dry_run": false,
      "rejection_reason": null,
      "occurred_at": "2026-03-02T12:00:00+00:00",
      "guard_results": [
        {
          "guard_id": "EG-01",
          "passed": true,
          "reason": "Self-review exists",
          "fix_hint": ""
        }
      ]
    }
  ]
}
```

---

## `governor_get_guard_failure_hotspots`

Return guards ranked by failure and evaluation counts.

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Max guards to return",
      "default": 10
    }
  },
  "required": []
}
```

### Example Request

```json
{
  "limit": 5
}
```

### Example Response

```json
{
  "hotspots": [
    {
      "guard_id": "EG-03",
      "evaluations": 42,
      "failures": 19
    },
    {
      "guard_id": "EG-01",
      "evaluations": 42,
      "failures": 8
    }
  ]
}
```

---

## `governor_get_rework_lineage`

Return transition lineage and rework count for a single task.

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "task_id": {
      "type": "string",
      "description": "Task identifier"
    }
  },
  "required": [
    "task_id"
  ]
}
```

### Example Request

```json
{
  "task_id": "TASK_001"
}
```

### Example Response

```json
{
  "task_id": "TASK_001",
  "rework_count": 1,
  "lineage": [
    {
      "transition_id": "T01",
      "from_state": "ACTIVE",
      "to_state": "READY_FOR_REVIEW",
      "result": "PASS",
      "occurred_at": "2026-03-02T12:00:00+00:00"
    },
    {
      "transition_id": "T03",
      "from_state": "READY_FOR_REVIEW",
      "to_state": "REWORK",
      "result": "PASS",
      "occurred_at": "2026-03-02T13:00:00+00:00"
    },
    {
      "transition_id": "T04",
      "from_state": "REWORK",
      "to_state": "READY_FOR_REVIEW",
      "result": "PASS",
      "occurred_at": "2026-03-02T13:30:00+00:00"
    }
  ]
}
```

---

## `governor_get_policy_coverage`

Return per-guard and aggregate pass/fail coverage.

### Input Schema

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

### Example Request

```json
{}
```

### Example Response

```json
{
  "guards": [
    {
      "guard_id": "EG-01",
      "evaluations": 42,
      "passes": 34,
      "fails": 8
    },
    {
      "guard_id": "EG-03",
      "evaluations": 42,
      "passes": 23,
      "fails": 19
    }
  ],
  "totals": {
    "evaluations": 84,
    "passes": 57,
    "fails": 27
  }
}
```

---

## Notes for Integrators

- `target_state`, `role`, and `task_type` are normalized internally to uppercase.
- Transition writes use optimistic concurrency and may return `STATE_CONFLICT`.
- Audit/analytics tools depend on backend support:
  - `MemoryBackend` supports these APIs in-process.
  - `Neo4jBackend` persists and queries graph-native audit entities.
