import { describe, it, expect, beforeEach } from "vitest";
import { MemoryBackend } from "../src/backend/memory.js";

describe("MemoryBackend", () => {
  let backend: MemoryBackend;

  beforeEach(() => {
    backend = new MemoryBackend();
  });

  it("should create and retrieve a task", async () => {
    const taskData = {
      task_id: "TASK_001",
      task_name: "Test task",
      task_type: "IMPLEMENTATION",
      role: "DEVELOPER",
      status: "ACTIVE",
      priority: "HIGH",
      content: "Test content",
    };
    await backend.createTask(taskData);
    const result = await backend.getTask("TASK_001");
    expect(result.task.task_id).toBe("TASK_001");
    expect(result.task.status).toBe("ACTIVE");
    expect(result.task.task_type).toBe("IMPLEMENTATION");
  });

  it("should normalize task fields to uppercase", async () => {
    await backend.createTask({
      task_id: "TASK_002",
      task_type: "implementation",
      role: "developer",
      status: "active",
      priority: "high",
    });
    const result = await backend.getTask("TASK_002");
    expect(result.task.task_type).toBe("IMPLEMENTATION");
    expect(result.task.role).toBe("DEVELOPER");
    expect(result.task.status).toBe("ACTIVE");
    expect(result.task.priority).toBe("HIGH");
  });

  it("should throw on duplicate task creation", async () => {
    await backend.createTask({ task_id: "TASK_003", status: "ACTIVE" });
    await expect(
      backend.createTask({ task_id: "TASK_003", status: "ACTIVE" }),
    ).rejects.toThrow("already exists");
  });

  it("should throw on missing task", async () => {
    await expect(backend.getTask("NONEXISTENT")).rejects.toThrow("not found");
  });

  it("should update task with optimistic locking", async () => {
    await backend.createTask({ task_id: "TASK_004", status: "ACTIVE" });

    // Success case
    const r1 = await backend.updateTask(
      "TASK_004",
      { status: "READY_FOR_REVIEW" },
      "ACTIVE",
    );
    expect(r1.success).toBe(true);

    // Conflict case
    const r2 = await backend.updateTask(
      "TASK_004",
      { status: "COMPLETED" },
      "ACTIVE", // Expected ACTIVE but actual is READY_FOR_REVIEW
    );
    expect(r2.success).toBe(false);
    expect(r2.error_code).toBe("STATE_CONFLICT");
  });

  it("should build relationships from reviews/reports/handoffs", async () => {
    await backend.createTask({ task_id: "TASK_005", status: "ACTIVE" });
    await backend.addReview("TASK_005", { review_type: "SELF_REVIEW" });
    await backend.addReport("TASK_005", { report_type: "IMPLEMENTATION" });
    await backend.addHandoff("TASK_005", { handoff_id: "H_001" });

    const result = await backend.getTask("TASK_005");
    expect(result.relationships).toHaveLength(3);

    const types = result.relationships.map((r) => r.type);
    expect(types).toContain("HAS_REVIEW");
    expect(types).toContain("REPORTS_ON");
    expect(types).toContain("HANDOFF_TO");
  });

  it("should apply transitions atomically with rollback", async () => {
    await backend.createTask({ task_id: "TASK_006", status: "ACTIVE" });

    const result = await backend.applyTransition(
      "TASK_006",
      { status: "READY_FOR_REVIEW" },
      {
        event_id: "EVT_001",
        task_id: "TASK_006",
        transition_id: "T01",
        from_state: "ACTIVE",
        to_state: "READY_FOR_REVIEW",
        result: "PASS",
      },
      "ACTIVE",
    );
    expect(result.success).toBe(true);
    expect(result.event_id).toBeDefined();

    const task = await backend.getTask("TASK_006");
    expect(task.task.status).toBe("READY_FOR_REVIEW");
  });

  it("should detect STATE_CONFLICT on apply_transition", async () => {
    await backend.createTask({ task_id: "TASK_007", status: "ACTIVE" });

    const result = await backend.applyTransition(
      "TASK_007",
      { status: "COMPLETED" },
      { event_id: "EVT_002", result: "PASS" },
      "READY_FOR_REVIEW", // Wrong expected status
    );
    expect(result.success).toBe(false);
    expect(result.error_code).toBe("STATE_CONFLICT");

    // Status should remain unchanged
    const task = await backend.getTask("TASK_007");
    expect(task.task.status).toBe("ACTIVE");
  });

  it("should track audit trail", async () => {
    await backend.createTask({ task_id: "TASK_008", status: "ACTIVE" });
    await backend.recordTransitionEvent({
      event_id: "EVT_003",
      task_id: "TASK_008",
      transition_id: "T01",
      from_state: "ACTIVE",
      to_state: "READY_FOR_REVIEW",
      result: "PASS",
      occurred_at: new Date().toISOString(),
    });

    const trail = await backend.getTaskAuditTrail("TASK_008");
    expect(trail).toHaveLength(1);
    expect(trail[0].transition_id).toBe("T01");
  });

  it("should compute guard failure hotspots", async () => {
    await backend.recordTransitionEvent({
      event_id: "EVT_004",
      task_id: "TASK_009",
      result: "FAIL",
      guard_results: [
        { guard_id: "EG-01", passed: false, reason: "fail", fix_hint: "" },
        { guard_id: "EG-02", passed: true, reason: "pass", fix_hint: "" },
      ],
    });
    await backend.recordTransitionEvent({
      event_id: "EVT_005",
      task_id: "TASK_010",
      result: "FAIL",
      guard_results: [
        { guard_id: "EG-01", passed: false, reason: "fail", fix_hint: "" },
      ],
    });

    const hotspots = await backend.getGuardFailureHotspots();
    expect(hotspots[0].guard_id).toBe("EG-01");
    expect(hotspots[0].failures).toBe(2);
  });

  it("should check task existence", async () => {
    await backend.createTask({ task_id: "TASK_011", status: "ACTIVE" });
    expect(await backend.taskExists("TASK_011")).toBe(true);
    expect(await backend.taskExists("NONEXISTENT")).toBe(false);
  });

  it("should reject oversized string fields", async () => {
    const oversized = "x".repeat(1_000_001);
    await expect(
      backend.createTask({
        task_id: "TASK_BIG",
        status: "ACTIVE",
        content: oversized,
      }),
    ).rejects.toThrow("exceeds maximum size");
  });

  it("should accept fields at exactly the size limit", async () => {
    const atLimit = "x".repeat(1_000_000);
    await backend.createTask({
      task_id: "TASK_LIMIT",
      status: "ACTIVE",
      content: atLimit,
    });
    const result = await backend.getTask("TASK_LIMIT");
    expect(result.task.content).toHaveLength(1_000_000);
  });
});
