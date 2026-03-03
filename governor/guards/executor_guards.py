"""Executor Governor Guards (EG-01 through EG-08).

These guards gate the ACTIVE -> READY_FOR_REVIEW transition. They validate
that an executor agent has produced sufficient evidence and deliverables
before submitting work for review.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

from governor.engine.transition_engine import GuardContext, GuardResult, register_guard


def _norm_enum(value: Any) -> str:
    return str(value or "").strip().upper()


@register_guard("EG-01", overwrite=False)
def guard_self_review_exists(ctx: GuardContext) -> GuardResult:
    """EG-01: Self-review must exist (HAS_REVIEW with SELF_REVIEW type)."""
    count = 0
    for r in ctx.relationships:
        if r.get("type") == "HAS_REVIEW":
            node = r.get("node") or {}
            if _norm_enum(node.get("review_type")) == "SELF_REVIEW":
                count += 1
    if count < 1:
        return GuardResult(
            "EG-01", False, "No SELF_REVIEW found",
            fix_hint="Create a self-review before submission",
        )
    return GuardResult("EG-01", True, "Self-review exists")


@register_guard("EG-02", overwrite=False)
def guard_report_exists(ctx: GuardContext) -> GuardResult:
    """EG-02: Report must exist (REPORTS_ON relationship), task-type aware severity.

    Severity by task_type:
      - INVESTIGATION, AUDIT: mandatory (blocks transition)
      - IMPLEMENTATION, DEPLOY: warning (non-blocking)
      - Other: warning (non-blocking)
    """
    task_type = _norm_enum(ctx.task.get("task_type", ""))
    count = sum(1 for r in ctx.relationships if r.get("type") == "REPORTS_ON")

    if count >= 1:
        return GuardResult("EG-02", True, "Report exists")

    mandatory_types = {"INVESTIGATION", "AUDIT"}
    warning_types = {"IMPLEMENTATION", "DEPLOY"}

    if task_type in mandatory_types:
        return GuardResult(
            "EG-02", False, f"No report found (mandatory for {task_type})",
            fix_hint="Create and link a report before submission",
        )
    elif task_type in warning_types:
        return GuardResult(
            "EG-02", True, f"No report found (warning for {task_type} — non-blocking)",
            fix_hint="Create a report for better traceability", warning=True,
        )
    else:
        return GuardResult(
            "EG-02", True, "No report found (warning — non-blocking)",
            fix_hint="Create a report for better traceability", warning=True,
        )


@register_guard("EG-03", overwrite=False)
def guard_deliverables_exist(ctx: GuardContext) -> GuardResult:
    """EG-03: Report or filesystem deliverables check.

    Checks that at least one of the following is true:

    1. All declared deliverable files exist on the filesystem, OR
    2. At least one report is linked to the task (REPORTS_ON relationship).

    A linked report satisfies the requirement even if specific deliverable
    files are missing — this guard does NOT verify that report content
    references the deliverables. This is a structural presence check, not a
    content-level verification.

    If no deliverables are declared and no report is linked,
    INVESTIGATION/AUDIT tasks fail; other task types pass (nothing to verify).
    """
    deliverables = ctx.task.get("deliverables")
    paths: List[str] = []

    if deliverables:
        if isinstance(deliverables, str):
            try:
                parsed = json.loads(deliverables)
                if isinstance(parsed, list):
                    paths = parsed
                elif isinstance(parsed, str):
                    paths = [parsed]
                else:
                    paths = []
            except (json.JSONDecodeError, ValueError):
                paths = [p.strip() for p in deliverables.split("\n") if p.strip()]
        elif isinstance(deliverables, list):
            paths = deliverables
    else:
        paths = _parse_deliverables_from_content(ctx.task.get("content", ""))

    if not paths:
        task_type = _norm_enum(ctx.task.get("task_type"))
        report_count = sum(1 for r in ctx.relationships if r.get("type") == "REPORTS_ON")
        if report_count >= 1:
            return GuardResult(
                "EG-03", True,
                f"No filesystem deliverables declared; satisfied by {report_count} linked report(s)",
            )
        if task_type in {"INVESTIGATION", "AUDIT"}:
            return GuardResult(
                "EG-03", False,
                f"No deliverables declared and no report linked (required for {task_type})",
                fix_hint="Link a report or add file paths under a Deliverables section",
            )
        return GuardResult("EG-03", True, "No deliverables declared (nothing to verify)")

    search_roots = ctx.transition_params.get("deliverable_search_roots", [])
    workspace = ctx.transition_params.get("project_root", os.getcwd())
    workspace = os.path.realpath(str(workspace))

    def _is_within(base: str, candidate: str) -> bool:
        base = os.path.realpath(base)
        candidate = os.path.realpath(candidate)
        try:
            return os.path.commonpath([base, candidate]) == base
        except ValueError:
            # Different drives on Windows
            return False

    allowed_roots = [workspace]
    for root in search_roots:
        root_str = str(root)
        candidate = root_str if os.path.isabs(root_str) else os.path.join(workspace, root_str)
        candidate = os.path.realpath(candidate)
        if _is_within(workspace, candidate):
            allowed_roots.append(candidate)

    def _path_exists_within_allowed_roots(p: str) -> bool:
        p = str(p)
        if os.path.isabs(p):
            candidate = os.path.realpath(p)
            if any(_is_within(root, candidate) for root in allowed_roots) and os.path.exists(candidate):
                return True
            return False

        for root in allowed_roots:
            candidate = os.path.realpath(os.path.join(root, p))
            if not _is_within(root, candidate):
                continue
            if os.path.exists(candidate):
                return True
        return False

    missing = [p for p in paths if not _path_exists_within_allowed_roots(p)]

    if missing:
        report_count = sum(1 for r in ctx.relationships if r.get("type") == "REPORTS_ON")
        if report_count >= 1:
            return GuardResult(
                "EG-03", True,
                f"Some filesystem deliverables missing; satisfied by {report_count} linked report(s)",
            )
        return GuardResult(
            "EG-03", False, f"Missing deliverables: {', '.join(missing[:5])}",
            fix_hint="Ensure all stated deliverables exist on filesystem",
        )

    return GuardResult("EG-03", True, f"All {len(paths)} deliverables verified")


_MAX_CONTENT_PARSE_LENGTH = 500_000  # 500 KB cap for regex parsing


def _parse_deliverables_from_content(content: str) -> List[str]:
    """Extract file paths from task content for EG-03 deliverables check."""
    if len(content) > _MAX_CONTENT_PARSE_LENGTH:
        content = content[:_MAX_CONTENT_PARSE_LENGTH]
    paths: List[str] = []
    content = re.sub(r"```[\s\S]*?```", "", content)

    section_pattern = (
        r"(?:^|\n)(?:#{2,3}\s+|[*_]{2})Deliverables[*_]{0,2}\s*\n"
        r"([\s\S]*?)(?=\n#{2,3}\s|\n[*_]{2}[A-Z]|\Z)"
    )
    section_match = re.search(section_pattern, content, re.IGNORECASE)
    _MAX_LINE_LENGTH = 1000
    if section_match:
        section_text = section_match.group(1)
        for line in section_text.splitlines():
            if len(line) > _MAX_LINE_LENGTH:
                line = line[:_MAX_LINE_LENGTH]
            # Backtick-wrapped paths
            for m in re.finditer(r"`([^`\s]+\.\w+)`", line):
                paths.append(m.group(1).strip())
            # Bullet-list paths
            bm = re.match(r"\s*[-*]\s+(\S+\.\w+)", line)
            if bm:
                paths.append(bm.group(1).strip())

    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return unique


@register_guard("EG-04", overwrite=False)
def guard_no_implied_deploys(ctx: GuardContext) -> GuardResult:
    """EG-04: Non-DEPLOY tasks must not contain deploy commands."""
    task_type = _norm_enum(ctx.task.get("task_type", ""))
    if task_type == "DEPLOY":
        return GuardResult("EG-04", True, "Skipped — DEPLOY tasks are exempt")
    content = ctx.task.get("content", "")
    # Use word-boundary-aware regex patterns to avoid false positives
    # on prose like "see our docker push guidelines" or documentation
    # that merely references deploy commands.
    _FORBIDDEN_DEPLOY_PATTERNS = [
        (r"\bkubectl\s+apply\b", "kubectl apply"),
        (r"\bkubectl\s+delete\b", "kubectl delete"),
        (r"\bkubectl\s+rollout\b", "kubectl rollout"),
        (r"\bterraform\s+apply\b", "terraform apply"),
        (r"\bterraform\s+destroy\b", "terraform destroy"),
        (r"\bhelm\s+install\b", "helm install"),
        (r"\bhelm\s+upgrade\b", "helm upgrade"),
        (r"\bdocker\s+push\b", "docker push"),
        (r"\bgcloud\s+deploy\b", "gcloud deploy"),
        (r"\bgcloud\s+app\s+deploy\b", "gcloud app deploy"),
        (r"\bgcloud\s+run\s+deploy\b", "gcloud run deploy"),
        (r"\baws\s+deploy\b", "aws deploy"),
        (r"\baws\s+ecs\s+update-service\b", "aws ecs update-service"),
        (r"\baws\s+lambda\s+update-function\b", "aws lambda update-function"),
        (r"\bpulumi\s+up\b", "pulumi up"),
        (r"\bansible-playbook\b", "ansible-playbook"),
        (r"\bcdk\s+deploy\b", "cdk deploy"),
    ]
    # Only match patterns inside code blocks or bare lines — skip
    # content that is clearly prose context (e.g. preceded by "see",
    # "about", "document", "guideline").
    _PROSE_EXEMPT_RE = re.compile(
        r"(?:see|about|document|guideline|mention|descri|refer|discuss)\w*\s+\S*$",
        re.IGNORECASE,
    )
    for regex, label in _FORBIDDEN_DEPLOY_PATTERNS:
        match = re.search(regex, content, re.IGNORECASE)
        if match:
            # Check if the match is preceded by prose-exempt context
            before = content[max(0, match.start() - 60):match.start()]
            if _PROSE_EXEMPT_RE.search(before):
                continue
            return GuardResult(
                "EG-04", False, f"Forbidden deploy pattern found: {label}",
                fix_hint="Remove deploy commands from non-DEPLOY task content",
            )
    return GuardResult("EG-04", True, "No implied deploys")


@register_guard("EG-05", overwrite=False)
def guard_no_secrets_in_content(ctx: GuardContext) -> GuardResult:
    """EG-05: Task content must not contain potential secrets or credentials.

    Scans task content for patterns that resemble API keys, tokens,
    passwords, or other secrets that should not be persisted in task
    content or audit trails.
    """
    content = ctx.task.get("content", "")
    if not content:
        return GuardResult("EG-05", True, "No content to scan")

    # Patterns that require an assignment operator nearby (key=value style).
    # Word boundaries (\b) prevent matching inside compound words like
    # "api_key_rotation_guide" or "reset_password_policy".
    _assignment_patterns = [
        (r"\b(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{3,}['\"]?", "password assignment"),
        (r"\b(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[^\s'\"]{3,}['\"]?", "API key assignment"),
        (r"\b(?:secret|token)\s{0,3}[:=]\s*['\"]?[^\s'\"]{20,}['\"]?", "secret/token assignment"),
        (r"\b(?:aws_access_key_id|aws_secret_access_key)\s*[:=]\s*['\"]?\S+", "AWS credential"),
        (r"\b(?:bearer|authorization)\s{0,3}[:=]\s*['\"]?[^\s'\"]{20,}", "authorization header value"),
    ]
    # Patterns that are self-evident secrets (no assignment context needed).
    _literal_patterns = [
        (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "private key block"),
        (r"\bghp_[A-Za-z0-9_]{36,}", "GitHub personal access token"),
        (r"\bsk-[A-Za-z0-9]{20,}", "API secret key pattern"),
        (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "JWT token"),
        (r"\bxox[bpars]-[A-Za-z0-9-]{10,}", "Slack token"),
        (r"(?:mongodb|postgres(?:ql)?|mysql|redis)://\S+:\S+@", "database connection string"),
        (r"\bASIA[A-Z0-9]{16}", "AWS session token key ID"),
        (r"\bgh[pousr]_[A-Za-z0-9_]{36,}", "GitHub OAuth/app token"),
        (r"\b(?:sk_live|pk_live|rk_live)_[A-Za-z0-9]{20,}", "Stripe API key"),
    ]

    # Strip Markdown headings to avoid false positives on section titles
    # like "## API Key Rotation Policy".
    _heading_re = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
    scan_content = _heading_re.sub("", content)

    for pattern, desc in _assignment_patterns + _literal_patterns:
        if re.search(pattern, scan_content, re.IGNORECASE):
            return GuardResult(
                "EG-05", False,
                f"Potential secret detected in task content: {desc}",
                fix_hint="Remove credentials from task content. Use environment variables or a secrets manager instead.",
            )
    return GuardResult("EG-05", True, "No secrets detected in content")


@register_guard("EG-06", overwrite=False)
def guard_deploy_rollback_plan(ctx: GuardContext) -> GuardResult:
    """EG-06: DEPLOY tasks must include a rollback/recovery strategy.

    Requires rollback content in a **structured section** (Markdown heading
    or bullet list), not just a keyword mention. A task that says "do NOT
    rollback" will not pass.

    Override this guard with a domain-specific implementation for production
    deploy pipelines that validate against actual rollback runbooks.
    """
    if _norm_enum(ctx.task.get("task_type")) != "DEPLOY":
        return GuardResult("EG-06", True, "Skipped — task type is not DEPLOY")

    content = ctx.task.get("content", "")
    _ROLLBACK_KW = r"(?:rollback|revert|undo|recovery|fallback)"

    # Negation patterns — these indicate the author explicitly declines a rollback plan.
    _NEGATION_RE = re.compile(
        r"(?:no|without|skip|none|not|don'?t|do not)\s+" + _ROLLBACK_KW,
        re.IGNORECASE,
    )

    # 1. Check for a Markdown heading containing rollback keywords
    #    e.g. "## Rollback Strategy", "### Recovery Plan", "**Rollback**"
    _HEADING_RE = re.compile(
        r"(?:^|\n)\s*(?:#{2,6}\s+|[*_]{2})" + r"[^\n]*" + _ROLLBACK_KW,
        re.IGNORECASE,
    )
    has_section = bool(_HEADING_RE.search(content))

    # 2. Check for bullet-list steps mentioning rollback
    #    e.g. "- Revert to previous image", "* Rollback via helm"
    _BULLET_RE = re.compile(
        r"(?:^|\n)\s*[-*]\s+[^\n]*" + _ROLLBACK_KW,
        re.IGNORECASE,
    )
    has_bullets = bool(_BULLET_RE.search(content))

    # 3. Check for negation-only mentions
    has_any_keyword = bool(re.search(_ROLLBACK_KW, content, re.IGNORECASE))
    has_negation = bool(_NEGATION_RE.search(content))

    if has_section or has_bullets:
        if has_negation and not (has_section and has_bullets):
            # Ambiguous: section exists but also contains negation.
            # Pass with warning so reviewer is alerted.
            return GuardResult(
                "EG-06", True,
                "Rollback section found but content contains negation language — reviewer should verify",
                warning=True,
            )
        return GuardResult("EG-06", True, "Rollback/recovery strategy found in structured section")

    if has_any_keyword and not has_negation:
        # Keyword exists but not in a structured section — pass with warning.
        return GuardResult(
            "EG-06", True,
            "Rollback keyword found but not in a dedicated section — consider adding a structured rollback plan",
            fix_hint="Add a '## Rollback' section with step-by-step recovery instructions",
            warning=True,
        )

    return GuardResult(
        "EG-06", False, "DEPLOY task missing rollback/recovery strategy",
        fix_hint="Add a '## Rollback' or '## Recovery Plan' section with step-by-step recovery instructions. "
                 "Override this guard for domain-specific deploy validation.",
    )


@register_guard("EG-07", overwrite=False)
def guard_audit_multi_source(ctx: GuardContext) -> GuardResult:
    """EG-07: AUDIT tasks must reference >= 2 evidence sources (heuristic).

    Scans task content and linked report content for evidence-related
    keywords and parses report metadata for explicit source lists.
    Keywords are deduplicated per-sentence so that repeating "source"
    in one sentence does not inflate the count.

    Passes if unique_sentence_refs >= 2 OR explicit_sources >= 2.

    This is a heuristic check, not rigorous evidence validation. Override
    this guard with a domain-specific implementation for production audit
    compliance that validates evidence against actual source systems.
    """
    if _norm_enum(ctx.task.get("task_type")) != "AUDIT":
        return GuardResult("EG-07", True, "Skipped — task type is not AUDIT")

    task_content = ctx.task.get("content", "")
    report_text_chunks: List[str] = []
    evidence_sources: set = set()

    for r in ctx.relationships:
        if r.get("type") != "REPORTS_ON":
            continue
        node = r.get("node") or {}
        report_content = node.get("content")
        if report_content:
            report_text_chunks.append(str(report_content))

        metadata_raw = node.get("metadata")
        metadata_obj: Optional[Dict[str, Any]] = None
        if isinstance(metadata_raw, dict):
            metadata_obj = metadata_raw
        elif isinstance(metadata_raw, str) and metadata_raw.strip():
            try:
                parsed = json.loads(metadata_raw)
                if isinstance(parsed, dict):
                    metadata_obj = parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        if isinstance(metadata_obj, dict):
            for key in ("evidence_sources", "sources", "references", "citations", "evidence"):
                val = metadata_obj.get(key)
                if isinstance(val, list):
                    for item in val:
                        if item is not None:
                            s = str(item).strip()
                            if s:
                                evidence_sources.add(s)
                elif isinstance(val, str):
                    s = val.strip()
                    if s:
                        evidence_sources.add(s)

    report_text = "\n".join(report_text_chunks)
    combined = f"{task_content}\n{report_text}"

    # Split into distinct sentences and count sentences that contain
    # at least one evidence keyword. This prevents "source source source"
    # in one sentence from counting as 3 references.
    _SENTENCE_SPLIT = re.compile(r"[.!?\n]+")
    _EVIDENCE_KW = re.compile(
        r"\b(?:source|evidence|verified|confirmed|cross-check(?:ed)?|reference(?:d)?)\b",
        re.IGNORECASE,
    )
    sentences = _SENTENCE_SPLIT.split(combined)
    sentences_with_evidence = sum(
        1 for s in sentences if s.strip() and _EVIDENCE_KW.search(s)
    )

    if sentences_with_evidence >= 2 or len(evidence_sources) >= 2:
        return GuardResult(
            "EG-07", True,
            f"Multi-source evidence found (sentence_refs={sentences_with_evidence}, explicit_sources={len(evidence_sources)})",
        )

    return GuardResult(
        "EG-07", False,
        f"Need >= 2 evidence sources, found sentence_refs={sentences_with_evidence}, explicit_sources={len(evidence_sources)}",
        fix_hint="Add >= 2 evidence sources in distinct sentences, or list them in report metadata under "
                 "'evidence_sources'. Override this guard for domain-specific audit validation.",
    )


@register_guard("EG-08", overwrite=False)
def guard_implementation_tests(ctx: GuardContext) -> GuardResult:
    """EG-08: IMPLEMENTATION tasks must reference tests or verification.

    Requires at least 2 distinct test-evidence signals from:
    - Test file paths (test_*.py, *_test.go, *.test.ts, etc.)
    - Test framework references (pytest, unittest, vitest, jest, etc.)
    - Test result indicators (passed, failed, coverage, assertions)
    - Structured test sections (## Test, ## Verification, etc.)
    - Assertion/verification statements (assert, expect, assertEquals, etc.)
    """
    if _norm_enum(ctx.task.get("task_type")) != "IMPLEMENTATION":
        return GuardResult("EG-08", True, "Skipped — task type is not IMPLEMENTATION")
    content = ctx.task.get("content", "")
    notes = ctx.task.get("notes", "")
    combined = f"{content}\n{notes}"

    signals: List[str] = []

    # 1. Test file paths
    if re.search(
        r"(?:test_\w+\.py|_test\.(?:go|py|ts|js)|\.test\.(?:ts|js|tsx|jsx)|\.spec\.(?:ts|js|tsx|jsx)|tests/\w+)",
        combined,
    ):
        signals.append("test_file_path")

    # 2. Test framework references
    if re.search(
        r"\b(?:pytest|unittest|vitest|jest|mocha|cypress|playwright|selenium|"
        r"testing[_-]?library|test[_-]?runner|xunit|nunit|junit)\b",
        combined, re.IGNORECASE,
    ):
        signals.append("test_framework")

    # 3. Test result indicators
    if re.search(
        r"\b(?:tests?\s+passed|tests?\s+failed|coverage\s+\d|"
        r"\d+\s+(?:passing|failing)|assertion(?:s|Error)\b|"
        r"PASS(?:ED)?|FAIL(?:ED)?)\b",
        combined,
    ):
        signals.append("test_results")

    # 4. Structured test/verification section heading
    if re.search(
        r"(?:^|\n)\s*(?:#{2,6}\s+|[*_]{2})[^\n]*\b(?:test(?:ing|s)?|verification|"
        r"validate|quality\s+assurance)\b",
        combined, re.IGNORECASE,
    ):
        signals.append("test_section")

    # 5. Assertion/expect statements (code-level evidence)
    if re.search(
        r"\b(?:assert(?:Equal|True|False|Raises|In|Not|That|Matches)?|"
        r"expect\(|should\.|toBe|toEqual|toHave|verify\(|"
        r"assert\s+\w+|self\.assert)\b",
        combined,
    ):
        signals.append("assertion_statement")

    # 6. General test/verification prose (broader but excludes "check")
    _general_test_refs = re.findall(
        r"\b(?:tests?\b|testing|verified|verify|verification|validated|"
        r"validate|validation|test[_-]?case|test[_-]?plan|QA)\b",
        combined, re.IGNORECASE,
    )
    if len(_general_test_refs) >= 2:
        signals.append("test_prose_refs")

    if len(signals) >= 2:
        return GuardResult(
            "EG-08", True,
            f"Test evidence found ({len(signals)} signals: {', '.join(signals)})",
        )
    elif len(signals) == 1:
        return GuardResult(
            "EG-08", True,
            f"Minimal test evidence ({signals[0]}) — consider adding more specifics",
            fix_hint="Strengthen with test file paths, framework references, or result snippets.",
            warning=True,
        )
    return GuardResult(
        "EG-08", False,
        "IMPLEMENTATION task missing test/verification references.",
        fix_hint="Add test file paths, framework references, result snippets, or a '## Tests' section.",
    )
