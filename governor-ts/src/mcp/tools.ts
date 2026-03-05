/**
 * MCP tool definitions for Governor TypeScript SDK.
 *
 * Exposes Governor's core API as MCP tools:
 *
 * - `governor_transition_task` — execute or dry-run a state transition
 * - `governor_get_available_transitions` — query possible transitions
 * - `governor_get_task_audit_trail` — fetch persisted transition events
 * - `governor_get_guard_failure_hotspots` — rank guards by failures
 * - `governor_get_rework_lineage` — reconstruct rework cycles for a task
 * - `governor_get_policy_coverage` — pass/fail coverage totals per guard
 *
 * @example
 * ```ts
 * import { TransitionEngine, MemoryBackend, createGovernorTools } from "@governor/core";
 *
 * const engine = new TransitionEngine(new MemoryBackend());
 * const tools = createGovernorTools(engine);
 * // Register tools with your MCP server implementation
 * ```
 */

import type { TransitionEngine } from "../engine/transition.js";

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

export interface McpToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  handler: (...args: unknown[]) => Promise<Record<string, unknown>>;
}

// ------------------------------------------------------------------
// Tool factory
// ------------------------------------------------------------------

export function createGovernorTools(engine: TransitionEngine): McpToolDefinition[] {
  // Handlers
  async function handleTransitionTask(args: {
    task_id: string;
    target_state: string;
    calling_role: string;
    dry_run?: boolean;
    transition_params?: Record<string, unknown>;
  }): Promise<Record<string, unknown>> {
    return engine.transitionTask(
      args.task_id,
      args.target_state,
      args.calling_role,
      args.dry_run ?? false,
      args.transition_params,
    );
  }

  async function handleGetAvailableTransitions(args: {
    task_id: string;
    calling_role: string;
  }): Promise<Record<string, unknown>> {
    return engine.getAvailableTransitions(args.task_id, args.calling_role);
  }

  async function handleGetTaskAuditTrail(args: {
    task_id: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    const events = await engine.getTaskAuditTrail(args.task_id, args.limit ?? 50);
    return { task_id: args.task_id, events };
  }

  async function handleGetGuardFailureHotspots(args: {
    limit?: number;
  }): Promise<Record<string, unknown>> {
    const hotspots = await engine.getGuardFailureHotspots(args.limit ?? 10);
    return { hotspots };
  }

  async function handleGetPolicyCoverage(): Promise<Record<string, unknown>> {
    return engine.getPolicyCoverage();
  }

  async function handleGetReworkLineage(args: {
    task_id: string;
  }): Promise<Record<string, unknown>> {
    return engine.getReworkLineage(args.task_id);
  }

  return [
    {
      name: "governor_transition_task",
      description:
        "Execute or dry-run a state transition for a task. " +
        "Validates role authorization, evaluates all registered guards, and " +
        "applies the state change atomically if all guards pass. " +
        "Returns a result dict with 'result' ('PASS'/'FAIL'), 'guard_results' " +
        "(per-guard verdicts with fix hints), and 'events_fired'. " +
        "Each guard_result includes: guard_id, passed (bool), reason, fix_hint, " +
        "and warning (bool). A warning=true guard passed but flagged a non-blocking " +
        "advisory — the transition still succeeds, but the caller should address " +
        "the concern. " +
        "Use dry_run=true to preview guard outcomes without mutating state. " +
        "Example: transition_task('TASK_001', 'READY_FOR_REVIEW', 'EXECUTOR') " +
        "returns FAIL with guard_results showing exactly which guards blocked and why.",
      input_schema: {
        type: "object",
        properties: {
          task_id: {
            type: "string",
            description: "Task identifier (e.g. 'TASK_001')",
            minLength: 1,
          },
          target_state: {
            type: "string",
            description: "Target state to transition to",
            enum: [
              "PENDING", "ACTIVE", "READY_FOR_REVIEW",
              "READY_FOR_GOVERNOR", "COMPLETED", "REWORK",
              "BLOCKED", "FAILED", "ARCHIVED",
            ],
          },
          calling_role: {
            type: "string",
            description: "Role attempting the transition (e.g. 'EXECUTOR', 'REVIEWER')",
            minLength: 1,
          },
          dry_run: {
            type: "boolean",
            description: "If true, evaluate guards without applying state change. Defaults to false.",
            default: false,
          },
          transition_params: {
            type: "object",
            description: "Optional context passed to guards (e.g. project_root for deliverable checks).",
          },
        },
        required: ["task_id", "target_state", "calling_role"],
      },
      handler: handleTransitionTask as McpToolDefinition["handler"],
    },
    {
      name: "governor_get_available_transitions",
      description:
        "Query which transitions are possible for a task given the calling role. " +
        "Returns the task's current state and a list of reachable transitions, each " +
        "annotated with guard readiness: guards_total, guards_met, guards_missing " +
        "(with fix hints), guard_warnings (guards that passed but flagged non-blocking " +
        "advisories), warnings_count, and a boolean 'ready' flag. " +
        "Warnings do not block the transition but indicate concerns the agent should " +
        "address. " +
        "Use this to show the agent what it needs to fix before submitting.",
      input_schema: {
        type: "object",
        properties: {
          task_id: {
            type: "string",
            description: "Task identifier (e.g. 'TASK_001')",
            minLength: 1,
          },
          calling_role: {
            type: "string",
            description: "Role querying transitions (e.g. 'EXECUTOR', 'REVIEWER')",
            minLength: 1,
          },
        },
        required: ["task_id", "calling_role"],
      },
      handler: handleGetAvailableTransitions as McpToolDefinition["handler"],
    },
    {
      name: "governor_get_task_audit_trail",
      description:
        "Fetch the transition audit trail for a task — every transition attempt " +
        "(PASS and FAIL) with embedded guard evaluations, timestamps, and calling roles. " +
        "Returns events ordered newest-first. " +
        "Use this to understand why a task is stuck or to review its full lifecycle history.",
      input_schema: {
        type: "object",
        properties: {
          task_id: {
            type: "string",
            description: "Task identifier (e.g. 'TASK_001')",
            minLength: 1,
          },
          limit: {
            type: "integer",
            description: "Max events to return (default 50, min 1)",
            default: 50,
            minimum: 1,
          },
        },
        required: ["task_id"],
      },
      handler: handleGetTaskAuditTrail as McpToolDefinition["handler"],
    },
    {
      name: "governor_get_guard_failure_hotspots",
      description:
        "Rank guards by failure count across all recorded transition events. " +
        "Returns a list of {guard_id, evaluations, failures} sorted by most failures. " +
        "Use this to identify which guards are blocking agents most often.",
      input_schema: {
        type: "object",
        properties: {
          limit: {
            type: "integer",
            description: "Max guards to return (default 10, min 1)",
            default: 10,
            minimum: 1,
          },
        },
        required: [],
      },
      handler: handleGetGuardFailureHotspots as McpToolDefinition["handler"],
    },
    {
      name: "governor_get_rework_lineage",
      description:
        "Reconstruct the full transition lineage for a task, with rework cycle count. " +
        "Returns {task_id, rework_count, lineage: [{transition_id, from_state, to_state, occurred_at}]}. " +
        "Use this to understand churn.",
      input_schema: {
        type: "object",
        properties: {
          task_id: {
            type: "string",
            description: "Task identifier (e.g. 'TASK_001')",
            minLength: 1,
          },
        },
        required: ["task_id"],
      },
      handler: handleGetReworkLineage as McpToolDefinition["handler"],
    },
    {
      name: "governor_get_policy_coverage",
      description:
        "Return guard evaluation coverage across all recorded transitions. " +
        "Shows per-guard {guard_id, evaluations, passes, fails} plus aggregate totals. " +
        "Use this to verify that all guards are being exercised.",
      input_schema: {
        type: "object",
        properties: {},
        required: [],
      },
      handler: handleGetPolicyCoverage as McpToolDefinition["handler"],
    },
  ];
}
