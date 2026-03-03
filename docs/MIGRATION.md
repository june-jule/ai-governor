# Migration Guide

## v1.x → v2.0.0

### What Changed

**State Machine**: Two new states and five new transitions added.

| State | Type | Description |
|-------|------|-------------|
| `BLOCKED` | Non-terminal | Task waiting on external dependency |
| `FAILED` | Terminal | Task exhausted rework attempts or abandoned |

| Transition | From → To | Roles |
|------------|-----------|-------|
| T05 | ACTIVE → BLOCKED | EXECUTOR, REVIEWER |
| T06 | BLOCKED → ACTIVE | EXECUTOR, REVIEWER |
| T07 | REWORK → FAILED | REVIEWER |
| T08 | ACTIVE → FAILED | REVIEWER |
| T09 | BLOCKED → FAILED | REVIEWER |

**New Task Fields**:
- `blocked_date` — set when task enters BLOCKED
- `failed_date` — set when task enters FAILED
- `blocking_reason` — reason for blocking (via `transition_params`)
- `failure_reason` — reason for failure (via `transition_params`)
- `revision_count` — incremented on T03 (REWORK)

### Migration Steps

#### 1. Update the Package

```bash
pip install --upgrade ai-governor
```

#### 2. Update Neo4j Schema (if using Neo4j backend)

Run the updated schema to add new indexes:

```python
from governor.backend.neo4j_backend import Neo4jBackend

backend = Neo4jBackend.from_env()
result = backend.ensure_schema()
print(f"Applied {result['statements_applied']} schema statements")
```

Or use the new `auto_schema` flag:

```python
backend = Neo4jBackend.from_env(auto_schema=True)
```

All schema statements use `IF NOT EXISTS` — safe to re-run.

#### 3. Existing Tasks Are Unaffected

Tasks in `ACTIVE`, `READY_FOR_REVIEW`, `REWORK`, or `COMPLETED` states continue to work unchanged. The new states only apply to new transitions.

#### 4. Update Custom State Machine JSON (if applicable)

If you provide a custom `state_machine_path`, add the new states and transitions from the bundled `state_machine.json`. The engine validates the JSON on startup and will report missing states if transitions reference them.

### Breaking Changes

None. All changes are additive. The `state_machine.json` schema version is `1.1` (backward compatible). The engine version is `2.0.0` to signal the expanded state space.

---

## Guard Composition (v2.0.0)

Transitions now support an optional `guard_mode` field:

```json
{
  "id": "T01",
  "guards": ["EG-01", "EG-02", "EG-03"],
  "guard_mode": "AND"
}
```

- `"AND"` (default): All guards must pass
- `"OR"`: At least one guard must pass

This is backward compatible — existing transitions without `guard_mode` default to `"AND"`.

---

## Metrics (v2.0.0)

New `governor.metrics` module provides Prometheus-compatible metrics:

```python
from governor.metrics import get_metrics, prometheus_available

metrics = get_metrics()
snapshot = metrics.snapshot()  # Always works (dict fallback)
```

Install `prometheus_client` for full Prometheus scrape endpoint support:

```bash
pip install prometheus_client
```

---

## Webhook Callbacks (v2.0.0)

New `governor.callbacks.webhook` module:

```python
from governor.callbacks.webhook import WebhookCallback

webhook = WebhookCallback(
    url="https://example.com/hooks/governor",
    secret="my-signing-secret",
)

engine = TransitionEngine(
    backend=backend,
    event_callbacks=[webhook],
)
```

---

## Neo4j Event Retention / TTL (v2.0.0)

New `purge_old_events()` method on `Neo4jBackend`:

```python
# Dry run first
result = backend.purge_old_events(older_than_days=90, dry_run=True)
print(f"Would delete {result['events_matched']} events")

# Execute
result = backend.purge_old_events(older_than_days=90, dry_run=False)
print(f"Deleted {result.get('events_deleted', 0)} events")
```
