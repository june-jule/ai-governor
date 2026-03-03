"""Benchmark-only transition engine (offline, no Neo4j).

Self-contained guard logic and scoring for the offline benchmark runner.
This replaces the deprecated ``governor.governance`` module.

NOT for production use — use ``governor.engine.transition_engine`` instead.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class GuardContext:
    """Context passed to guard callables (fixture runner compatible)."""

    def __init__(
        self,
        task_id: str,
        task_data: Dict[str, Any],
        transition_params: Optional[Dict[str, Any]] = None,
    ):
        self.task_id = task_id
        self.task_data = task_data
        self.task = task_data.get("task") or {}
        self.relationships = task_data.get("relationships") or []
        self.transition_params = transition_params or {}

        # The offline benchmark runner injects these to bypass Neo4j.
        self._context_bundle: Optional[Dict[str, Any]] = None
        self._bundle_error: Optional[str] = None
        self._bundle_loaded: bool = False


class GuardResult:
    __slots__ = ("guard_id", "passed", "reason", "fix_hint", "warning")

    def __init__(
        self,
        guard_id: str,
        passed: bool,
        reason: str = "",
        fix_hint: str = "",
        warning: bool = False,
    ) -> None:
        self.guard_id = guard_id
        self.passed = passed
        self.reason = reason
        self.fix_hint = fix_hint
        self.warning = warning

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "guard_id": self.guard_id,
            "passed": bool(self.passed),
            "reason": self.reason,
            "fix_hint": self.fix_hint,
        }
        if self.warning:
            d["warning"] = True
        return d


GuardCallable = Callable[[GuardContext], GuardResult]
_guard_registry: Dict[str, GuardCallable] = {}


def register_guard(guard_id: str) -> Callable[[GuardCallable], GuardCallable]:
    def decorator(fn: GuardCallable) -> GuardCallable:
        _guard_registry[guard_id] = fn
        return fn

    return decorator


def _resolve_guard(guard_ref: Any) -> Tuple[str, GuardCallable]:
    if isinstance(guard_ref, str):
        gid = guard_ref
        fn = _guard_registry.get(gid)
        if fn is None:
            def _passthrough(ctx: GuardContext) -> GuardResult:
                return GuardResult(gid, True, f"Guard {gid} not implemented (pass-through)")

            return gid, _passthrough
        return gid, fn
    raise ValueError(f"Unsupported guard reference: {guard_ref!r}")


def _load_state_machine() -> Dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "governor" / "schema" / "state_machine.json"
    return json.loads(path.read_text(encoding="utf-8"))


_DEDUCTIONS_BY_GUARD: Dict[str, int] = {
    "EG-01": 15, "EG-02": 15, "EG-03": 5, "EG-04": 10,
    "EG-06": 10, "EG-07": 5, "EG-08": 5,
    # Additional guards can be added for activation gates — see examples/
}


@dataclass(frozen=True)
class ScoredTransition:
    final_score: int
    threshold: int
    passed_threshold: bool


def _compute_transition_score(
    *,
    guard_results: List[GuardResult],
    guard_refs: List[Any],
    task_type: str,
    scoring_config: Optional[Dict[str, Any]] = None,
) -> ScoredTransition:
    del guard_refs, task_type
    base = int((scoring_config or {}).get("base_score", 85))
    threshold = int((scoring_config or {}).get("threshold", 85))

    failed_ids = [gr.guard_id for gr in guard_results if not gr.passed]
    total_deduction = sum(int(_DEDUCTIONS_BY_GUARD.get(gid, 0)) for gid in failed_ids)
    final = max(0, base - total_deduction)

    passed = (len(failed_ids) == 0) and (final >= threshold)
    return ScoredTransition(final_score=final, threshold=threshold, passed_threshold=passed)


# ---------------------------------------------------------------------------
# Guards — Executor (EG)
# Additional guards can be added for activation gates — see examples/
# ---------------------------------------------------------------------------


def _parse_deliverables_from_content(content: str) -> List[str]:
    content = re.sub(r"```[\s\S]*?```", "", content)
    section_pattern = (
        r"(?:^|\n)(?:#{2,3}\s+|[*_]{2})Deliverables[*_]{0,2}\s*\n"
        r"([\s\S]*?)(?=\n#{2,3}\s|\n[*_]{2}[A-Z]|\Z)"
    )
    m = re.search(section_pattern, content, re.IGNORECASE)
    if not m:
        return []
    section_text = m.group(1)
    line_paths = re.findall(r"[`]([^`]+\.\w+)[`]|[-*]\s+(?:`?)([^\s`*,)]+\.\w+)(?:`?)", section_text)
    out: List[str] = []
    for a, b in line_paths:
        p = (a or b).strip()
        if p:
            out.append(p)
    seen = set()
    uniq: List[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


@register_guard("EG-01")
def eg01_self_review_exists(ctx: GuardContext) -> GuardResult:
    for r in ctx.relationships:
        if r.get("type") == "HAS_REVIEW":
            node = r.get("node") or {}
            if node.get("review_type") == "SELF_REVIEW":
                return GuardResult("EG-01", True, "Self-review exists")
    return GuardResult("EG-01", False, "No SELF_REVIEW found", fix_hint="Create a self-review before submission")


@register_guard("EG-02")
def eg02_report_exists(ctx: GuardContext) -> GuardResult:
    task_type = str(ctx.task.get("task_type") or "").strip().upper()
    report_count = sum(1 for r in ctx.relationships if r.get("type") == "REPORTS_ON")
    if report_count >= 1:
        return GuardResult("EG-02", True, "Report exists")
    if task_type in {"INVESTIGATION", "AUDIT"}:
        return GuardResult("EG-02", False, f"No report found (mandatory for {task_type})", fix_hint="Create and link a report before submission")
    return GuardResult("EG-02", True, f"No report found (warning for {task_type or 'UNKNOWN'} — non-blocking)", fix_hint="Create a report for better traceability", warning=True)


@register_guard("EG-03")
def eg03_deliverables_exist(ctx: GuardContext) -> GuardResult:
    deliverables = ctx.task.get("deliverables")
    paths: List[str] = []
    if deliverables:
        if isinstance(deliverables, str):
            try:
                parsed = json.loads(deliverables)
                if isinstance(parsed, list):
                    paths = [str(x) for x in parsed]
                else:
                    paths = [p.strip() for p in str(deliverables).splitlines() if p.strip()]
            except (json.JSONDecodeError, ValueError, TypeError):
                paths = [p.strip() for p in str(deliverables).splitlines() if p.strip()]
        elif isinstance(deliverables, list):
            paths = [str(x) for x in deliverables]
    else:
        paths = _parse_deliverables_from_content(str(ctx.task.get("content") or ""))
    report_count = sum(1 for r in ctx.relationships if r.get("type") == "REPORTS_ON")
    task_type = str(ctx.task.get("task_type") or "").strip().upper()
    if not paths:
        if report_count >= 1:
            return GuardResult("EG-03", True, f"No filesystem deliverables declared; satisfied by {report_count} linked report(s)")
        if task_type in {"INVESTIGATION", "AUDIT"}:
            return GuardResult("EG-03", False, f"No deliverables declared and no report linked (required for {task_type})", fix_hint="Link a report or add deliverable file paths")
        return GuardResult("EG-03", True, "No deliverables declared (nothing to verify)")
    project_root = str(ctx.transition_params.get("project_root") or os.getcwd())
    missing = []
    for p in paths:
        p = str(p).strip()
        if not p:
            continue
        resolved = p if os.path.isabs(p) else os.path.join(project_root, p)
        if not os.path.exists(resolved):
            missing.append(p)
    if missing:
        if report_count >= 1:
            return GuardResult("EG-03", True, f"Some filesystem deliverables missing; satisfied by {report_count} linked report(s)")
        return GuardResult("EG-03", False, f"Missing deliverables: {', '.join(missing[:5])}", fix_hint="Ensure all stated deliverables exist on filesystem")
    return GuardResult("EG-03", True, f"All {len(paths)} deliverables verified")


@register_guard("EG-04")
def eg04_no_implied_deploys(ctx: GuardContext) -> GuardResult:
    task_type = str(ctx.task.get("task_type") or "").strip().upper()
    if task_type == "DEPLOY":
        return GuardResult("EG-04", True, "Skipped — DEPLOY tasks are exempt")
    content = str(ctx.task.get("content") or "")
    patterns = ["kubectl apply", "terraform apply", "gcloud app deploy", "gcloud run deploy", "gcloud functions deploy", "helm upgrade"]
    for pat in patterns:
        if pat in content:
            return GuardResult("EG-04", False, f"Forbidden deploy pattern found: {pat}", fix_hint="Remove deploy commands from non-DEPLOY task content")
    return GuardResult("EG-04", True, "No implied deploys")


@register_guard("EG-06")
def eg06_deploy_rollback_plan(ctx: GuardContext) -> GuardResult:
    task_type = str(ctx.task.get("task_type") or "").strip().upper()
    if task_type != "DEPLOY":
        return GuardResult("EG-06", True, "Skipped — task type is not DEPLOY")
    content = str(ctx.task.get("content") or "")
    if re.search(r"rollback|revert|undo|recovery|fallback", content, re.IGNORECASE):
        return GuardResult("EG-06", True, "Rollback/revert strategy found")
    return GuardResult("EG-06", False, "DEPLOY task missing rollback/revert strategy", fix_hint="Add rollback strategy to task content")


@register_guard("EG-07")
def eg07_audit_multi_source(ctx: GuardContext) -> GuardResult:
    task_type = str(ctx.task.get("task_type") or "").strip().upper()
    if task_type != "AUDIT":
        return GuardResult("EG-07", True, "Skipped — task type is not AUDIT")
    sources: set = set()
    keyword_hits = 0
    for r in ctx.relationships:
        if r.get("type") != "REPORTS_ON":
            continue
        node = r.get("node") or {}
        content = str(node.get("content") or "")
        keyword_hits += len(re.findall(r"(?:source|evidence|verified|confirmed|reference)", content, re.IGNORECASE))
        metadata = node.get("metadata")
        md_obj = None
        if isinstance(metadata, dict):
            md_obj = metadata
        elif isinstance(metadata, str) and metadata.strip():
            try:
                parsed = json.loads(metadata)
                if isinstance(parsed, dict):
                    md_obj = parsed
            except Exception:
                md_obj = None
        if isinstance(md_obj, dict):
            for key in ("evidence_sources", "sources", "references", "citations"):
                val = md_obj.get(key)
                if isinstance(val, list):
                    for item in val:
                        s = str(item or "").strip()
                        if s:
                            sources.add(s)
                elif isinstance(val, str):
                    s = val.strip()
                    if s:
                        sources.add(s)
    task_content = str(ctx.task.get("content") or "")
    keyword_hits += len(re.findall(r"(?:source|evidence|verified|confirmed|reference)", task_content, re.IGNORECASE))
    if len(sources) >= 2 or keyword_hits >= 2:
        return GuardResult("EG-07", True, f"Multi-source evidence found (keyword_refs={keyword_hits}, explicit_sources={len(sources)})")
    return GuardResult("EG-07", False, f"Need >= 2 evidence sources, found keyword_refs={keyword_hits}, explicit_sources={len(sources)}", fix_hint="Add >= 2 evidence sources to the audit task content or linked report")


@register_guard("EG-08")
def eg08_implementation_tests(ctx: GuardContext) -> GuardResult:
    task_type = str(ctx.task.get("task_type") or "").strip().upper()
    if task_type != "IMPLEMENTATION":
        return GuardResult("EG-08", True, "Skipped — task type is not IMPLEMENTATION")
    content = str(ctx.task.get("content") or "")
    footer = str(ctx.task.get("footer") or "")
    combined = f"{content}\n{footer}"
    if re.search(r"(?:test|verify|validation|assert|check)", combined, re.IGNORECASE):
        return GuardResult("EG-08", True, "Test/verification references found")
    return GuardResult("EG-08", False, "IMPLEMENTATION task missing test/verification references in task content or footer.", fix_hint="Add a test plan or verification evidence in content/footer")
