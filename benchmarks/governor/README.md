# Governor Bench Fixtures (Synthetic)

This corpus is a **synthetic, non-sensitive** fixture suite for exercising the Governor guard logic + scoring in `governor/engine/transition_engine.py` **without Neo4j**.

## One-command runner

From repo root:

```bash
python3 benchmarks/run.py --pretty
```

Write machine-readable JSON output:

```bash
python3 benchmarks/run.py --out /tmp/governor_bench.json --pretty
```

## Corpus format (`corpus.jsonl`)

JSON Lines (one object per line). Minimal schema:

```json
{
  "id": "t01_pass_basic",
  "transition_id": "T01",
  "task": {
    "task_id": "FIXTURE_t01_pass_basic",
    "task_name": "Synthetic submission",
    "task_type": "IMPLEMENTATION",
    "role": "NEO4J_AGENT",
    "status": "ACTIVE",
    "priority": "HIGH",
    "content": "Implement synthetic change.\nTest: verify.\n",
    "footer": "## Completion\n- Completed: 2026-02-27\n- Deliverables: [synthetic]\n- Safety: [x] All asks addressed\n",
    "deliverables": ["governor/engine/transition_engine.py"]
  },
  "relationships": [
    { "type": "HAS_REVIEW", "node_labels": ["Review"], "node": { "review_type": "SELF_REVIEW" } }
  ],
  "context_bundle": {},
  "snapshots": {},
  "expected": {
    "passed": true,
    "failed_guards": [],
    "final_score": 85
  }
}
```

### Notes

- **Guards evaluated**: pulled from `governor/schema/state_machine.json` for the fixture’s `transition_id`.
- **Scoring**: computed by `governor/engine/transition_engine._compute_transition_score()`.
- **Long content fixtures**: to keep files small, a task may include:

```json
{ "_content_repeat": { "text": "x", "count": 17000 } }
```

The runner expands this into `task.content` before evaluating guards.

