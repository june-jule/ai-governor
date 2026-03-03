"""Example: Custom guards for deployment workflows.

Shows how to add deployment-specific safety checks.
"""

import re

from governor.engine.transition_engine import GuardContext, GuardResult, register_guard


@register_guard("DG-01")
def guard_staging_verified(ctx: GuardContext) -> GuardResult:
    """DG-01: Ensure staging environment was verified before production deploy.

    Checks task content for evidence of staging verification.
    """
    content = ctx.task.get("content", "")
    staging_patterns = [
        r"staging\s+(?:verified|tested|confirmed|passed)",
        r"(?:pre-?prod|preprod)\s+(?:verified|tested)",
        r"staging\s+environment",
    ]
    for pattern in staging_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return GuardResult("DG-01", True, "Staging verification evidence found")

    return GuardResult(
        "DG-01", False, "No staging verification evidence found",
        fix_hint="Add staging verification results to task content before deploying to production",
    )


@register_guard("DG-02")
def guard_change_window(ctx: GuardContext) -> GuardResult:
    """DG-02: Verify deployment is within an approved change window.

    This is a stub — override with your own scheduling logic.
    """
    # In a real system, check against a change management calendar
    return GuardResult("DG-02", True, "Change window check passed (default stub)")
