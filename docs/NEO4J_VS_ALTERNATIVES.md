# Neo4j vs Alternatives for Governance

A concise comparison of storage backends for AI agent governance workloads.

---

## When to Use Each Backend

### MemoryBackend -- Prototyping and Testing

Use the in-memory backend when:

- You are prototyping guard logic or state machine transitions.
- Running unit tests (fast, no external dependencies).
- Building proof-of-concept integrations with agent frameworks.
- Task volume is small and ephemeral (no persistence needed).

```python
from governor.backend.memory_backend import MemoryBackend

backend = MemoryBackend()
```

Zero configuration. Zero dependencies. All data lost on process exit.

### Neo4jBackend -- Production

Graduate to Neo4j when:

- You need persistent audit trails that survive restarts.
- Multiple agents or services share governance state concurrently.
- You want graph analytics on guard failures, task dependencies, and rework patterns.
- Compliance requires queryable, tamper-evident transition history.
- Task volume exceeds what fits comfortably in memory.

```python
from governor.backend.neo4j_backend import Neo4jBackend

backend = Neo4jBackend(
    uri="neo4j://localhost:7687",
    user="neo4j",
    password="password",
)
```

---

## Query Pattern Comparison

The governance domain is relationship-heavy. The table below shows how common
governance queries map to SQL vs. Neo4j Cypher.

### 1. Full Audit Trail for a Task

**SQL (PostgreSQL):**
```sql
SELECT t.task_name, te.transition_id, te.from_state, te.to_state,
       ge.guard_id, ge.passed, ge.reason
FROM tasks t
JOIN transition_events te ON te.task_id = t.task_id
LEFT JOIN guard_evaluations ge ON ge.event_id = te.event_id
WHERE t.task_id = 'TASK_001'
ORDER BY te.timestamp;
```
3 tables, 2 JOINs, and you still need additional queries for reviews and reports.

**Cypher:**
```cypher
MATCH (t:Task {task_id: 'TASK_001'})-[r]->(n)
RETURN t.task_name, type(r) AS rel, labels(n)[0] AS node_type, properties(n) AS detail
```
One query. All related entities -- reviews, reports, transitions, guard results --
come back in a single traversal.

### 2. Transitive Blocking (All Tasks Blocked by X)

**SQL:**
```sql
WITH RECURSIVE blocked AS (
    SELECT task_id, depends_on_task_id FROM task_dependencies
    WHERE depends_on_task_id = 'TASK_001'
    UNION ALL
    SELECT td.task_id, td.depends_on_task_id
    FROM task_dependencies td
    JOIN blocked b ON td.depends_on_task_id = b.task_id
)
SELECT * FROM blocked;
```
Recursive CTEs are correct but hard to optimize, hard to read, and perform
poorly at depth.

**Cypher:**
```cypher
MATCH (blocked:Task)-[:DEPENDS_ON*]->(root:Task {task_id: 'TASK_001'})
RETURN blocked.task_id, blocked.task_name, blocked.status
```
Variable-length path. The database engine optimizes the traversal.

### 3. Guard Failure Impact Ranking

Which guards cause the most rework across the system?

**SQL:** Requires joining tasks, transition_events, guard_evaluations, then
aggregating with window functions or multiple self-joins. Increasingly complex
as you add dimensions (by role, by task type, over time).

**Cypher + GDS:**
```cypher
CALL gds.pageRank.stream('governance-graph', {relationshipWeightProperty: 'failure_count'})
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).guard_id AS guard, score
ORDER BY score DESC
```
PageRank on the guard-failure graph surfaces the guards with the highest
systemic impact -- not just the most failures, but the ones that cascade.

### 4. Circular Dependency Detection

**SQL:** Cycle detection in a relational database requires iterative queries or
application-level logic. There is no standard SQL construct for it.

**Cypher + GDS:**
```cypher
CALL gds.scc.stream('task-dependency-graph')
YIELD nodeId, componentId
WITH componentId, collect(gds.util.asNode(nodeId).task_id) AS tasks
WHERE size(tasks) > 1
RETURN componentId, tasks
```
Strongly connected components in O(V+E). Any component with more than one node
is a cycle.

### 5. Task Clustering by Failure Pattern

**SQL:** Not practical. Clustering requires graph structure awareness that
relational engines do not have.

**Cypher + GDS:**
```cypher
CALL gds.louvain.stream('failure-graph')
YIELD nodeId, communityId
RETURN communityId, collect(gds.util.asNode(nodeId).task_id) AS cluster
ORDER BY size(cluster) DESC
```
Louvain community detection groups tasks that fail together, revealing
systemic issues (shared dependencies, common misconfiguration patterns).

---

## Performance Characteristics

| Dimension | SQL (PostgreSQL) | Neo4j |
|-----------|-----------------|-------|
| Single task lookup | Fast (indexed) | Fast (indexed) |
| 1-hop relationships | Fast (JOIN) | Fast (traversal) |
| 2-3 hop traversals | Moderate (multi-JOIN) | Fast (index-free adjacency) |
| Deep traversals (5+ hops) | Slow (recursive CTE) | Fast (native graph engine) |
| Graph analytics | Not available | GDS library (PageRank, SCC, Louvain, etc.) |
| Schema flexibility | Rigid (ALTER TABLE) | Flexible (add properties/labels anytime) |
| Concurrent writes | Row-level locks | Optimistic concurrency (Governor CAS pattern) |

---

## Deployment Options

| Option | Best For | Setup |
|--------|----------|-------|
| Docker Compose (local) | Development | `docker compose up -d` |
| Neo4j Community (self-hosted) | Small production | Single server |
| Neo4j AuraDB Free | Evaluation / small teams | Managed cloud, free tier |
| Neo4j AuraDB Professional | Production at scale | Managed cloud, SLA-backed |

---

## Decision Framework

```
Start with MemoryBackend
        |
        v
  Need persistence? ──No──> Stay with MemoryBackend
        |
       Yes
        |
        v
  Need graph analytics? ──No──> Consider SQLite/PostgreSQL
        |                        (but you'll outgrow it)
       Yes
        |
        v
  Use Neo4jBackend
        |
        v
  Self-host or AuraDB?
```

For most Governor users, the progression is:

1. **MemoryBackend** during development and testing.
2. **Neo4jBackend** with Docker Compose for local production testing.
3. **Neo4j AuraDB** for managed production deployment.

---

## Further Reading

- [Graph Data Model](assets/graph_data_model.md) -- node types and relationships
- [GRAPH_ANALYTICS.md](GRAPH_ANALYTICS.md) -- full GDS analytics reference
- [Neo4j AuraDB](https://neo4j.com/cloud/aura/) -- managed cloud deployment
