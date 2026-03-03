# Contributing to Governor

Setup, tests, style, and how to open a PR.

## Setup

- **Clone** the repo and ensure you have Python 3.9+ available.
- **Install** in dev mode: `pip install -e ".[dev]"` (adds pytest).
- **Optional**: `pip install -e ".[neo4j]"` if you work on the Neo4j backend.

## Tests and validation

- **Run tests**: `pytest` from the repo root. Tests live under `tests/`.
- **Coverage**: `pytest --cov=governor` to check coverage.
- **Lint**: Follow existing code style; keep functions small and readable.

## Style

- **Python**: Follow PEP 8. Prefer clear names over comments.
- **Markdown**: Use clear headings, lists, and code fences. Follow existing tone (concise, operational).
- **Naming**: Use existing conventions (e.g. guard functions, backend interfaces).

## Pull requests

1. **Scope**: One logical change per PR (bug fix, feature, or docs).
2. **Branch**: Create a branch from `main`.
3. **Description**: Summarize what changed and why; link any related issue if applicable.
4. **Tests**: Add or update tests for new behavior.
5. **Review**: Maintainers will review and may request edits before merge.

## Project structure

- `governor/engine/` — Transition engine (state machine, guard evaluation)
- `governor/guards/` — Built-in guard functions
- `governor/scoring/` — Scoring and review logic
- `governor/governance/` — Governance policies and validation
- `governor/backend/` — Storage backends (in-memory, Neo4j)
- `schema/` — JSON schemas for tasks, bundles, policies
- `examples/` — Usage examples and quickstarts
- `docs/` — Documentation
- `tests/` — Test suite

## Questions

- **Architecture**: See `README.md` and files under `docs/`.
- **Examples**: See `examples/` for quickstart patterns.
