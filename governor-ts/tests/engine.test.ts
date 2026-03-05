import { describe, it, expect, beforeEach } from "vitest";
import { MemoryBackend } from "../src/backend/memory.js";
import { TransitionEngine } from "../src/engine/transition.js";

describe("TransitionEngine", () => {
  let backend: MemoryBackend;
  let engine: TransitionEngine;

  beforeEach(async () => {
    backend = new MemoryBackend();
    engine = new TransitionEngine(backend);
  });

  async function createTaskWithEvidence(
    taskId: string,
    overrides: Record<string, unknown> = {},
  ) {
    await backend.createTask({
      task_id: taskId,
      task_name: "Test task",
      task_type: "IMPLEMENTATION",
      role: "DEVELOPER",
      status: "ACTIVE",
      priority: "HIGH",
      content: "Implement the feature. Tests pass. Assertions checked.",
      ...overrides,
    });
    await backend.addReview(taskId, { review_type: "SELF_REVIEW", rating: 8 });
    await backend.addReport(taskId, { report_type: "IMPLEMENTATION" });
  }

  it("should transition ACTIVE -> READY_FOR_REVIEW with all evidence", async () => {
    await createTaskWithEvidence("TASK_001");
    const result = await engine.transitionTask(
      "TASK_001",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(result.result).toBe("PASS");
    expect(result.from_state).toBe("ACTIVE");
    expect(result.to_state).toBe("READY_FOR_REVIEW");
    expect(result.transition_id).toBe("T01");
  });

  it("should FAIL without self-review", async () => {
    await backend.createTask({
      task_id: "TASK_002",
      task_name: "No review task",
      task_type: "IMPLEMENTATION",
      role: "DEVELOPER",
      status: "ACTIVE",
      priority: "HIGH",
      content: "Implement. Tests pass.",
    });
    const result = await engine.transitionTask(
      "TASK_002",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(result.result).toBe("FAIL");
    const failed = result.guard_results?.filter((g) => !g.passed) ?? [];
    expect(failed.some((g) => g.guard_id === "EG-01")).toBe(true);
  });

  it("should reject illegal transitions", async () => {
    await createTaskWithEvidence("TASK_003");
    const result = await engine.transitionTask(
      "TASK_003",
      "COMPLETED",
      "EXECUTOR",
    );
    expect(result.result).toBe("FAIL");
    expect(result.error_code).toBe("ILLEGAL_TRANSITION");
  });

  it("should reject unauthorized roles", async () => {
    await createTaskWithEvidence("TASK_004");
    const result = await engine.transitionTask(
      "TASK_004",
      "READY_FOR_REVIEW",
      "REVIEWER",
    );
    expect(result.result).toBe("FAIL");
    expect(result.error_code).toBe("ROLE_NOT_AUTHORIZED");
  });

  it("should support dry_run mode", async () => {
    await createTaskWithEvidence("TASK_005");
    const result = await engine.transitionTask(
      "TASK_005",
      "READY_FOR_REVIEW",
      "EXECUTOR",
      true,
    );
    expect(result.result).toBe("PASS");
    expect(result.dry_run).toBe(true);

    // Task should still be in ACTIVE state
    const task = await backend.getTask("TASK_005");
    expect(task.task.status).toBe("ACTIVE");
  });

  it("should handle full lifecycle: ACTIVE -> REVIEW -> REWORK -> REVIEW -> COMPLETED", async () => {
    await createTaskWithEvidence("TASK_006");

    // T01: ACTIVE -> READY_FOR_REVIEW
    const r1 = await engine.transitionTask(
      "TASK_006",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(r1.result).toBe("PASS");

    // T03: READY_FOR_REVIEW -> REWORK (no guards)
    const r2 = await engine.transitionTask(
      "TASK_006",
      "REWORK",
      "REVIEWER",
    );
    expect(r2.result).toBe("PASS");

    // T04: REWORK -> READY_FOR_REVIEW
    const r3 = await engine.transitionTask(
      "TASK_006",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(r3.result).toBe("PASS");

    // T02: READY_FOR_REVIEW -> COMPLETED
    const r4 = await engine.transitionTask(
      "TASK_006",
      "COMPLETED",
      "REVIEWER",
    );
    expect(r4.result).toBe("PASS");

    // Verify final state
    const task = await backend.getTask("TASK_006");
    expect(task.task.status).toBe("COMPLETED");
  });

  it("should return TASK_NOT_FOUND for missing tasks", async () => {
    const result = await engine.transitionTask(
      "NONEXISTENT",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(result.result).toBe("FAIL");
    expect(result.error_code).toBe("TASK_NOT_FOUND");
  });

  it("should apply temporal fields on transition", async () => {
    await createTaskWithEvidence("TASK_007");
    await engine.transitionTask(
      "TASK_007",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    const task = await backend.getTask("TASK_007");
    expect(task.task.submitted_date).toBeDefined();
  });

  it("should support role aliases", async () => {
    const aliasedEngine = new TransitionEngine(backend, {
      roleAliases: { DEVELOPER: "EXECUTOR" },
    });
    await createTaskWithEvidence("TASK_008");
    const result = await aliasedEngine.transitionTask(
      "TASK_008",
      "READY_FOR_REVIEW",
      "DEVELOPER",
    );
    expect(result.result).toBe("PASS");
  });

  it("should get available transitions", async () => {
    await createTaskWithEvidence("TASK_009");
    const avail = await engine.getAvailableTransitions("TASK_009", "EXECUTOR");
    expect(avail.current_state).toBe("ACTIVE");
    expect(avail.transitions.length).toBeGreaterThan(0);
    const t01 = avail.transitions.find((t) => t.transition_id === "T01");
    expect(t01).toBeDefined();
    expect(t01!.role_authorized).toBe(true);
    expect(t01!.ready).toBe(true);
  });

  it("should batch transition multiple tasks", async () => {
    await createTaskWithEvidence("TASK_010");
    await createTaskWithEvidence("TASK_011");
    const results = await engine.transitionTasks(
      ["TASK_010", "TASK_011"],
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(results).toHaveLength(2);
    expect(results[0].result).toBe("PASS");
    expect(results[1].result).toBe("PASS");
  });

  it("should evaluate all guards even when first fails (no short-circuit)", async () => {
    await backend.createTask({
      task_id: "TASK_012",
      task_name: "Bare task",
      task_type: "IMPLEMENTATION",
      role: "DEVELOPER",
      status: "ACTIVE",
      priority: "HIGH",
      content: "No tests mentioned, no rollback.",
    });
    const result = await engine.transitionTask(
      "TASK_012",
      "READY_FOR_REVIEW",
      "EXECUTOR",
    );
    expect(result.result).toBe("FAIL");
    // Should have multiple guard results (all evaluated)
    expect(result.guard_results!.length).toBe(8);
  });

  it("should include guard ID in resolution error messages (strict mode)", async () => {
    const strictEngine = new TransitionEngine(backend, { strict: true });
    await backend.createTask({
      task_id: "TASK_ERR",
      task_name: "Error test",
      task_type: "IMPLEMENTATION",
      role: "DEVELOPER",
      status: "ACTIVE",
      priority: "HIGH",
      content: "test content",
    });
    // getAvailableTransitions returns { task_id, current_state, transitions }
    const result = await strictEngine.getAvailableTransitions(
      "TASK_ERR",
      "EXECUTOR",
    );
    expect(result.transitions.length).toBeGreaterThan(0);
    // Every guard_missing entry should have a non-empty reason and guard_id
    for (const t of result.transitions) {
      for (const g of t.guards_missing ?? []) {
        expect(g.reason).toBeTruthy();
        expect(g.guard_id).toBeTruthy();
      }
    }
  });
});
