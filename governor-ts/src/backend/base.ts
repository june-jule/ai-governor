/**
 * Abstract backend interface for Governor persistence.
 *
 * All task data access goes through this interface, so the Governor
 * engine works with any backend (Neo4j, PostgreSQL, in-memory, etc.).
 */

import type {
  TaskData,
  TaskDict,
  TransitionEventDict,
  UpdateResult,
} from "../types.js";

export abstract class GovernorBackend {
  // ------------------------------------------------------------------
  // Abstract methods — every backend must implement these
  // ------------------------------------------------------------------

  abstract getTask(taskId: string): Promise<TaskData>;

  abstract updateTask(
    taskId: string,
    updates: Record<string, unknown>,
    expectedCurrentStatus?: string,
  ): Promise<UpdateResult>;

  abstract taskExists(taskId: string): Promise<boolean>;

  abstract getReviewsForTask(
    taskId: string,
  ): Promise<Record<string, unknown>[]>;

  abstract getReportsForTask(
    taskId: string,
  ): Promise<Record<string, unknown>[]>;

  // ------------------------------------------------------------------
  // Lifecycle helpers (optional — defaults throw)
  // ------------------------------------------------------------------

  async createTask(taskData: TaskDict): Promise<TaskDict> {
    throw new Error(
      `${this.constructor.name} does not implement createTask()`,
    );
  }

  async addReview(
    taskId: string,
    review: Record<string, unknown>,
  ): Promise<void> {
    throw new Error(
      `${this.constructor.name} does not implement addReview()`,
    );
  }

  async addReport(
    taskId: string,
    report: Record<string, unknown>,
  ): Promise<void> {
    throw new Error(
      `${this.constructor.name} does not implement addReport()`,
    );
  }

  async addHandoff(
    taskId: string,
    handoff: Record<string, unknown>,
  ): Promise<void> {
    throw new Error(
      `${this.constructor.name} does not implement addHandoff()`,
    );
  }

  async recordTransitionEvent(
    event: TransitionEventDict,
  ): Promise<UpdateResult> {
    return { success: false, error_code: "NOT_SUPPORTED" };
  }

  async applyTransition(
    taskId: string,
    updates: Record<string, unknown>,
    event: TransitionEventDict,
    expectedCurrentStatus?: string,
  ): Promise<UpdateResult> {
    const updateResult = await this.updateTask(
      taskId,
      updates,
      expectedCurrentStatus,
    );
    if (!updateResult.success) return updateResult;

    const eventResult = await this.recordTransitionEvent(event);
    if (!eventResult.success) {
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
  }

  async healthCheck(): Promise<Record<string, unknown>> {
    return { healthy: true, backend: this.constructor.name };
  }

  async getTaskAuditTrail(
    taskId: string,
    limit = 50,
  ): Promise<TransitionEventDict[]> {
    return [];
  }

  async getGuardFailureHotspots(
    limit = 10,
  ): Promise<Record<string, unknown>[]> {
    return [];
  }

  async getPolicyCoverage(): Promise<Record<string, unknown>> {
    return {
      guards: [],
      totals: { evaluations: 0, passes: 0, fails: 0 },
    };
  }

  async getReworkLineage(
    taskId: string,
  ): Promise<Record<string, unknown>> {
    return { task_id: taskId, rework_count: 0, lineage: [] };
  }
}
