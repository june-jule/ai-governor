/**
 * TransitionEngine — the core of Governor.
 *
 * Loads a state machine, evaluates guards, applies transitions atomically,
 * and records audit events. Zero external dependencies.
 */

import { GovernorBackend } from "../backend/base.js";
import {
  GuardContext,
  GuardResult,
  type GuardCallable,
  type TransitionDef,
  type StateMachineDef,
  type TransitionResultDict,
  type TransitionEventDict,
  type AvailableTransitionDict,
  type GuardResultDict,
  type TransitionEngineOptions,
  type EventCallback,
  ErrorCode,
} from "../types.js";
import { resolveGuard, getRegistrySnapshot } from "./guards.js";
import { validateStateMachine } from "./validation.js";

// Bundled default state machine
import defaultStateMachine from "../schema/state_machine.json" with { type: "json" };

// Ensure built-in guards are registered on import
import "../guards/executor.js";

function normalizeState(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

function errorResponse(
  errorCode: string,
  message: string,
  extra: Record<string, unknown> = {},
): TransitionResultDict {
  return {
    result: "FAIL",
    error_code: errorCode,
    message,
    guard_results: [],
    dry_run: false,
    events_fired: [],
    temporal_updates: {},
    ...extra,
  };
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export class TransitionEngine {
  private _backend: GovernorBackend;
  private _roleAliases: Record<string, string>;
  private _strict: boolean;
  private _eventCallbacks: EventCallback[];
  private _stateMachine: StateMachineDef;
  private _stateMachineVersion: string;
  private _instanceGuardRegistry: Map<string, GuardCallable>;

  constructor(backend: GovernorBackend, options: TransitionEngineOptions = {}) {
    this._backend = backend;
    this._roleAliases = options.roleAliases ?? {};
    this._strict = options.strict ?? true;
    this._eventCallbacks = options.eventCallbacks ?? [];

    // Load state machine
    this._stateMachine =
      options.stateMachine ?? (defaultStateMachine as StateMachineDef);

    // Validate
    const errors = validateStateMachine(this._stateMachine);
    if (errors.length > 0) {
      throw new Error(
        `Invalid state machine:\n${errors.map((e) => `  - ${e}`).join("\n")}`,
      );
    }

    this._stateMachineVersion =
      this._stateMachine._meta?.version ?? "unknown";

    // Copy global guard registry for instance isolation
    this._instanceGuardRegistry = getRegistrySnapshot();
  }

  /**
   * Register a guard on this engine instance only.
   */
  registerGuard(
    guardId: string,
    fn: GuardCallable,
    overwrite = true,
  ): void {
    if (!overwrite && this._instanceGuardRegistry.has(guardId)) return;
    this._instanceGuardRegistry.set(guardId, fn);
  }

  /**
   * Get the loaded state machine definition.
   */
  get stateMachine(): StateMachineDef {
    return this._stateMachine;
  }

  // ------------------------------------------------------------------
  // State machine helpers
  // ------------------------------------------------------------------

  private _normalizeCallingRole(callingRole: string): string {
    const upper = callingRole.trim().toUpperCase();
    return this._roleAliases[upper] ?? upper;
  }

  private _findTransition(
    fromState: string,
    toState: string,
  ): TransitionDef | undefined {
    return this._stateMachine.transitions.find(
      (t) => t.from_state === fromState && t.to_state === toState,
    );
  }

  private _getAllTransitionsFrom(fromState: string): TransitionDef[] {
    return this._stateMachine.transitions.filter(
      (t) => t.from_state === fromState,
    );
  }

  // ------------------------------------------------------------------
  // Guard evaluation
  // ------------------------------------------------------------------

  private async _evaluateSingleGuard(
    guardId: string,
    guardFn: GuardCallable,
    ctx: GuardContext,
  ): Promise<GuardResult> {
    try {
      const result = guardFn(ctx);
      return result instanceof Promise ? await result : result;
    } catch (err) {
      return new GuardResult(
        guardId,
        false,
        `Guard threw: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  // ------------------------------------------------------------------
  // Temporal field updates
  // ------------------------------------------------------------------

  private _applyTemporalFields(
    transitionDef: TransitionDef,
    task: Record<string, unknown>,
  ): Record<string, unknown> {
    const updates: Record<string, unknown> = {};
    const tf = transitionDef.temporal_fields;
    if (!tf) return updates;

    for (const field of tf.set ?? []) {
      updates[field] = todayISO();
    }
    for (const field of tf.clear ?? []) {
      updates[field] = null;
    }
    for (const field of tf.increment ?? []) {
      const current = Number(task[field] ?? 0) || 0;
      updates[field] = current + 1;
    }
    for (const field of tf.reset ?? []) {
      updates[field] = 0;
    }
    return updates;
  }

  // ------------------------------------------------------------------
  // Event firing
  // ------------------------------------------------------------------

  private async _fireEvents(
    transitionDef: TransitionDef,
    event: TransitionEventDict,
  ): Promise<string[]> {
    const firedIds: string[] = [];
    for (const callback of this._eventCallbacks) {
      try {
        const result = callback(event);
        if (result instanceof Promise) await result;
      } catch {
        // Swallow callback errors
      }
    }
    for (const eventDef of transitionDef.events ?? []) {
      if (eventDef.event_id) firedIds.push(eventDef.event_id);
    }
    return firedIds;
  }

  // ------------------------------------------------------------------
  // Core API — transition_task
  // ------------------------------------------------------------------

  async transitionTask(
    taskId: string,
    targetState: string,
    callingRole: string,
    dryRun = false,
    transitionParams: Record<string, unknown> = {},
  ): Promise<TransitionResultDict> {
    const normalizedRole = this._normalizeCallingRole(callingRole);
    const normalizedTarget = normalizeState(targetState);

    // 1. Load task from backend
    let taskData;
    try {
      taskData = await this._backend.getTask(taskId);
    } catch (err) {
      if (err instanceof Error && err.message.includes("not found")) {
        return errorResponse(ErrorCode.TASK_NOT_FOUND, `Task not found: ${taskId}`, { task_id: taskId });
      }
      return errorResponse(
        ErrorCode.BACKEND_ERROR,
        `Backend error loading task: ${err instanceof Error ? err.message : String(err)}`,
        { task_id: taskId },
      );
    }

    const currentState = normalizeState(taskData.task.status);

    // 2. Find transition definition
    const transitionDef = this._findTransition(currentState, normalizedTarget);
    if (!transitionDef) {
      return errorResponse(
        ErrorCode.ILLEGAL_TRANSITION,
        `No transition from '${currentState}' to '${normalizedTarget}'`,
        { task_id: taskId, from_state: currentState, to_state: normalizedTarget },
      );
    }

    // 3. Check role authorization
    const allowedRoles = transitionDef.allowed_roles.map((r) =>
      r.trim().toUpperCase(),
    );
    if (!allowedRoles.includes(normalizedRole)) {
      return errorResponse(
        ErrorCode.ROLE_NOT_AUTHORIZED,
        `Role '${normalizedRole}' not authorized for transition '${transitionDef.id}' (allowed: ${allowedRoles.join(", ")})`,
        {
          task_id: taskId,
          transition_id: transitionDef.id,
          from_state: currentState,
          to_state: normalizedTarget,
        },
      );
    }

    // 4. Build guard context
    const ctx = new GuardContext(taskId, taskData, transitionParams);

    // 5. Resolve all guards
    const guardRefs = transitionDef.guards ?? [];
    const resolved: [string, GuardCallable][] = [];
    for (const ref of guardRefs) {
      try {
        resolved.push(
          resolveGuard(ref, this._strict, this._instanceGuardRegistry),
        );
      } catch (err) {
        const refId = typeof ref === "string" ? ref : (ref as { guard_id?: string }).guard_id ?? "unknown";
        return errorResponse(
          ErrorCode.GUARD_NOT_FOUND,
          `Guard '${refId}' resolution failed: ${err instanceof Error ? err.message : String(err)}`,
          { task_id: taskId, transition_id: transitionDef.id },
        );
      }
    }

    // 6. Evaluate all guards (no short-circuit)
    const guardResults: GuardResult[] = [];
    for (const [guardId, guardFn] of resolved) {
      const gr = await this._evaluateSingleGuard(guardId, guardFn, ctx);
      guardResults.push(gr);
    }

    const guardResultDicts: GuardResultDict[] = guardResults.map((gr) =>
      gr.toDict(),
    );
    const allPassed = guardResults.every((gr) => gr.passed);
    const overallResult = allPassed ? "PASS" : "FAIL";

    // Build event
    const now = new Date().toISOString();
    const eventId = `EVT_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const event: TransitionEventDict = {
      event_id: eventId,
      task_id: taskId,
      transition_id: transitionDef.id,
      from_state: currentState,
      to_state: normalizedTarget,
      calling_role: normalizedRole,
      result: overallResult,
      occurred_at: now,
      guard_results: guardResultDicts,
      dry_run: dryRun,
    };

    if (!allPassed) {
      const failedGuards = guardResults.filter((gr) => !gr.passed);
      event.rejection_reason = failedGuards
        .map((gr) => `${gr.guardId}: ${gr.reason}`)
        .join("; ");
    }

    // 7. If FAIL or dry_run: record event and return
    if (!allPassed || dryRun) {
      await this._backend.recordTransitionEvent(event);
      return {
        result: overallResult as "PASS" | "FAIL",
        transition_id: transitionDef.id,
        from_state: currentState,
        to_state: normalizedTarget,
        task_id: taskId,
        dry_run: dryRun,
        guard_results: guardResultDicts,
        events_fired: [],
        temporal_updates: {},
        ...(event.rejection_reason
          ? { rejection_reason: event.rejection_reason }
          : {}),
      };
    }

    // 8. PASS: Apply temporal fields
    const temporalUpdates = this._applyTemporalFields(
      transitionDef,
      taskData.task as Record<string, unknown>,
    );
    const stateUpdates: Record<string, unknown> = {
      status: normalizedTarget,
      ...temporalUpdates,
    };

    // 9. Atomic apply
    const applyResult = await this._backend.applyTransition(
      taskId,
      stateUpdates,
      event,
      currentState,
    );

    if (!applyResult.success) {
      const code = (applyResult.error_code as string) ?? ErrorCode.BACKEND_ERROR;
      return errorResponse(code, `Apply transition failed: ${code}`, {
        task_id: taskId,
        transition_id: transitionDef.id,
        from_state: currentState,
        to_state: normalizedTarget,
      });
    }

    // 10. Fire post-transition events
    const firedEvents = await this._fireEvents(transitionDef, event);

    return {
      result: "PASS",
      transition_id: transitionDef.id,
      from_state: currentState,
      to_state: normalizedTarget,
      task_id: taskId,
      dry_run: false,
      guard_results: guardResultDicts,
      events_fired: firedEvents,
      temporal_updates: temporalUpdates,
    };
  }

  // ------------------------------------------------------------------
  // Core API — get_available_transitions
  // ------------------------------------------------------------------

  async getAvailableTransitions(
    taskId: string,
    callingRole: string,
  ): Promise<{
    task_id: string;
    current_state: string;
    transitions: AvailableTransitionDict[];
  }> {
    const normalizedRole = this._normalizeCallingRole(callingRole);

    let taskData;
    try {
      taskData = await this._backend.getTask(taskId);
    } catch {
      return { task_id: taskId, current_state: "UNKNOWN", transitions: [] };
    }

    const currentState = normalizeState(taskData.task.status);
    const outbound = this._getAllTransitionsFrom(currentState);
    const ctx = new GuardContext(taskId, taskData);

    const results: AvailableTransitionDict[] = [];

    for (const tDef of outbound) {
      const allowedRoles = tDef.allowed_roles.map((r) =>
        r.trim().toUpperCase(),
      );
      const roleAuthorized = allowedRoles.includes(normalizedRole);

      const guardRefs = tDef.guards ?? [];
      const guardsMissing: GuardResultDict[] = [];
      const guardWarnings: GuardResultDict[] = [];
      let guardsMet = 0;

      for (const ref of guardRefs) {
        try {
          const [guardId, guardFn] = resolveGuard(
            ref,
            false,
            this._instanceGuardRegistry,
          );
          const gr = await this._evaluateSingleGuard(guardId, guardFn, ctx);
          const dict = gr.toDict();
          if (gr.passed) {
            guardsMet++;
            if (gr.warning) guardWarnings.push(dict);
          } else {
            guardsMissing.push(dict);
          }
        } catch (err) {
          guardsMissing.push({
            guard_id: typeof ref === "string" ? ref : (ref as { guard_id?: string }).guard_id ?? "unknown",
            passed: false,
            reason: `Guard resolution error: ${err instanceof Error ? err.message : String(err)}`,
            fix_hint: "Register this guard or check the guard ID spelling.",
          });
        }
      }

      results.push({
        transition_id: tDef.id,
        target_state: tDef.to_state,
        description: tDef.description ?? "",
        allowed_roles: tDef.allowed_roles,
        role_authorized: roleAuthorized,
        guards_total: guardRefs.length,
        guards_met: guardsMet,
        guards_missing: guardsMissing,
        guard_warnings: guardWarnings,
        warnings_count: guardWarnings.length,
        ready: roleAuthorized && guardsMissing.length === 0,
      });
    }

    return { task_id: taskId, current_state: currentState, transitions: results };
  }

  // ------------------------------------------------------------------
  // Batch API
  // ------------------------------------------------------------------

  async transitionTasks(
    taskIds: string[],
    targetState: string,
    callingRole: string,
    dryRun = false,
    transitionParams: Record<string, unknown> = {},
  ): Promise<TransitionResultDict[]> {
    const results: TransitionResultDict[] = [];
    for (const taskId of taskIds) {
      results.push(
        await this.transitionTask(
          taskId,
          targetState,
          callingRole,
          dryRun,
          transitionParams,
        ),
      );
    }
    return results;
  }

  // ------------------------------------------------------------------
  // Analytics (delegates to backend)
  // ------------------------------------------------------------------

  async getTaskAuditTrail(
    taskId: string,
    limit = 50,
  ): Promise<TransitionEventDict[]> {
    return this._backend.getTaskAuditTrail(taskId, limit);
  }

  async getGuardFailureHotspots(
    limit = 10,
  ): Promise<Record<string, unknown>[]> {
    return this._backend.getGuardFailureHotspots(limit);
  }

  async getPolicyCoverage(): Promise<Record<string, unknown>> {
    return this._backend.getPolicyCoverage();
  }

  async getReworkLineage(
    taskId: string,
  ): Promise<Record<string, unknown>> {
    return this._backend.getReworkLineage(taskId);
  }
}

// ------------------------------------------------------------------
// Module-level convenience functions
// ------------------------------------------------------------------

let _defaultEngine: TransitionEngine | null = null;

export function configure(
  backend: GovernorBackend,
  options: TransitionEngineOptions = {},
): TransitionEngine {
  _defaultEngine = new TransitionEngine(backend, options);
  return _defaultEngine;
}

export async function transitionTask(
  taskId: string,
  targetState: string,
  callingRole: string,
  dryRun = false,
  transitionParams: Record<string, unknown> = {},
): Promise<TransitionResultDict> {
  if (!_defaultEngine) {
    throw new Error("Call configure() before using module-level transitionTask()");
  }
  return _defaultEngine.transitionTask(
    taskId,
    targetState,
    callingRole,
    dryRun,
    transitionParams,
  );
}

export async function getAvailableTransitions(
  taskId: string,
  callingRole: string,
): Promise<{
  task_id: string;
  current_state: string;
  transitions: AvailableTransitionDict[];
}> {
  if (!_defaultEngine) {
    throw new Error(
      "Call configure() before using module-level getAvailableTransitions()",
    );
  }
  return _defaultEngine.getAvailableTransitions(taskId, callingRole);
}
