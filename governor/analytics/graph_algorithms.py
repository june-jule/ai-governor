"""Graph algorithm integration for Governor Neo4j backends.

Provides analytics methods that leverage Neo4j's graph structure to answer
questions that would be impractical with a relational database:

- **Ready now** (no GDS needed): guard bottlenecks, rework hotspots,
  guard co-occurrence, role efficiency.
- **Requires GDS**: PageRank for task criticality, betweenness centrality
  for blocking bottlenecks, SCC for circular dependency detection,
  Louvain for task clustering.

Usage::

    from governor.backend.neo4j_backend import Neo4jBackend
    from governor.analytics import GovernorAnalytics

    backend = Neo4jBackend.from_env()
    analytics = GovernorAnalytics(backend)

    # No GDS required
    bottlenecks = analytics.get_guard_bottlenecks(limit=5)
    hotspots = analytics.get_rework_hotspots(limit=5)

    # Requires GDS plugin + task dependency relationships
    criticality = analytics.get_task_criticality(status_filter="ACTIVE")
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from governor.backend.neo4j_backend import Neo4jBackend

logger = logging.getLogger("governor.analytics")

# Allowlist for status filter values to prevent injection via GDS
# cypher projection strings (which cannot use $param placeholders).
_VALID_STATUS_RE = re.compile(r"^[A-Z_]{1,50}$")


def _gds_graph_name(prefix: str) -> str:
    """Generate a unique GDS graph name to avoid concurrent collisions.

    Uses the full UUID4 hex (128 bits) to make collisions effectively
    impossible, even under high concurrency.
    """
    return f"{prefix}_{uuid.uuid4().hex}"


def _validate_status_filter(status_filter: str) -> None:
    """Validate that a status_filter is a safe, alphanumeric identifier.

    GDS ``gds.graph.project()`` Cypher-projection node-query strings are
    evaluated as literal Cypher and do **not** support ``$param``
    placeholders. We therefore must inline the value — but only after
    strict validation to prevent Cypher injection.

    Raises:
        ValueError: If the value contains characters outside ``[A-Z_]``.
    """
    if not _VALID_STATUS_RE.match(status_filter):
        raise ValueError(
            f"Invalid status_filter value: {status_filter!r}. "
            "Must match [A-Z_]{{1,50}} (e.g. 'ACTIVE', 'BLOCKED')."
        )


class GovernorAnalytics:
    """Graph algorithm integration for Governor Neo4j backends.

    All methods return plain Python dicts/lists — no special dependencies.
    Methods that require Neo4j GDS are clearly documented.
    """

    def __init__(self, backend: "Neo4jBackend") -> None:
        self._backend = backend

    def _drop_gds_graph(self, graph_name: str) -> None:
        """Best-effort cleanup of a projected GDS graph.

        Logs a warning with remediation steps on failure. Repeated
        failures may leave orphaned in-memory graphs; use
        ``CALL gds.graph.list()`` to audit and drop them manually.
        """
        try:
            self._backend._run_query(
                "CALL gds.graph.drop($graph_name, false) YIELD graphName RETURN graphName",
                {"graph_name": graph_name},
                mode="write",
            )
        except Exception as cleanup_err:
            logger.warning(
                "GDS graph cleanup FAILED for '%s' — projected graph may "
                "remain in memory until the Neo4j process restarts. "
                "Run `CALL gds.graph.list()` to find orphans, then "
                "`CALL gds.graph.drop('%s', false)` to reclaim memory. "
                "Error: %s",
                graph_name,
                graph_name,
                cleanup_err,
            )

    # ==================================================================
    # Ready NOW — work with existing schema, no GDS needed
    # ==================================================================

    def get_guard_bottlenecks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Identify guards that block the most tasks.

        Uses aggregation on GuardEvaluation nodes to find guards with
        the highest failure-to-evaluation ratio.

        Returns:
            List of dicts with guard_id, evaluations, failures, failure_rate.
        """
        return self._backend._run_query(
            """
            MATCH (ge:GuardEvaluation)
            WITH ge.guard_id AS guard_id,
                 count(ge) AS evaluations,
                 sum(CASE WHEN ge.passed THEN 0 ELSE 1 END) AS failures
            RETURN guard_id, evaluations, failures,
                   round(100.0 * failures / evaluations, 1) AS failure_rate
            ORDER BY failures DESC
            LIMIT $limit
            """,
            {"limit": limit},
            mode="read",
        )

    def get_rework_hotspots(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Find tasks with the most rework cycles.

        Aggregates TransitionEvent nodes where to_state='REWORK' to
        identify tasks that repeatedly fail guard evaluation.

        Returns:
            List of dicts with task_id, task_type, role, status, rework_cycles.
        """
        return self._backend._run_query(
            """
            MATCH (t:Task)-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
            WHERE te.to_state = 'REWORK'
            WITH t, count(te) AS rework_cycles
            RETURN t.task_id AS task_id,
                   t.task_type AS task_type,
                   t.role AS role,
                   t.status AS status,
                   rework_cycles
            ORDER BY rework_cycles DESC
            LIMIT $limit
            """,
            {"limit": limit},
            mode="read",
        )

    def get_guard_cooccurrence(
        self, min_cooccurrence: int = 2, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Find guards that frequently fail together.

        When two guards consistently co-fail on the same transition event,
        it indicates a systemic issue (e.g., tasks missing both self-review
        AND report suggest incomplete submission patterns).

        Returns:
            List of dicts with guard_a, guard_b, co_failures.
        """
        return self._backend._run_query(
            """
            MATCH (te:TransitionEvent)-[:HAS_GUARD_EVALUATION]->(ge1:GuardEvaluation)
            WHERE NOT ge1.passed
            WITH te, ge1
            MATCH (te)-[:HAS_GUARD_EVALUATION]->(ge2:GuardEvaluation)
            WHERE NOT ge2.passed AND ge1.guard_id < ge2.guard_id
            WITH ge1.guard_id AS guard_a, ge2.guard_id AS guard_b,
                 count(*) AS co_failures
            WHERE co_failures >= $min_cooccurrence
            RETURN guard_a, guard_b, co_failures
            ORDER BY co_failures DESC
            LIMIT $limit
            """,
            {"min_cooccurrence": min_cooccurrence, "limit": limit},
            mode="read",
        )

    def get_role_efficiency(
        self, since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Measure pass/fail rates per role.

        Which roles have the highest first-attempt pass rates?
        Which roles trigger the most rework?

        Args:
            since: Optional ISO date string to filter by occurred_at.

        Returns:
            List of dicts with role, total_transitions, passes, fails, pass_rate.
        """
        params: Dict[str, Any] = {}
        where_clause = ""
        if since:
            where_clause = "WHERE te.occurred_at >= $since"
            params["since"] = since
        return self._backend._run_query(
            f"""
            MATCH (te:TransitionEvent)
            {where_clause}
            RETURN te.calling_role AS role,
                   count(te) AS total_transitions,
                   sum(CASE WHEN te.result = 'PASS' THEN 1 ELSE 0 END) AS passes,
                   sum(CASE WHEN te.result = 'FAIL' THEN 1 ELSE 0 END) AS fails,
                   round(100.0 * sum(CASE WHEN te.result = 'PASS' THEN 1 ELSE 0 END) /
                         count(te), 1) AS pass_rate
            ORDER BY total_transitions DESC
            """,
            params,
            mode="read",
        )

    def get_transition_timeline(
        self,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get transition event timeline, optionally filtered by task.

        Returns:
            List of dicts with event_id, task_id, transition_id, from_state,
            to_state, result, occurred_at, calling_role.
        """
        params: Dict[str, Any] = {"limit": limit}
        where_clause = ""
        if task_id:
            where_clause = "WHERE t.task_id = $task_id"
            params["task_id"] = task_id
        return self._backend._run_query(
            f"""
            MATCH (t:Task)-[:HAS_TRANSITION_EVENT]->(te:TransitionEvent)
            {where_clause}
            RETURN te.event_id AS event_id,
                   t.task_id AS task_id,
                   te.transition_id AS transition_id,
                   te.from_state AS from_state,
                   te.to_state AS to_state,
                   te.result AS result,
                   te.occurred_at AS occurred_at,
                   te.calling_role AS calling_role
            ORDER BY te.occurred_at DESC
            LIMIT $limit
            """,
            params,
            mode="read",
        )

    # ==================================================================
    # Requires task-to-task relationships (DEPENDS_ON / BLOCKS)
    # ==================================================================

    def get_task_dependencies(
        self,
        task_id: str,
        direction: str = "both",
    ) -> Dict[str, Any]:
        """Get tasks this task depends on or is blocked by.

        Requires DEPENDS_ON relationships between Task nodes.

        Args:
            task_id: Task to query dependencies for.
            direction: "outgoing" (tasks I depend on), "incoming" (tasks
                       that depend on me), or "both".

        Returns:
            Dict with task_id, depends_on (list), depended_by (list).
        """
        result: Dict[str, Any] = {
            "task_id": task_id,
            "depends_on": [],
            "depended_by": [],
        }

        if direction in ("outgoing", "both"):
            result["depends_on"] = self._backend._run_query(
                """
                MATCH (t:Task {task_id: $task_id})-[:DEPENDS_ON]->(dep:Task)
                RETURN dep.task_id AS task_id,
                       dep.task_name AS task_name,
                       dep.status AS status,
                       dep.priority AS priority
                """,
                {"task_id": task_id},
                mode="read",
            )

        if direction in ("incoming", "both"):
            result["depended_by"] = self._backend._run_query(
                """
                MATCH (dep:Task)-[:DEPENDS_ON]->(t:Task {task_id: $task_id})
                RETURN dep.task_id AS task_id,
                       dep.task_name AS task_name,
                       dep.status AS status,
                       dep.priority AS priority
                """,
                {"task_id": task_id},
                mode="read",
            )

        return result

    def add_task_dependency(
        self,
        from_task_id: str,
        to_task_id: str,
        rel_type: str = "DEPENDS_ON",
    ) -> Dict[str, Any]:
        """Create a task-to-task dependency relationship.

        Args:
            from_task_id: Task that depends on another.
            to_task_id: Task being depended on.
            rel_type: Relationship type (DEPENDS_ON or BLOCKS).

        Returns:
            Dict with success status.
        """
        if rel_type not in ("DEPENDS_ON", "BLOCKS"):
            return {"success": False, "error": f"Invalid rel_type: {rel_type}"}

        # Use MERGE for idempotency
        if rel_type == "DEPENDS_ON":
            query = """
                MATCH (a:Task {task_id: $from_id}), (b:Task {task_id: $to_id})
                MERGE (a)-[r:DEPENDS_ON]->(b)
                ON CREATE SET r.created_date = date()
                RETURN type(r) AS rel_type
            """
        else:
            query = """
                MATCH (a:Task {task_id: $from_id}), (b:Task {task_id: $to_id})
                MERGE (a)-[r:BLOCKS]->(b)
                ON CREATE SET r.created_date = date()
                RETURN type(r) AS rel_type
            """
        results = self._backend._run_query(
            query,
            {"from_id": from_task_id, "to_id": to_task_id},
            mode="write",
        )
        if results:
            return {"success": True, "from_task_id": from_task_id, "to_task_id": to_task_id}
        return {"success": False, "error": "One or both tasks not found"}

    def remove_task_dependency(
        self,
        from_task_id: str,
        to_task_id: str,
        rel_type: str = "DEPENDS_ON",
    ) -> Dict[str, Any]:
        """Remove a task-to-task dependency relationship.

        Args:
            from_task_id: Source task.
            to_task_id: Target task.
            rel_type: Relationship type (DEPENDS_ON or BLOCKS).

        Returns:
            Dict with success status.
        """
        if rel_type not in ("DEPENDS_ON", "BLOCKS"):
            return {"success": False, "error": f"Invalid rel_type: {rel_type}"}

        if rel_type == "DEPENDS_ON":
            query = """
                MATCH (a:Task {task_id: $from_id})-[r:DEPENDS_ON]->(b:Task {task_id: $to_id})
                DELETE r
                RETURN count(r) AS deleted
            """
        else:
            query = """
                MATCH (a:Task {task_id: $from_id})-[r:BLOCKS]->(b:Task {task_id: $to_id})
                DELETE r
                RETURN count(r) AS deleted
            """
        results = self._backend._run_query(
            query,
            {"from_id": from_task_id, "to_id": to_task_id},
            mode="write",
        )
        deleted = results[0].get("deleted", 0) if results else 0
        return {"success": True, "deleted": deleted}

    # ==================================================================
    # Requires Neo4j GDS plugin
    # ==================================================================

    def get_task_criticality(
        self,
        status_filter: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """PageRank on task dependency graph.

        Tasks that many other tasks depend on score higher. Use this to
        prioritize which ACTIVE tasks to unblock first.

        Requires: DEPENDS_ON relationships between tasks.
        Requires: Neo4j GDS plugin installed.

        Returns:
            List of dicts with task_id, task_name, status, priority, criticality_score.
        """
        params: Dict[str, Any] = {"limit": limit}
        if status_filter:
            _validate_status_filter(status_filter)
            node_query = f"MATCH (t:Task) WHERE t.status = \\'{status_filter}\\' RETURN id(t) AS id"
        else:
            node_query = "MATCH (t:Task) RETURN id(t) AS id"

        graph_name = _gds_graph_name("gov_task_deps_pr")
        rel_query = "MATCH (t1:Task)-[:DEPENDS_ON]->(t2:Task) RETURN id(t1) AS source, id(t2) AS target"
        try:
            self._backend._run_query(
                f"""
                CALL gds.graph.project(
                  $graph_name,
                  '{node_query}',
                  '{rel_query}'
                )
                YIELD graphName
                RETURN graphName
                """,
                {"graph_name": graph_name},
                mode="write",
            )
            return self._backend._run_query(
                """
                CALL gds.pageRank.stream($graph_name, {
                  maxIterations: 20,
                  dampingFactor: 0.85
                })
                YIELD nodeId, score
                WITH nodeId, score
                MATCH (t:Task) WHERE id(t) = nodeId
                RETURN t.task_id AS task_id,
                       t.task_name AS task_name,
                       t.status AS status,
                       t.priority AS priority,
                       round(score, 4) AS criticality_score
                ORDER BY criticality_score DESC
                LIMIT $limit
                """,
                {**params, "graph_name": graph_name},
                mode="read",
            )
        except Exception as e:
            if "gds" in str(e).lower() or "procedure" in str(e).lower():
                return [{"error": "Neo4j GDS plugin not installed", "detail": str(e)}]
            raise
        finally:
            self._drop_gds_graph(graph_name)

    def get_blocking_bottlenecks(
        self,
        status_filter: str = "ACTIVE",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Betweenness centrality on task dependency graph.

        Identifies tasks that sit on the most dependency paths. These
        are the tasks whose completion would unblock the most downstream work.

        Requires: DEPENDS_ON / BLOCKS relationships between tasks.
        Requires: Neo4j GDS plugin installed.

        Returns:
            List of dicts with task_id, task_name, status, bottleneck_score.
        """
        params: Dict[str, Any] = {"limit": limit}
        if status_filter:
            _validate_status_filter(status_filter)
            node_query = f"MATCH (t:Task) WHERE t.status = \\'{status_filter}\\' RETURN id(t) AS id"
        else:
            node_query = "MATCH (t:Task) RETURN id(t) AS id"

        graph_name = _gds_graph_name("gov_task_deps_bc")
        rel_query = "MATCH (t1:Task)-[:DEPENDS_ON|BLOCKS]->(t2:Task) RETURN id(t1) AS source, id(t2) AS target"
        try:
            self._backend._run_query(
                f"""
                CALL gds.graph.project(
                  $graph_name,
                  '{node_query}',
                  '{rel_query}'
                )
                YIELD graphName
                RETURN graphName
                """,
                {"graph_name": graph_name},
                mode="write",
            )
            return self._backend._run_query(
                """
                CALL gds.betweenness.stream($graph_name)
                YIELD nodeId, score
                WITH nodeId, score
                MATCH (t:Task) WHERE id(t) = nodeId
                RETURN t.task_id AS task_id,
                       t.task_name AS task_name,
                       t.status AS status,
                       round(score, 4) AS bottleneck_score
                ORDER BY bottleneck_score DESC
                LIMIT $limit
                """,
                {**params, "graph_name": graph_name},
                mode="read",
            )
        except Exception as e:
            if "gds" in str(e).lower() or "procedure" in str(e).lower():
                return [{"error": "Neo4j GDS plugin not installed", "detail": str(e)}]
            raise
        finally:
            self._drop_gds_graph(graph_name)

    def detect_circular_dependencies(self) -> List[Dict[str, Any]]:
        """Strongly connected components on task dependency graph.

        Finds cycles where Task A depends on B, B depends on C, C depends
        on A. These are deadlocks that need manual intervention.

        Requires: DEPENDS_ON relationships between tasks.
        Requires: Neo4j GDS plugin installed.

        Returns:
            List of dicts with component_id, size, task_ids.
        """
        graph_name = _gds_graph_name("gov_task_deps_scc")
        node_query = "MATCH (t:Task) RETURN id(t) AS id"
        rel_query = "MATCH (t1:Task)-[:DEPENDS_ON]->(t2:Task) RETURN id(t1) AS source, id(t2) AS target"
        try:
            self._backend._run_query(
                f"""
                CALL gds.graph.project(
                  $graph_name,
                  '{node_query}',
                  '{rel_query}'
                )
                YIELD graphName
                RETURN graphName
                """,
                {"graph_name": graph_name},
                mode="write",
            )
            return self._backend._run_query(
                """
                CALL gds.scc.stream($graph_name)
                YIELD nodeId, componentId
                WITH componentId, collect(nodeId) AS nodeIds
                WHERE size(nodeIds) > 1
                UNWIND nodeIds AS nid
                MATCH (t:Task) WHERE id(t) = nid
                WITH componentId, collect(t.task_id) AS task_ids
                RETURN componentId AS component_id,
                       size(task_ids) AS size,
                       task_ids
                ORDER BY size DESC
                """,
                {"graph_name": graph_name},
                mode="read",
            )
        except Exception as e:
            if "gds" in str(e).lower() or "procedure" in str(e).lower():
                return [{"error": "Neo4j GDS plugin not installed", "detail": str(e)}]
            raise
        finally:
            self._drop_gds_graph(graph_name)

    def get_task_clusters(
        self, min_cluster_size: int = 3
    ) -> List[Dict[str, Any]]:
        """Louvain community detection on task + guard failure graph.

        Groups tasks that share similar guard failure patterns. Useful for
        identifying systemic issues across task types.

        Requires: Neo4j GDS plugin installed.

        Returns:
            List of dicts with community_id, size, task_ids.
        """
        graph_name = _gds_graph_name("gov_task_clusters")
        node_query = "MATCH (t:Task) RETURN id(t) AS id"
        rel_query = (
            "MATCH (t1:Task)-[:HAS_TRANSITION_EVENT]->(:TransitionEvent)"
            "-[:HAS_GUARD_EVALUATION]->(ge:GuardEvaluation) "
            "WHERE NOT ge.passed "
            "WITH t1, ge.guard_id AS gid "
            "MATCH (t2:Task)-[:HAS_TRANSITION_EVENT]->(:TransitionEvent)"
            "-[:HAS_GUARD_EVALUATION]->(ge2:GuardEvaluation) "
            "WHERE NOT ge2.passed AND ge2.guard_id = gid AND t1 <> t2 "
            "RETURN id(t1) AS source, id(t2) AS target"
        )
        try:
            self._backend._run_query(
                f"""
                CALL gds.graph.project(
                  $graph_name,
                  '{node_query}',
                  '{rel_query}'
                )
                YIELD graphName
                RETURN graphName
                """,
                {"graph_name": graph_name},
                mode="write",
            )
            return self._backend._run_query(
                """
                CALL gds.louvain.stream($graph_name)
                YIELD nodeId, communityId
                WITH communityId, collect(nodeId) AS nodeIds
                WHERE size(nodeIds) >= $min_cluster_size
                UNWIND nodeIds AS nid
                MATCH (t:Task) WHERE id(t) = nid
                WITH communityId, collect(t.task_id) AS task_ids
                RETURN communityId AS community_id,
                       size(task_ids) AS size,
                       task_ids
                ORDER BY size DESC
                """,
                {"min_cluster_size": min_cluster_size, "graph_name": graph_name},
                mode="read",
            )
        except Exception as e:
            if "gds" in str(e).lower() or "procedure" in str(e).lower():
                return [{"error": "Neo4j GDS plugin not installed", "detail": str(e)}]
            raise
        finally:
            self._drop_gds_graph(graph_name)
