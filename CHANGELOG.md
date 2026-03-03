# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-03-03

### Added

- **BLOCKED and FAILED states** (state machine v2.0.0, transitions T05-T09): tasks can now be parked when blocked and permanently failed from ACTIVE, BLOCKED, or REWORK states.
- **Graph analytics module** with Neo4j GDS integration (PageRank, betweenness centrality, strongly connected components, Louvain community detection).
- **TypeScript Neo4j backend** (`governor-ts/src/backend/neo4j.ts`) for Node.js deployments.
- **CI integration tests** with real Neo4j via GitHub Actions service containers (`tests/integration/`).
- **Docker Compose** now includes GDS plugin by default (`NEO4J_PLUGINS: '["graph-data-science"]'`).
- **Graph data model diagram** (`docs/assets/graph_data_model.md`) — Mermaid-based visual reference for all node types and relationships.
- **Performance comparison document** (`docs/NEO4J_VS_ALTERNATIVES.md`) — Neo4j vs relational databases for governance query patterns.

### Fixed

- Failed transition events now persist to audit trail with retry logic.
- Path traversal vulnerability in EG-03 deliverables check (switched to `os.path.commonpath`).
- GDS graph name collisions in concurrent analytics (UUID-suffixed names + try/finally cleanup).
- Guard timeout thread leak -- engine now provides `shutdown()` and context manager.
- WriteConflict exceptions now retried in Neo4j backend.
- Expanded secret detection (EG-05): JWT, Slack tokens, DB connection strings, AWS session tokens, GitHub OAuth tokens, Stripe keys.
- `ensure_schema()` now reports partial failures instead of crashing.
- `GuardResult.passed` validates boolean type at construction.
- Event callbacks track failure -- events not marked "fired" if callback raises.
- Rate limiter LRU eviction now happens before insert (capacity invariant).
- Relationship truncation response includes total count and limit.
- Regex DoS protection in deliverables parsing (per-line length cap).

### Changed

- GDS methods split into project/run/drop for proper cleanup on failure.

## [0.2.0] - 2026-02-27

### Added

- **Async support**: `AsyncTransitionEngine` and `AsyncGovernorBackend` for async agent frameworks (LangChain, CrewAI, OpenAI Agents SDK).
- **MCP tool wrapper**: `governor.mcp.tools` exposes Governor as 6 MCP tools (transition, available transitions, audit trail, guard hotspots, rework lineage, policy coverage) for Claude, Cursor, and MCP-compatible agents.
- **State machine validation**: `validate_state_machine()` catches orphan states, missing terminals, and duplicate IDs at engine init — not at runtime.
- **PEP 561 compliance**: `py.typed` marker for type checker support.
- **Framework integration examples**: LangChain callback, CrewAI pipeline, and OpenAI Agents SDK self-correction patterns (`examples/`).
- **Audit trail example**: `examples/audit_trail.py` — 5-task lifecycle with guard failures, rework, and Neo4j Cypher equivalents.
- **Neo4j composite indexes**: `(status, role)`, `(status, priority)`, `(status, task_type)` for production query patterns.
- **Scoring rubric tests**: 15 tests covering rubric loading, scoring math, evidence gate, and rating thresholds.
- **Guard unit tests**: Comprehensive tests for each EG guard (pass/fail/skip/edge cases).
- **Error boundary tests**: Malformed state machine, missing fields, guard exceptions, strict mode validation.
- **Neo4j backend mock tests**: Cypher building and error handling with `unittest.mock`.
- **Async engine tests**: Full lifecycle tests with `AsyncMemoryBackend` wrapper.
- **Documentation**: `docs/WHY.md` — real failure scenarios and how guards prevent them.

### Changed

- **BREAKING: `strict=True` is now the default.** Previously, unregistered guards silently passed (`strict=False`). Now the engine raises on unregistered guard IDs. Pass `strict=False` explicitly to restore the old behavior.
- **Package renamed to `ai-governor`** on PyPI. Import name remains `governor`.
- **Version bumped to 0.2.0.**
- **CI matrix**: Tests now run on Python 3.9, 3.11, 3.12, and 3.13.
- **CI coverage**: `pytest-cov` with XML and terminal coverage reporting.
- **Test suite expanded**: 39 tests → 87 tests.
- **README overhauled**: Comparison table, async snippet, framework integrations, MCP section, roadmap.

### Migration Guide

If you relied on `strict=False` (the v0.1.0 default):

```python
# v0.1.0 — unregistered guards silently pass
engine = TransitionEngine(backend=backend)

# v0.2.0 — either register all guards, or explicitly opt out
engine = TransitionEngine(backend=backend, strict=False)
```

## [0.1.0] - 2026-02-20

### Added

- **Transition engine**: State machine with role-based authorization and pluggable guard evaluation.
- **Guard system**: Built-in guards (self-review, report exists, deliverables check) plus custom guard support.
- **Scoring**: Configurable scoring rubric with evidence-based review protocol.
- **Backends**: In-memory backend for testing; Neo4j backend for production graph storage.
- **JSON schemas**: Task and state machine schemas under `schema/`.
- **Examples**: Quickstart examples for common integration patterns.
- **Documentation**: Architecture overview, guard catalog, and integration guides.
- **Test suite**: pytest-based tests for engine, guards, and backend.

---

*For development history, see git log.*
