import { describe, it, expect } from "vitest";
import { createGovernorTools } from "../src/mcp/tools.js";
import { TransitionEngine } from "../src/engine/transition.js";
import { MemoryBackend } from "../src/backend/memory.js";

function makeEngine() {
  const backend = new MemoryBackend();
  const engine = new TransitionEngine(backend);
  return { backend, engine };
}

describe("createGovernorTools", () => {
  it("returns 6 tools", () => {
    const { engine } = makeEngine();
    const tools = createGovernorTools(engine);
    expect(tools).toHaveLength(6);
  });

  it("each tool has name, description, input_schema, handler", () => {
    const { engine } = makeEngine();
    const tools = createGovernorTools(engine);
    for (const tool of tools) {
      expect(tool.name).toBeTruthy();
      expect(tool.description).toBeTruthy();
      expect(tool.input_schema).toBeTruthy();
      expect(typeof tool.handler).toBe("function");
    }
  });

  it("includes expected tool names", () => {
    const { engine } = makeEngine();
    const tools = createGovernorTools(engine);
    const names = tools.map((t) => t.name);
    expect(names).toContain("governor_transition_task");
    expect(names).toContain("governor_get_available_transitions");
    expect(names).toContain("governor_get_task_audit_trail");
    expect(names).toContain("governor_get_guard_failure_hotspots");
    expect(names).toContain("governor_get_rework_lineage");
    expect(names).toContain("governor_get_policy_coverage");
  });

  it("transition tool description mentions warning field", () => {
    const { engine } = makeEngine();
    const tools = createGovernorTools(engine);
    const tool = tools.find((t) => t.name === "governor_transition_task")!;
    expect(tool.description.toLowerCase()).toContain("warning");
  });

  it("available transitions description mentions guard_warnings", () => {
    const { engine } = makeEngine();
    const tools = createGovernorTools(engine);
    const tool = tools.find((t) => t.name === "governor_get_available_transitions")!;
    expect(tool.description).toContain("guard_warnings");
    expect(tool.description).toContain("warnings_count");
  });

  it("transition handler returns a result", async () => {
    const { backend, engine } = makeEngine();
    await backend.createTask({
      task_id: "TASK_001",
      task_name: "Test",
      task_type: "IMPLEMENTATION",
      role: "DEVELOPER",
      status: "ACTIVE",
      priority: "HIGH",
      content: "Test content.",
    });

    const tools = createGovernorTools(engine);
    const handler = tools.find((t) => t.name === "governor_transition_task")!.handler;
    const result = await handler({
      task_id: "TASK_001",
      target_state: "READY_FOR_REVIEW",
      calling_role: "EXECUTOR",
      dry_run: true,
    });
    expect(result).toHaveProperty("result");
    expect(["PASS", "FAIL"]).toContain((result as Record<string, unknown>).result);
  });
});
