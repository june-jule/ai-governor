# Graph Analytics for Governor

Governor's Neo4j backend stores tasks, transitions, guard evaluations, and dependencies as a graph. The `governor.analytics` module provides analytics that use this structure.

## Why Graph Algorithms?

| Query | Postgres | Neo4j + GDS |
|-------|----------|-------------|
| Guard failure hotspots | Simple GROUP BY | Same (no advantage) |
| Guard co-occurrence | Self-join + GROUP BY | Same (no advantage) |
| **Task criticality (PageRank)** | Not available | `gds.pageRank.stream()` |
| **Blocking bottlenecks** | Recursive CTE (slow, complex) | `gds.betweenness.stream()` |
| **Circular dependency detection** | Very hard | `gds.scc.stream()` |
| **Task clustering by failure pattern** | Not practical | `gds.louvain.stream()` |

The first two are basic aggregation — any database handles them. The last four require actual graph structure.

## Quick Start

```python
from governor.backend.neo4j_backend import Neo4jBackend
from governor.analytics import GovernorAnalytics

backend = Neo4jBackend.from_env()
analytics = GovernorAnalytics(backend)
```

## Available Methods

### Ready Now (No GDS Required)

These methods work with the existing schema immediately.

#### `get_guard_bottlenecks(limit=10)`
Identify which guards block the most tasks.

```python
bottlenecks = analytics.get_guard_bottlenecks(limit=5)
# [{"guard_id": "EG-01", "evaluations": 50, "failures": 15, "failure_rate": 30.0}, ...]
```

#### `get_rework_hotspots(limit=10)`
Find tasks with the most rework cycles.

```python
hotspots = analytics.get_rework_hotspots(limit=5)
# [{"task_id": "T1", "task_type": "IMPLEMENTATION", "rework_cycles": 3}, ...]
```

#### `get_guard_cooccurrence(min_cooccurrence=2, limit=15)`
Find guards that frequently fail together (indicates systemic issues).

```python
pairs = analytics.get_guard_cooccurrence(min_cooccurrence=3)
# [{"guard_a": "EG-01", "guard_b": "EG-02", "co_failures": 10}, ...]
```

#### `get_role_efficiency(since=None)`
Measure pass/fail rates per role.

```python
roles = analytics.get_role_efficiency(since="2026-01-01")
# [{"role": "EXECUTOR", "total_transitions": 20, "passes": 15, "fails": 5, "pass_rate": 75.0}]
```

#### `get_transition_timeline(task_id=None, limit=100)`
Get transition event timeline, optionally filtered by task.

### Task Dependencies

These require `DEPENDS_ON` / `BLOCKS` relationships between tasks.

#### `add_task_dependency(from_task_id, to_task_id, rel_type="DEPENDS_ON")`
Create a task-to-task dependency.

```python
analytics.add_task_dependency("TASK_A", "TASK_B")
# TASK_A now depends on TASK_B
```

#### `get_task_dependencies(task_id, direction="both")`
Query what a task depends on and what depends on it.

#### `remove_task_dependency(from_task_id, to_task_id, rel_type="DEPENDS_ON")`
Remove a dependency relationship.

### GDS-Dependent Methods

These require the [Neo4j Graph Data Science](https://neo4j.com/docs/graph-data-science/) plugin.

#### `get_task_criticality(status_filter=None, limit=20)`
**PageRank** on task dependency graph. Tasks that many others depend on score higher.

```python
critical = analytics.get_task_criticality(status_filter="ACTIVE")
# [{"task_id": "T1", "criticality_score": 0.9234, "status": "ACTIVE"}, ...]
```

#### `get_blocking_bottlenecks(status_filter="ACTIVE", limit=20)`
**Betweenness centrality** — finds tasks that sit on the most dependency paths.

#### `detect_circular_dependencies()`
**Strongly connected components** — finds dependency cycles (deadlocks).

```python
cycles = analytics.detect_circular_dependencies()
# [{"component_id": 0, "size": 3, "task_ids": ["T1", "T2", "T3"]}]
```

#### `get_task_clusters(min_cluster_size=3)`
**Louvain community detection** — groups tasks by shared guard failure patterns.

## Schema Requirements

The analytics module adds two relationship indexes to the schema:

```cypher
CREATE INDEX task_depends_on_created_idx IF NOT EXISTS
FOR ()-[d:DEPENDS_ON]->() ON (d.created_date);

CREATE INDEX task_blocks_created_idx IF NOT EXISTS
FOR ()-[b:BLOCKS]->() ON (b.created_date);
```

These are included in `governor/schema/neo4j_schema.cypher`.

## GDS Plugin Installation

To use PageRank, betweenness centrality, SCC, and Louvain:

1. Install GDS plugin for your Neo4j version
2. Restart Neo4j
3. Verify: `CALL gds.version()` should return the version

Methods gracefully degrade when GDS is not installed — they return an error dict instead of raising.
