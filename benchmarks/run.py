#!/usr/bin/env python3
"""
Governor Benchmarks Runner (offline)

Runs a synthetic fixture corpus against the Transition Engine guard logic
without requiring Neo4j or external services.

Usage:
  python3 benchmarks/run.py
  python3 benchmarks/run.py --out /tmp/gov_bench.json --pretty
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(25):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    # Fall back to repo-root-ish heuristic (repo_root/benchmarks/run.py)
    return start.resolve().parents[1]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON on line {idx} in {path}: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"Fixture line {idx} must be an object, got {type(obj).__name__}")
        cases.append(obj)
    return cases


def _coerce_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize/expand fixture task fields into the shape guard functions expect."""
    task = dict(task or {})

    # Allow compact long-content fixtures:
    #  - _content_repeat: { "text": "x", "count": 17000 }
    repeat = task.pop("_content_repeat", None)
    if repeat and isinstance(repeat, dict):
        text = str(repeat.get("text", "x"))
        count = int(repeat.get("count", 0) or 0)
        task["content"] = str(task.get("content", "")) + (text * max(0, count))

    # Make sure optional fields exist (guards treat missing as "")
    task.setdefault("content", "")
    task.setdefault("footer", "")
    return task


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    transition_id: str
    passed: bool
    final_score: Optional[int]
    threshold: Optional[int]
    guard_results: List[Dict[str, Any]]
    failed_guards: List[str]
    warnings: List[str]
    mismatches: List[str]
    elapsed_ms: float


def _load_transition_by_id(state_machine: Dict[str, Any], transition_id: str) -> Dict[str, Any]:
    for t in state_machine.get("transitions") or []:
        if t.get("id") == transition_id:
            return t
    raise ValueError(f"Unknown transition_id '{transition_id}' in fixture (not in state_machine.json)")


def run_fixtures(fixtures_path: Path) -> Dict[str, Any]:
    repo_root = _find_repo_root(Path(__file__))
    # Ensure the repo root is importable even when running as a script
    # (`python3 benchmarks/run.py` sets sys.path[0] to `benchmarks/`).
    import sys

    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    # Import from the benchmark-local engine (self-contained, no Neo4j needed).
    from benchmarks.bench_engine import (
        GuardContext, GuardResult, _resolve_guard, _load_state_machine,
        _compute_transition_score,
    )
    import benchmarks.bench_engine as te

    cases = _read_jsonl(fixtures_path)
    state_machine = te._load_state_machine()

    per_guard: Dict[str, Dict[str, int]] = {}
    per_transition: Dict[str, Dict[str, int]] = {}
    all_outcomes: List[CaseOutcome] = []

    for case in cases:
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            raise ValueError("Fixture case missing non-empty 'id'")
        transition_id = str(case.get("transition_id") or "").strip()
        if not transition_id:
            raise ValueError(f"Fixture '{case_id}' missing non-empty 'transition_id'")

        transition = _load_transition_by_id(state_machine, transition_id)
        guard_refs: List[Any] = list(transition.get("guards") or [])
        scoring_config = transition.get("scoring")

        task = _coerce_task(case.get("task") or {})
        relationships = case.get("relationships") or []
        if not isinstance(relationships, list):
            raise ValueError(f"Fixture '{case_id}': relationships must be a list")

        # Minimal task_id fallback (some OG checks require a non-empty string)
        task.setdefault("task_id", f"FIXTURE_{case_id}")
        task_type = str(task.get("task_type") or "")

        ctx = te.GuardContext(
            task_id=str(task.get("task_id") or f"FIXTURE_{case_id}"),
            task_data={"task": task, "relationships": relationships},
            transition_params=case.get("transition_params") or {},
        )

        # Force offline mode: provide context_bundle directly to avoid Neo4j.
        ctx._context_bundle = case.get("context_bundle")  # type: ignore[attr-defined]
        ctx._bundle_error = case.get("bundle_error")  # type: ignore[attr-defined]
        ctx._bundle_loaded = True  # type: ignore[attr-defined]

        guard_results: List[te.GuardResult] = []
        guard_result_dicts: List[Dict[str, Any]] = []
        mismatches: List[str] = []
        warnings: List[str] = []

        t_start = time.perf_counter()
        for ref in guard_refs:
            gid, fn = te._resolve_guard(ref)
            gr = fn(ctx)

            guard_results.append(gr)
            gr_dict = gr.to_dict()
            guard_result_dicts.append(gr_dict)

            per_guard.setdefault(gid, {"passed": 0, "failed": 0, "warning": 0})
            if gr_dict.get("warning"):
                per_guard[gid]["warning"] += 1
                warnings.append(gid)
            if gr.passed:
                per_guard[gid]["passed"] += 1
            else:
                per_guard[gid]["failed"] += 1
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        scored = te._compute_transition_score(
            guard_results=guard_results,
            guard_refs=guard_refs,
            task_type=task_type,
            scoring_config=scoring_config,
        )

        if scored is None:
            final_score = None
            threshold = None
            passed = all(gr.passed for gr in guard_results)
        else:
            final_score = int(scored.final_score)
            threshold = int(scored.threshold)
            passed = bool(scored.passed_threshold)

        failed_guards = [gr.guard_id for gr in guard_results if not gr.passed]

        # Expected checks (optional)
        expected = case.get("expected") or {}
        if expected:
            exp_passed = expected.get("passed")
            if exp_passed is not None and bool(exp_passed) != bool(passed):
                mismatches.append(f"passed: expected={bool(exp_passed)} actual={bool(passed)}")

            exp_failed = expected.get("failed_guards")
            if exp_failed is not None:
                exp_set = sorted([str(x) for x in (exp_failed or [])])
                act_set = sorted([str(x) for x in failed_guards])
                if exp_set != act_set:
                    mismatches.append(f"failed_guards: expected={exp_set} actual={act_set}")

            exp_score = expected.get("final_score")
            if exp_score is not None:
                if final_score is None or int(exp_score) != int(final_score):
                    mismatches.append(f"final_score: expected={exp_score} actual={final_score}")

        per_transition.setdefault(transition_id, {"cases": 0, "passed": 0, "failed": 0, "mismatched": 0})
        per_transition[transition_id]["cases"] += 1
        per_transition[transition_id]["passed" if passed else "failed"] += 1
        if mismatches:
            per_transition[transition_id]["mismatched"] += 1

        all_outcomes.append(
            CaseOutcome(
                case_id=case_id,
                transition_id=transition_id,
                passed=passed,
                final_score=final_score,
                threshold=threshold,
                guard_results=guard_result_dicts,
                failed_guards=failed_guards,
                warnings=warnings,
                mismatches=mismatches,
                elapsed_ms=elapsed_ms,
            )
        )

    timings_ms = [o.elapsed_ms for o in all_outcomes]
    sorted_timings = sorted(timings_ms)

    def _percentile(data: List[float], pct: float) -> float:
        if not data:
            return 0.0
        idx = int(len(data) * pct / 100.0)
        idx = min(idx, len(data) - 1)
        return data[idx]

    timing_stats = {
        "total_ms": round(sum(timings_ms), 3),
        "avg_ms": round(statistics.mean(timings_ms), 3) if timings_ms else 0.0,
        "p50_ms": round(_percentile(sorted_timings, 50), 3),
        "p95_ms": round(_percentile(sorted_timings, 95), 3),
        "p99_ms": round(_percentile(sorted_timings, 99), 3),
        "max_ms": round(max(timings_ms), 3) if timings_ms else 0.0,
    }

    totals = {
        "cases_total": len(all_outcomes),
        "passed": sum(1 for o in all_outcomes if o.passed),
        "failed": sum(1 for o in all_outcomes if not o.passed),
        "mismatched": sum(1 for o in all_outcomes if o.mismatches),
    }

    # Sort by slowest first for easy regression spotting.
    sorted_outcomes = sorted(all_outcomes, key=lambda o: o.elapsed_ms, reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "fixtures_path": str(fixtures_path),
        "summary": totals,
        "timing": timing_stats,
        "per_transition": per_transition,
        "per_guard": per_guard,
        "cases": [
            {
                "id": o.case_id,
                "transition_id": o.transition_id,
                "passed": o.passed,
                "final_score": o.final_score,
                "threshold": o.threshold,
                "failed_guards": o.failed_guards,
                "warnings": o.warnings,
                "mismatches": o.mismatches,
                "elapsed_ms": round(o.elapsed_ms, 3),
                "guards": o.guard_results,
            }
            for o in sorted_outcomes
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    repo_root = _find_repo_root(Path(__file__))
    default_fixtures = repo_root / "benchmarks" / "governor" / "corpus.jsonl"

    ap = argparse.ArgumentParser(description="Run Governor benchmark fixtures (offline).")
    ap.add_argument("--fixtures", default=str(default_fixtures), help="Path to corpus JSONL.")
    ap.add_argument("--out", default="", help="Write JSON output to this path (default: stdout).")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    ap.add_argument("--fail-on-mismatch", action="store_true", help="Exit non-zero if any expected/actual mismatch.")
    args = ap.parse_args(argv)

    fixtures_path = Path(args.fixtures).expanduser().resolve()
    if not fixtures_path.exists():
        raise SystemExit(f"Fixtures not found: {fixtures_path}")

    result = run_fixtures(fixtures_path)
    json_text = json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_text + "\n", encoding="utf-8")
    else:
        print(json_text)

    mismatched = int(result.get("summary", {}).get("mismatched", 0) or 0)
    if args.fail_on_mismatch and mismatched > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

