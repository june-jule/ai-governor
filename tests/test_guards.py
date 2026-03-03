"""Tests for built-in guards."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from governor.engine.transition_engine import GuardContext, GuardResult

# Import guards to register them
import governor.guards.executor_guards as eg


def _make_ctx(task_overrides=None, relationships=None, params=None):
    """Helper to build a GuardContext for testing."""
    task = {
        "task_id": "TASK_TEST",
        "task_name": "Test",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Test content with sufficient length for testing.",
    }
    if task_overrides:
        task.update(task_overrides)

    task_data = {
        "task": task,
        "relationships": relationships or [],
    }
    return GuardContext("TASK_TEST", task_data, transition_params=params)


class TestExecutorGuards:
    def test_eg01_pass(self):
        rels = [{"type": "HAS_REVIEW", "node": {"review_type": "SELF_REVIEW"}, "node_labels": ["Review"]}]
        ctx = _make_ctx(relationships=rels)
        result = eg.guard_self_review_exists(ctx)
        assert result.passed is True

    def test_eg01_fail(self):
        ctx = _make_ctx()
        result = eg.guard_self_review_exists(ctx)
        assert result.passed is False

    def test_eg01_mixed_case_review_type_is_accepted(self):
        rels = [{"type": "HAS_REVIEW", "node": {"review_type": "self_review"}, "node_labels": ["Review"]}]
        ctx = _make_ctx(relationships=rels)
        result = eg.guard_self_review_exists(ctx)
        assert result.passed is True

    def test_eg02_pass(self):
        rels = [{"type": "REPORTS_ON", "node": {}, "node_labels": ["Report"]}]
        ctx = _make_ctx(relationships=rels)
        result = eg.guard_report_exists(ctx)
        assert result.passed is True

    def test_eg02_mandatory_fail(self):
        ctx = _make_ctx({"task_type": "INVESTIGATION"})
        result = eg.guard_report_exists(ctx)
        assert result.passed is False

    def test_eg02_warning(self):
        ctx = _make_ctx({"task_type": "IMPLEMENTATION"})
        result = eg.guard_report_exists(ctx)
        assert result.passed is True
        assert result.warning is True

    def test_eg02_mixed_case_task_type_is_normalized(self):
        ctx = _make_ctx({"task_type": "InVeStIgAtIoN"})
        result = eg.guard_report_exists(ctx)
        assert result.passed is False

    def test_eg04_pass(self):
        ctx = _make_ctx({"content": "Just regular code"})
        result = eg.guard_no_implied_deploys(ctx)
        assert result.passed is True

    def test_eg04_fail(self):
        ctx = _make_ctx({"content": "Run kubectl apply -f deploy.yaml"})
        result = eg.guard_no_implied_deploys(ctx)
        assert result.passed is False

    def test_eg04_detects_mixed_case_deploy_commands(self):
        ctx = _make_ctx({"content": "Run KuBectl Apply -f deploy.yaml"})
        result = eg.guard_no_implied_deploys(ctx)
        assert result.passed is False

    def test_eg04_skip_deploy_type(self):
        ctx = _make_ctx({"task_type": "DEPLOY", "content": "kubectl apply"})
        result = eg.guard_no_implied_deploys(ctx)
        assert result.passed is True

    def test_eg06_pass(self):
        ctx = _make_ctx({"task_type": "DEPLOY", "content": "Deploy with rollback strategy."})
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is True

    def test_eg06_fail(self):
        ctx = _make_ctx({"task_type": "DEPLOY", "content": "Just deploy it."})
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is False

    def test_eg06_skip_non_deploy(self):
        ctx = _make_ctx({"task_type": "IMPLEMENTATION"})
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is True

    def test_eg08_pass(self):
        ctx = _make_ctx({
            "task_type": "IMPLEMENTATION",
            "content": "Run test suite to verify correctness.",
        })
        result = eg.guard_implementation_tests(ctx)
        assert result.passed is True

    def test_eg08_fail(self):
        ctx = _make_ctx({
            "task_type": "IMPLEMENTATION",
            "content": "Just do the thing.",
        })
        result = eg.guard_implementation_tests(ctx)
        assert result.passed is False

    def test_eg08_skip_non_implementation(self):
        ctx = _make_ctx({"task_type": "INVESTIGATION"})
        result = eg.guard_implementation_tests(ctx)
        assert result.passed is True

    def test_eg06_mixed_case_deploy_is_enforced(self):
        ctx = _make_ctx({"task_type": "dePloy", "content": "ship now"})
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is False

    def test_eg03_blocks_external_absolute_paths(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")

        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": [str(outside)],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is False
        assert "Missing deliverables" in result.reason

    def test_eg03_does_not_fallback_to_workspace_basename_for_external_absolute_path(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Same basename exists inside workspace, but declared absolute path is outside.
        (workspace / "report.md").write_text("workspace file")
        outside = tmp_path / "outside" / "report.md"
        outside.parent.mkdir()
        outside.write_text("outside file")

        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": [str(outside)],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is False
        assert "Missing deliverables" in result.reason

    def test_eg03_json_object_deliverables_does_not_iterate_keys(self):
        ctx = _make_ctx(
            task_overrides={
                "task_type": "INVESTIGATION",
                "deliverables": '{"artifact":"report.md"}',
            },
            relationships=[],
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is False
        assert "No deliverables declared" in result.reason

    def test_eg03_large_content_does_not_hang(self):
        """Content exceeding the parse cap should be truncated, not cause backtracking (Bug 5)."""
        import time

        large_content = "## Deliverables\n- `file.py`\n" + ("x" * 600_000)
        start = time.monotonic()
        paths = eg._parse_deliverables_from_content(large_content)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Parsing took {elapsed:.1f}s — likely catastrophic backtracking"
        assert isinstance(paths, list)


class TestEG03PathTraversal:
    """Security tests: EG-03 must reject path traversal attacks."""

    def test_relative_traversal_outside_workspace(self, tmp_path):
        """../../etc/passwd must be rejected."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": ["../../etc/passwd"],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        # Should either fail (missing) or not claim it exists outside workspace
        assert "../../etc/passwd" not in (result.reason or "") or not result.passed

    def test_absolute_path_outside_workspace(self, tmp_path):
        """/etc/shadow must be rejected even if it exists."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": ["/etc/hosts"],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is False

    def test_deep_traversal_outside_workspace(self, tmp_path):
        """../../../tmp/evil.txt must be rejected."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": ["../../../tmp/evil.txt"],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is False

    def test_dot_dot_resolves_within_workspace_is_ok(self, tmp_path):
        """./subdir/../file.txt should resolve within workspace if file exists."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        (workspace / "file.txt").write_text("ok")
        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": ["./subdir/../file.txt"],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is True

    def test_symlink_escape_rejected(self, tmp_path):
        """Symlink pointing outside workspace must not satisfy deliverables."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = workspace / "sneaky_link.txt"
        link.symlink_to(outside)

        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": ["sneaky_link.txt"],
            },
            params={"project_root": str(workspace)},
        )
        result = eg.guard_deliverables_exist(ctx)
        # realpath resolves the symlink; _is_within should reject it
        assert result.passed is False

    def test_search_root_traversal_blocked(self, tmp_path):
        """A search root that escapes workspace via .. must be ignored."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("escaped")

        ctx = _make_ctx(
            task_overrides={
                "task_type": "IMPLEMENTATION",
                "deliverables": ["outside.txt"],
            },
            params={
                "project_root": str(workspace),
                "deliverable_search_roots": ["../../"],
            },
        )
        result = eg.guard_deliverables_exist(ctx)
        assert result.passed is False


class TestEG05FalsePositives:
    """EG-05 should not flag common non-secret patterns."""

    def test_heading_with_api_key_not_flagged(self):
        ctx = _make_ctx({"content": "## API Key Rotation Policy\n\nWe rotate keys quarterly."})
        result = eg.guard_no_secrets_in_content(ctx)
        assert result.passed is True

    def test_actual_api_key_assignment_flagged(self):
        ctx = _make_ctx({"content": "api_key = 'sk-abc123def456'"})
        result = eg.guard_no_secrets_in_content(ctx)
        assert result.passed is False

    def test_jwt_in_content_flagged(self):
        ctx = _make_ctx({"content": "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"})
        result = eg.guard_no_secrets_in_content(ctx)
        assert result.passed is False


class TestEG06Improved:
    """EG-06 should require structured rollback content, not just keyword mentions."""

    def test_negation_only_fails(self):
        ctx = _make_ctx({
            "task_type": "DEPLOY",
            "content": "Deploy to production. No rollback needed for this change.",
        })
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is False

    def test_rollback_section_heading_passes(self):
        ctx = _make_ctx({
            "task_type": "DEPLOY",
            "content": "## Deploy Plan\nDeploy v2.\n\n## Rollback Strategy\n- Revert to v1 image\n",
        })
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is True

    def test_rollback_bullet_points_pass(self):
        ctx = _make_ctx({
            "task_type": "DEPLOY",
            "content": "Deploy steps:\n- Push image\n- Rollback: revert to previous tag\n",
        })
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is True

    def test_do_not_rollback_fails(self):
        ctx = _make_ctx({
            "task_type": "DEPLOY",
            "content": "Deploy the service. Do not rollback under any circumstances.",
        })
        result = eg.guard_deploy_rollback_plan(ctx)
        assert result.passed is False

    def test_keyword_without_structure_warns(self):
        ctx = _make_ctx({
            "task_type": "DEPLOY",
            "content": "Deploy v2. If something goes wrong, rollback manually.",
        })
        result = eg.guard_deploy_rollback_plan(ctx)
        # Passes but with warning (keyword found, no structured section)
        assert result.passed is True
        assert result.warning is True


class TestEG07Improved:
    """EG-07 should count unique sentence references, not raw keyword matches."""

    def test_repeated_keyword_in_one_sentence_counts_once(self):
        ctx = _make_ctx({
            "task_type": "AUDIT",
            "content": "Source evidence: verified source from verified source.",
        })
        result = eg.guard_audit_multi_source(ctx)
        # Only 1 sentence with evidence keywords, need >= 2
        assert result.passed is False

    def test_keywords_in_distinct_sentences_pass(self):
        ctx = _make_ctx({
            "task_type": "AUDIT",
            "content": "Evidence from API logs confirms the issue. Verified against monitoring dashboard.",
        })
        result = eg.guard_audit_multi_source(ctx)
        assert result.passed is True
