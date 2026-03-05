/**
 * Graph algorithm integration for Governor TypeScript SDK.
 *
 * Provides analytics methods that leverage Neo4j's graph structure:
 *
 * - **Ready now** (no GDS needed): guard bottlenecks, rework hotspots,
 *   guard co-occurrence, role efficiency, transition timeline.
 * - **Requires GDS**: PageRank, betweenness centrality, SCC, Louvain
 *   (stubbed with informative errors).
 *
 * @example
 * ```ts
 * import { Neo4jBackend, GovernorAnalytics } from "@governor/core";
 *
 * const backend = await Neo4jBackend.fromEnv();
 * const analytics = new GovernorAnalytics(backend);
 *
 * const bottlenecks = await analytics.getGuardBottlenecks(5);
 * const hotspots = await analytics.getReworkHotspots(5);
 * ```
 */

import type { Neo4jBackend } from "../backend/neo4j.js";

// ------------------------------------------------------------------
// GovernorAnalytics
// ------------------------------------------------------------------

export class GovernorAnalytics {
  private readonly _backend: Neo4jBackend;

  constructor(backend: Neo4jBackend) {
    this._backend = backend;
  }

  // ================================================================
  // Ready NOW — work with existing schema, no GDS needed
  // ================================================================

  /**
   * Identify guards that block the most tasks.
   *
   * Uses aggregation on GuardEvaluation nodes to find guards with
   * the highest failure-to-evaluation ratio.
   */
  async getGuardBottlenecks(
    limit: number = 10,
  ): Promise<Record<string, unknown>[]> {
    return this._backend.runReadQuery(
      `MATCH (ge:GuardEvaluation)
       WITH ge.guard_id AS guard_id,
            count(ge) AS evaluations,
            sum(CASE WHEN ge.passed THEN 0 ELSE 1 END) AS failures
       RETURN guard_id, evaluations, failures,
              round(100.0 * failures / evaluations, 1) AS failure_rate
       ORDER BY failures DESC
       LIMIT $limit`,
      { limit },
    );
  }

  /**
   * Find tasks with the most rework cycles.
   *
   * Aggregates TransitionEvent nodes where to_state='REWORK'.
   */
  async getReworkHotspots(
    limit: number = 10,
  ): Promise<Record<string, unknown>[]> {
    return this._backend.runReadQuery(
      `MATCH (t:Task)-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
       WHERE te.to_state = 'REWORK'
       WITH t, count(te) AS rework_cycles
       RETURN t.task_id AS task_id,
              t.task_type AS task_type,
              t.role AS role,
              t.status AS status,
              rework_cycles
       ORDER BY rework_cycles DESC
       LIMIT $limit`,
      { limit },
    );
  }

  /**
   * Find guards that frequently fail together.
   *
   * When two guards consistently co-fail on the same transition event,
   * it indicates a systemic issue.
   */
  async getGuardCooccurrence(
    minCooccurrence: number = 2,
    limit: number = 15,
  ): Promise<Record<string, unknown>[]> {
    return this._backend.runReadQuery(
      `MATCH (te:TransitionEvent)-[:HAS_GUARD_EVALUATION]->(ge1:GuardEvaluation)
       WHERE NOT ge1.passed
       WITH te, ge1
       MATCH (te)-[:HAS_GUARD_EVALUATION]->(ge2:GuardEvaluation)
       WHERE NOT ge2.passed AND ge1.guard_id < ge2.guard_id
       WITH ge1.guard_id AS guard_a, ge2.guard_id AS guard_b,
            count(*) AS co_failures
       WHERE co_failures >= $min_cooccurrence
       RETURN guard_a, guard_b, co_failures
       ORDER BY co_failures DESC
       LIMIT $limit`,
      { min_cooccurrence: minCooccurrence, limit },
    );
  }

  /**
   * Measure pass/fail rates per role.
   *
   * @param since - Optional ISO date string to filter by occurred_at.
   */
  async getRoleEfficiency(
    since?: string,
  ): Promise<Record<string, unknown>[]> {
    const params: Record<string, unknown> = {};
    let whereClause = "";
    if (since) {
      whereClause = "WHERE te.occurred_at >= $since";
      params.since = since;
    }
    return this._backend.runReadQuery(
      `MATCH (te:TransitionEvent)
       ${whereClause}
       RETURN te.calling_role AS role,
              count(te) AS total_transitions,
              sum(CASE WHEN te.result = 'PASS' THEN 1 ELSE 0 END) AS passes,
              sum(CASE WHEN te.result = 'FAIL' THEN 1 ELSE 0 END) AS fails,
              round(100.0 * sum(CASE WHEN te.result = 'PASS' THEN 1 ELSE 0 END) /
                    count(te), 1) AS pass_rate
       ORDER BY total_transitions DESC`,
      params,
    );
  }

  /**
   * Get transition event timeline, optionally filtered by task.
   */
  async getTransitionTimeline(
    taskId?: string,
    limit: number = 100,
  ): Promise<Record<string, unknown>[]> {
    const params: Record<string, unknown> = { limit };
    let whereClause = "";
    if (taskId) {
      whereClause = "WHERE t.task_id = $task_id";
      params.task_id = taskId;
    }
    return this._backend.runReadQuery(
      `MATCH (t:Task)-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
       ${whereClause}
       RETURN te.event_id AS event_id,
              t.task_id AS task_id,
              te.transition_id AS transition_id,
              te.from_state AS from_state,
              te.to_state AS to_state,
              te.result AS result,
              te.occurred_at AS occurred_at,
              te.calling_role AS calling_role
       ORDER BY te.occurred_at DESC
       LIMIT $limit`,
      params,
    );
  }

  // ================================================================
  // Requires Neo4j GDS plugin (stubs)
  // ================================================================

  /**
   * PageRank on task dependency graph.
   *
   * Requires: DEPENDS_ON relationships + Neo4j GDS plugin.
   */
  async getTaskCriticality(
    _statusFilter?: string,
    _limit: number = 20,
  ): Promise<never> {
    throw new Error(
      "getTaskCriticality() requires the Neo4j GDS plugin. " +
        "Install GDS and create DEPENDS_ON relationships between tasks.",
    );
  }

  /**
   * Betweenness centrality on task dependency graph.
   *
   * Requires: DEPENDS_ON/BLOCKS relationships + Neo4j GDS plugin.
   */
  async getBlockingBottlenecks(
    _statusFilter: string = "ACTIVE",
    _limit: number = 20,
  ): Promise<never> {
    throw new Error(
      "getBlockingBottlenecks() requires the Neo4j GDS plugin. " +
        "Install GDS and create DEPENDS_ON/BLOCKS relationships between tasks.",
    );
  }

  /**
   * Strongly connected components on task dependency graph.
   *
   * Requires: DEPENDS_ON relationships + Neo4j GDS plugin.
   */
  async detectCircularDependencies(): Promise<never> {
    throw new Error(
      "detectCircularDependencies() requires the Neo4j GDS plugin. " +
        "Install GDS and create DEPENDS_ON relationships between tasks.",
    );
  }

  /**
   * Louvain community detection on task + guard failure graph.
   *
   * Requires: Neo4j GDS plugin.
   */
  async getTaskClusters(_minClusterSize: number = 3): Promise<never> {
    throw new Error(
      "getTaskClusters() requires the Neo4j GDS plugin. " +
        "Install GDS to enable community detection.",
    );
  }
}
