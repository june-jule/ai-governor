import { describe, it, expect } from "vitest";
import { GuardContext, GuardResult } from "../src/types.js";
import type { TaskData } from "../src/types.js";

// Import to trigger guard registration
import "../src/guards/executor.js";
import { getGuard } from "../src/engine/guards.js";

function makeCtx(
  task: Record<string, unknown>,
  relationships: Array<{ type: string; node: Record<string, unknown>; node_labels: string[] }> = [],
  params: Record<string, unknown> = {},
): GuardContext {
  return new GuardContext(
    String(task.task_id ?? "TEST_TASK"),
    { task: task as TaskData["task"], relationships },
    params,
  );
}

describe("EG-01: Self-review exists", () => {
  const guard = getGuard("EG-01")!;

  it("should pass with SELF_REVIEW", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION" }, [
      { type: "HAS_REVIEW", node: { review_type: "SELF_REVIEW" }, node_labels: ["Review"] },
    ]);
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });

  it("should fail without SELF_REVIEW", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION" }, []);
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
    expect(result.fixHint).toContain("self-review");
  });

  it("should fail with wrong review type", () => {
    const ctx = makeCtx({}, [
      { type: "HAS_REVIEW", node: { review_type: "PEER_REVIEW" }, node_labels: ["Review"] },
    ]);
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });
});

describe("EG-02: Report exists", () => {
  const guard = getGuard("EG-02")!;

  it("should pass when report linked", () => {
    const ctx = makeCtx({ task_type: "INVESTIGATION" }, [
      { type: "REPORTS_ON", node: { report_type: "INVESTIGATION" }, node_labels: ["Report"] },
    ]);
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });

  it("should fail for INVESTIGATION without report", () => {
    const ctx = makeCtx({ task_type: "INVESTIGATION" }, []);
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should warn for IMPLEMENTATION without report", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION" }, []);
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
    expect(result.warning).toBe(true);
  });
});

describe("EG-04: No implied deploys", () => {
  const guard = getGuard("EG-04")!;

  it("should pass for DEPLOY tasks", () => {
    const ctx = makeCtx({ task_type: "DEPLOY", content: "kubectl apply -f" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });

  it("should fail for non-DEPLOY with kubectl", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION", content: "Run kubectl apply -f deploy.yaml" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should pass for clean content", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION", content: "Just regular code" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });
});

describe("EG-05: No secrets in content", () => {
  const guard = getGuard("EG-05")!;

  it("should fail on password assignment", () => {
    const ctx = makeCtx({ content: 'password = "supersecret123"' });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should fail on AWS credentials", () => {
    const ctx = makeCtx({ content: "aws_access_key_id = AKIAIOSFODNN7EXAMPLE" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should fail on GitHub token", () => {
    const ctx = makeCtx({ content: "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should pass on clean content", () => {
    const ctx = makeCtx({ content: "Regular implementation notes" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });
});

describe("EG-06: Deploy rollback plan", () => {
  const guard = getGuard("EG-06")!;

  it("should pass for DEPLOY with rollback", () => {
    const ctx = makeCtx({ task_type: "DEPLOY", content: "Rollback: kubectl rollout undo" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });

  it("should fail for DEPLOY without rollback", () => {
    const ctx = makeCtx({ task_type: "DEPLOY", content: "Deploy to production" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should skip for non-DEPLOY", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION", content: "No rollback" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });
});

describe("EG-07: Audit multi-source", () => {
  const guard = getGuard("EG-07")!;

  it("should pass for AUDIT with multiple evidence references", () => {
    const ctx = makeCtx({
      task_type: "AUDIT",
      content: "Source A verified. Evidence from B confirmed. Cross-check with C.",
    });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });

  it("should fail for AUDIT with single reference", () => {
    const ctx = makeCtx({ task_type: "AUDIT", content: "One source checked." });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should skip for non-AUDIT", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION", content: "No sources" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });
});

describe("EG-08: Implementation tests", () => {
  const guard = getGuard("EG-08")!;

  it("should pass for IMPLEMENTATION with test refs", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION", content: "All tests pass." });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });

  it("should fail for IMPLEMENTATION without test refs", () => {
    const ctx = makeCtx({ task_type: "IMPLEMENTATION", content: "Deployed to staging." });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(false);
  });

  it("should skip for non-IMPLEMENTATION", () => {
    const ctx = makeCtx({ task_type: "DEPLOY", content: "No tests" });
    const result = guard(ctx) as GuardResult;
    expect(result.passed).toBe(true);
  });
});
