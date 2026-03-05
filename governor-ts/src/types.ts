/**
 * Governor TypeScript SDK — Type definitions.
 *
 * All interfaces mirror the Python TypedDicts exactly so data
 * is wire-compatible between the Python and TypeScript engines.
 */

// ------------------------------------------------------------------
// Task
// ------------------------------------------------------------------

export interface TaskDict {
  task_id: string;
  task_name?: string;
  task_type?: string;
  role?: string;
  status?: string;
  priority?: string;
  content?: string;
  deliverables?: string;
  created_date?: string;
  last_updated?: string;
  submitted_date?: string;
  completed_date?: string;
  blocked_date?: string;
  failed_date?: string;
  blocking_reason?: string;
  failure_reason?: string;
  revision_count?: number;
  notes?: string;
  [key: string]: unknown;
}

// ------------------------------------------------------------------
// Relationships (from backend.get_task)
// ------------------------------------------------------------------

export interface RelationshipDict {
  type: string;
  node: Record<string, unknown>;
  node_labels: string[];
}

export interface TaskData {
  task: TaskDict;
  relationships: RelationshipDict[];
}

// ------------------------------------------------------------------
// Guard result
// ------------------------------------------------------------------

export interface GuardResultDict {
  guard_id: string;
  passed: boolean;
  reason: string;
  fix_hint: string;
  warning?: boolean;
}

// ------------------------------------------------------------------
// Transition result
// ------------------------------------------------------------------

export interface TransitionResultDict {
  result: "PASS" | "FAIL";
  transition_id?: string;
  from_state?: string;
  to_state?: string;
  task_id?: string;
  dry_run?: boolean;
  guard_results?: GuardResultDict[];
  events_fired?: string[];
  temporal_updates?: Record<string, unknown>;
  rejection_reason?: string;
  error_code?: string;
  error?: string;
  message?: string;
  [key: string]: unknown;
}

// ------------------------------------------------------------------
// Transition event (audit trail)
// ------------------------------------------------------------------

export interface TransitionEventDict {
  event_id: string;
  task_id?: string;
  transition_id?: string;
  from_state?: string;
  to_state?: string;
  calling_role?: string;
  result?: string;
  timestamp?: string;
  occurred_at?: string;
  recorded_at?: string;
  guard_results?: GuardResultDict[];
  dry_run?: boolean;
  rejection_reason?: string;
  [key: string]: unknown;
}

// ------------------------------------------------------------------
// Available transition entry
// ------------------------------------------------------------------

export interface AvailableTransitionDict {
  transition_id: string;
  target_state: string;
  description: string;
  allowed_roles: string[];
  role_authorized: boolean;
  guards_total: number;
  guards_met: number;
  guards_missing: GuardResultDict[];
  guard_warnings: GuardResultDict[];
  warnings_count: number;
  ready: boolean;
}

// ------------------------------------------------------------------
// State machine schema
// ------------------------------------------------------------------

export interface StateDef {
  description?: string;
  terminal?: boolean;
}

export interface TemporalFields {
  set?: string[];
  clear?: string[];
  increment?: string[];
  reset?: string[];
}

export interface EventDef {
  type?: string;
  event_id?: string;
  config?: Record<string, unknown>;
}

export interface TransitionDef {
  id: string;
  from_state: string;
  to_state: string;
  description?: string;
  allowed_roles: string[];
  guards: (string | InlineGuardDef)[];
  events?: EventDef[];
  temporal_fields?: TemporalFields;
  notes?: string;
  scoring?: Record<string, unknown>;
}

export interface InlineGuardDef {
  guard_id: string;
  check?: string;
  [key: string]: unknown;
}

export interface StateMachineDef {
  _meta?: {
    schema_version?: string;
    version?: string;
    description?: string;
    created?: string;
    owner?: string;
  };
  states: Record<string, StateDef>;
  transitions: TransitionDef[];
  template_variables?: Record<string, string>;
}

// ------------------------------------------------------------------
// Enums (as const objects for zero-dep TS)
// ------------------------------------------------------------------

export const TaskState = {
  PENDING: "PENDING",
  ACTIVE: "ACTIVE",
  READY_FOR_REVIEW: "READY_FOR_REVIEW",
  READY_FOR_GOVERNOR: "READY_FOR_GOVERNOR",
  COMPLETED: "COMPLETED",
  REWORK: "REWORK",
  BLOCKED: "BLOCKED",
  FAILED: "FAILED",
  ARCHIVED: "ARCHIVED",
} as const;
export type TaskState = (typeof TaskState)[keyof typeof TaskState];

export const TransitionResult = {
  PASS: "PASS",
  FAIL: "FAIL",
} as const;
export type TransitionResult =
  (typeof TransitionResult)[keyof typeof TransitionResult];

export const ErrorCode = {
  TASK_NOT_FOUND: "TASK_NOT_FOUND",
  BACKEND_ERROR: "BACKEND_ERROR",
  ILLEGAL_TRANSITION: "ILLEGAL_TRANSITION",
  ROLE_NOT_AUTHORIZED: "ROLE_NOT_AUTHORIZED",
  GUARD_NOT_FOUND: "GUARD_NOT_FOUND",
  STATE_CONFLICT: "STATE_CONFLICT",
  EVENT_WRITE_FAILED: "EVENT_WRITE_FAILED",
  CRUD_FAILED: "CRUD_FAILED",
  RATE_LIMITED: "RATE_LIMITED",
} as const;
export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

export const GuardID = {
  SELF_REVIEW_EXISTS: "EG-01",
  REPORT_EXISTS: "EG-02",
  DELIVERABLES_EXIST: "EG-03",
  NO_IMPLIED_DEPLOYS: "EG-04",
  NO_SECRETS_IN_CONTENT: "EG-05",
  DEPLOY_ROLLBACK_PLAN: "EG-06",
  AUDIT_MULTI_SOURCE: "EG-07",
  IMPLEMENTATION_TESTS: "EG-08",
} as const;
export type GuardID = (typeof GuardID)[keyof typeof GuardID];

// ------------------------------------------------------------------
// Backend update result
// ------------------------------------------------------------------

export interface UpdateResult {
  success: boolean;
  task_id?: string;
  new_status?: string;
  event_id?: string;
  error_code?: string;
  [key: string]: unknown;
}

// ------------------------------------------------------------------
// Engine options
// ------------------------------------------------------------------

export interface TransitionEngineOptions {
  stateMachine?: StateMachineDef;
  roleAliases?: Record<string, string>;
  eventCallbacks?: EventCallback[];
  strict?: boolean;
}

export type GuardCallable = (ctx: GuardContext) => GuardResult | Promise<GuardResult>;
export type EventCallback = (event: TransitionEventDict) => void | Promise<void>;

// Forward declaration — actual classes are in their own files
export class GuardContext {
  readonly taskId: string;
  readonly task: TaskDict;
  readonly relationships: RelationshipDict[];
  readonly taskData: TaskData;
  readonly transitionParams: Record<string, unknown>;

  constructor(
    taskId: string,
    taskData: TaskData,
    transitionParams?: Record<string, unknown>,
  ) {
    this.taskId = taskId;
    this.task = taskData.task;
    this.relationships = taskData.relationships;
    this.taskData = taskData;
    this.transitionParams = transitionParams ?? {};
  }
}

export class GuardResult {
  readonly guardId: string;
  readonly passed: boolean;
  readonly reason: string;
  readonly fixHint: string;
  readonly warning: boolean;

  constructor(
    guardId: string,
    passed: boolean,
    reason = "",
    fixHint = "",
    warning = false,
  ) {
    this.guardId = guardId;
    this.passed = passed;
    this.reason = reason;
    this.fixHint = fixHint;
    this.warning = warning;
  }

  toDict(): GuardResultDict {
    return {
      guard_id: this.guardId,
      passed: this.passed,
      reason: this.reason,
      fix_hint: this.fixHint,
      ...(this.warning ? { warning: true } : {}),
    };
  }
}
