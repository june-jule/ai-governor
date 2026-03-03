# Benchmark Results — Governor Fixture Suite (Synthetic)

## What this suite covers (and doesn't)

- **Covers**: Offline evaluation of the Governor state machine and guard logic using `benchmarks/governor/corpus.jsonl`.
- **Doesn't cover**: Real workload behavior, Neo4j query performance, end-to-end orchestration, or deployment correctness. This is a **governance-logic fixture suite**, not a system benchmark.

## How to run

From repo root:

```bash
python3 benchmarks/run.py --pretty
```

Write JSON output:

```bash
python3 benchmarks/run.py --out /tmp/governor_bench.json --pretty
```

## Summary metrics (from the committed fixture suite)

**Run timestamp (UTC)**: 2026-02-27
**Corpus**: `benchmarks/governor/corpus.jsonl`

### Current results (expected/actual match)

- **Cases total**: 49
- **Expected/actual mismatches**: 0

### By transition (fixtures include intentional failures)

- **Activation (→ ACTIVE)**: 20 cases
  - Passed: 6
  - Failed: 14
- **Submission (ACTIVE → READY_FOR_REVIEW)**: 29 cases
  - Passed: 15
  - Failed: 14

## Interpretation (high-signal)

- The suite is designed to include both **PASS** and **intentional FAIL** cases; **pass rate is not a "quality score."**
- **Mismatch rate = 0** is the key health metric: fixtures' `expected` outputs match the current guard + scoring logic.
- Custom guards can extend the default set to enforce additional quality gates on submissions.

## Limitations / caution

- The corpus is **synthetic** and primarily validates **deterministic guard behavior + scoring**.
- Wall-clock runtime is **not** treated as a stable performance metric (environment-dependent, and the runner may emit unrelated connection logs depending on local configuration).
