/**
 * Governor TypeScript SDK — State-machine-enforced quality gates
 * for AI agent output.
 *
 * Zero dependencies. Wire-compatible with the Python engine.
 *
 * @example
 * ```ts
 * import { MemoryBackend, TransitionEngine } from "@governor/core";
 *
 * const backend = new MemoryBackend();
 * const engine = new TransitionEngine(backend);
 *
 * await backend.createTask({
 *   task_id: "TASK_001",
 *   task_name: "My first task",
 *   task_type: "IMPLEMENTATION",
 *   role: "DEVELOPER",
 *   status: "ACTIVE",
 *   priority: "HIGH",
 *   content: "Implement the feature. Tests pass.",
 * });
 *
 * const result = await engine.transitionTask("TASK_001", "READY_FOR_REVIEW", "EXECUTOR");
 * console.log(result.result); // "PASS" or "FAIL"
 * ```
 */

// Types
export type {
  TaskDict,
  RelationshipDict,
  TaskData,
  GuardResultDict,
  TransitionResultDict,
  TransitionEventDict,
  AvailableTransitionDict,
  StateDef,
  TemporalFields,
  EventDef,
  TransitionDef,
  InlineGuardDef,
  StateMachineDef,
  UpdateResult,
  TransitionEngineOptions,
  GuardCallable,
  EventCallback,
} from "./types.js";

// Classes
export { GuardContext, GuardResult } from "./types.js";

// Enums (const objects)
export {
  TaskState,
  TransitionResult,
  ErrorCode,
  GuardID,
} from "./types.js";

// Backend
export { GovernorBackend } from "./backend/base.js";
export { MemoryBackend } from "./backend/memory.js";
export { Neo4jBackend } from "./backend/neo4j.js";
export type { Neo4jBackendOptions } from "./backend/neo4j.js";

// Engine
export {
  TransitionEngine,
  configure,
  transitionTask,
  getAvailableTransitions,
} from "./engine/transition.js";

// Guards
export {
  registerGuard,
  getGuard,
  clearGuards,
  resolveGuard,
} from "./engine/guards.js";
export { registerBuiltinGuards } from "./guards/executor.js";

// Validation
export { validateStateMachine } from "./engine/validation.js";

// Scoring
export { ScoringRubric } from "./scoring/rubric.js";
export type { RubricDef, RubricCategoryDef, Deduction, ScoreResult } from "./scoring/rubric.js";

// MCP
export { createGovernorTools } from "./mcp/tools.js";
export type { McpToolDefinition } from "./mcp/tools.js";

// Analytics
export { GovernorAnalytics } from "./analytics/graph_algorithms.js";
