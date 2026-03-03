"""Example: Custom guards for code review workflows.

Shows how to register domain-specific guards that extend Governor.
"""

from governor.engine.transition_engine import GuardContext, GuardResult, register_guard


@register_guard("CR-01")
def guard_review_coverage(ctx: GuardContext) -> GuardResult:
    """CR-01: Ensure code review covers all changed files.

    Checks that the task content references the files that were changed.
    This is an example — adapt the logic to your workflow.
    """
    content = ctx.task.get("content", "")
    if "files reviewed" in content.lower() or "changes reviewed" in content.lower():
        return GuardResult("CR-01", True, "Review coverage statement found")
    return GuardResult(
        "CR-01", False, "No review coverage statement found",
        fix_hint="Add a 'Files Reviewed' section to your code review content",
    )


@register_guard("CR-02")
def guard_no_self_approval(ctx: GuardContext) -> GuardResult:
    """CR-02: Prevent self-approval — reviewer must differ from author.

    Checks that the review's reviewer_role differs from the task's role.
    """
    task_role = ctx.task.get("role", "")
    for r in ctx.relationships:
        if r.get("type") == "HAS_REVIEW":
            node = r.get("node") or {}
            reviewer = node.get("reviewer_role", "")
            if reviewer and reviewer == task_role:
                return GuardResult(
                    "CR-02", False, "Self-approval detected: reviewer matches task author",
                    fix_hint="Have a different role review the task",
                )
    return GuardResult("CR-02", True, "No self-approval detected")
