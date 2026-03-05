/**
 * In-memory backend for Governor — ideal for testing and demos.
 *
 * Stores tasks, reviews, and reports in plain Maps/arrays.
 * Zero external dependencies.
 */

import { GovernorBackend } from "./base.js";
import type {
  TaskData,
  TaskDict,
  RelationshipDict,
  TransitionEventDict,
  UpdateResult,
  GuardResultDict,
} from "../types.js";

const MAX_FIELD_SIZE = 1_000_000;

function normalizeField(key: string, value: unknown): unknown {
  if (value == null) return value;
  if (typeof value === "string" && value.length > MAX_FIELD_SIZE) {
    throw new Error(
      `Field '${key}' exceeds maximum size (${value.length} > ${MAX_FIELD_SIZE} chars)`,
    );
  }
  if (
    ["task_type", "status", "role", "priority"].includes(key) &&
    typeof value === "string"
  ) {
    return value.trim().toUpperCase();
  }
  return value;
}

function deepClone<T>(obj: T): T {
  if (typeof structuredClone === "function") return structuredClone(obj);
  return JSON.parse(JSON.stringify(obj));
}

export class MemoryBackend extends GovernorBackend {
  private _tasks = new Map<string, TaskDict>();
  private _reviews = new Map<string, Record<string, unknown>[]>();
  private _reports = new Map<string, Record<string, unknown>[]>();
  private _handoffs = new Map<string, Record<string, unknown>[]>();
  private _transitionEvents: TransitionEventDict[] = [];

  // ------------------------------------------------------------------
  // GovernorBackend interface
  // ------------------------------------------------------------------

  async getTask(taskId: string): Promise<TaskData> {
    const task = this._tasks.get(taskId);
    if (!task) throw new Error(`Task not found: ${taskId}`);
    return {
      task: deepClone(task),
      relationships: this._buildRelationships(taskId),
    };
  }

  async updateTask(
    taskId: string,
    updates: Record<string, unknown>,
    expectedCurrentStatus?: string,
  ): Promise<UpdateResult> {
    const task = this._tasks.get(taskId);
    if (!task) throw new Error(`Task not found during update: ${taskId}`);

    if (
      expectedCurrentStatus !== undefined &&
      task.status !== expectedCurrentStatus
    ) {
      return {
        success: false,
        error_code: "STATE_CONFLICT",
        task_id: taskId,
        expected_current_status: expectedCurrentStatus,
        actual_current_status: task.status,
      };
    }

    for (const [key, value] of Object.entries(updates)) {
      if (value == null) {
        delete (task as Record<string, unknown>)[key];
      } else {
        (task as Record<string, unknown>)[key] = normalizeField(key, value);
      }
    }
    task.last_updated = new Date().toISOString();

    return { success: true, task_id: taskId, new_status: task.status };
  }

  async taskExists(taskId: string): Promise<boolean> {
    return this._tasks.has(taskId);
  }

  async getReviewsForTask(
    taskId: string,
  ): Promise<Record<string, unknown>[]> {
    return deepClone(this._reviews.get(taskId) ?? []);
  }

  async getReportsForTask(
    taskId: string,
  ): Promise<Record<string, unknown>[]> {
    return deepClone(this._reports.get(taskId) ?? []);
  }

  // ------------------------------------------------------------------
  // Lifecycle helpers
  // ------------------------------------------------------------------

  async createTask(taskData: TaskDict): Promise<TaskDict> {
    const taskId = taskData.task_id;
    if (this._tasks.has(taskId)) {
      throw new Error(`Task already exists: ${taskId}`);
    }
    const now = new Date().toISOString();
    const task: TaskDict = { ...taskData };
    for (const [key, value] of Object.entries(task)) {
      (task as Record<string, unknown>)[key] = normalizeField(key, value);
    }
    task.created_date ??= now.slice(0, 10);
    task.last_updated ??= now;
    this._tasks.set(taskId, task);
    return deepClone(task);
  }

  async addReview(
    taskId: string,
    review: Record<string, unknown>,
  ): Promise<void> {
    const list = this._reviews.get(taskId) ?? [];
    list.push(deepClone(review));
    this._reviews.set(taskId, list);
  }

  async addReport(
    taskId: string,
    report: Record<string, unknown>,
  ): Promise<void> {
    const list = this._reports.get(taskId) ?? [];
    list.push(deepClone(report));
    this._reports.set(taskId, list);
  }

  async addHandoff(
    taskId: string,
    handoff: Record<string, unknown>,
  ): Promise<void> {
    const list = this._handoffs.get(taskId) ?? [];
    list.push(deepClone(handoff));
    this._handoffs.set(taskId, list);
  }

  async applyTransition(
    taskId: string,
    updates: Record<string, unknown>,
    event: TransitionEventDict,
    expectedCurrentStatus?: string,
  ): Promise<UpdateResult> {
    const task = this._tasks.get(taskId);
    if (!task) throw new Error(`Task not found during update: ${taskId}`);

    const original = deepClone(task);
    const originalEventsLen = this._transitionEvents.length;

    try {
      const updateResult = await this.updateTask(
        taskId,
        updates,
        expectedCurrentStatus,
      );
      if (!updateResult.success) return updateResult;

      const eventResult = await this.recordTransitionEvent(event);
      if (!eventResult.success) {
        this._tasks.set(taskId, original);
        this._transitionEvents.length = originalEventsLen;
        return {
          success: false,
          error_code: "EVENT_WRITE_FAILED",
          task_id: taskId,
        };
      }

      return {
        success: true,
        task_id: taskId,
        new_status: updateResult.new_status,
        event_id: eventResult.event_id,
      };
    } catch (err) {
      this._tasks.set(taskId, original);
      this._transitionEvents.length = originalEventsLen;
      throw err;
    }
  }

  async recordTransitionEvent(
    event: TransitionEventDict,
  ): Promise<UpdateResult> {
    const copy = deepClone(event);
    copy.recorded_at ??= new Date().toISOString();
    copy.event_id ??= `EVT_${String(this._transitionEvents.length + 1).padStart(6, "0")}`;
    this._transitionEvents.push(copy);
    return { success: true, event_id: copy.event_id };
  }

  async getTaskAuditTrail(
    taskId: string,
    limit = 50,
  ): Promise<TransitionEventDict[]> {
    const safeLimit = Math.max(1, limit);
    const matching = this._transitionEvents.filter(
      (e) => e.task_id === taskId,
    );
    matching.sort((a, b) => {
      const ka = (a.occurred_at ?? a.recorded_at ?? a.event_id ?? "") as string;
      const kb = (b.occurred_at ?? b.recorded_at ?? b.event_id ?? "") as string;
      return kb.localeCompare(ka);
    });
    return deepClone(matching.slice(0, safeLimit));
  }

  async getGuardFailureHotspots(
    limit = 10,
  ): Promise<Record<string, unknown>[]> {
    const safeLimit = Math.max(1, limit);
    const counts = new Map<
      string,
      { guard_id: string; evaluations: number; failures: number }
    >();
    for (const event of this._transitionEvents) {
      for (const gr of (event.guard_results ?? []) as GuardResultDict[]) {
        const gid = gr.guard_id ?? "UNKNOWN";
        const entry = counts.get(gid) ?? {
          guard_id: gid,
          evaluations: 0,
          failures: 0,
        };
        entry.evaluations++;
        if (!gr.passed) entry.failures++;
        counts.set(gid, entry);
      }
    }
    const ranked = [...counts.values()].sort(
      (a, b) => b.failures - a.failures || b.evaluations - a.evaluations,
    );
    return ranked.slice(0, safeLimit);
  }

  async getPolicyCoverage(): Promise<Record<string, unknown>> {
    const stats = new Map<
      string,
      { evaluations: number; passes: number; fails: number }
    >();
    let totalEvals = 0;
    let totalPass = 0;
    let totalFail = 0;

    for (const event of this._transitionEvents) {
      for (const gr of (event.guard_results ?? []) as GuardResultDict[]) {
        const gid = gr.guard_id ?? "UNKNOWN";
        const item = stats.get(gid) ?? {
          evaluations: 0,
          passes: 0,
          fails: 0,
        };
        item.evaluations++;
        totalEvals++;
        if (gr.passed) {
          item.passes++;
          totalPass++;
        } else {
          item.fails++;
          totalFail++;
        }
        stats.set(gid, item);
      }
    }

    const guards = [...stats.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([gid, vals]) => ({ guard_id: gid, ...vals }));

    return {
      guards,
      totals: {
        evaluations: totalEvals,
        passes: totalPass,
        fails: totalFail,
      },
    };
  }

  async getReworkLineage(
    taskId: string,
  ): Promise<Record<string, unknown>> {
    const events = this._transitionEvents.filter(
      (e) => e.task_id === taskId,
    );
    const lineage = events
      .filter((e) => e.result === "PASS")
      .map((e) => ({
        transition_id: e.transition_id,
        from_state: e.from_state,
        to_state: e.to_state,
        result: e.result,
        occurred_at: e.occurred_at,
      }));
    const reworkCount = lineage.filter(
      (e) => e.to_state === "REWORK",
    ).length;
    return { task_id: taskId, rework_count: reworkCount, lineage };
  }

  getAllTasks(): Map<string, TaskDict> {
    return new Map(
      [...this._tasks.entries()].map(([k, v]) => [k, deepClone(v)]),
    );
  }

  // ------------------------------------------------------------------
  // Internal helpers
  // ------------------------------------------------------------------

  private _buildRelationships(taskId: string): RelationshipDict[] {
    const rels: RelationshipDict[] = [];

    for (const review of this._reviews.get(taskId) ?? []) {
      rels.push({
        type: "HAS_REVIEW",
        node: deepClone(review),
        node_labels: ["Review"],
      });
    }
    for (const report of this._reports.get(taskId) ?? []) {
      rels.push({
        type: "REPORTS_ON",
        node: deepClone(report),
        node_labels: ["Report"],
      });
    }
    for (const handoff of this._handoffs.get(taskId) ?? []) {
      rels.push({
        type: "HANDOFF_TO",
        node: deepClone(handoff),
        node_labels: ["Handoff"],
      });
    }
    return rels;
  }
}
