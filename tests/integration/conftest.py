"""Fixtures for Neo4j integration tests.

These tests require a running Neo4j instance. Set the following environment
variables to connect:

    GOVERNOR_NEO4J_URI      - Bolt URI (e.g. neo4j://localhost:7687)
    GOVERNOR_NEO4J_USER     - Username (e.g. neo4j)
    GOVERNOR_NEO4J_PASSWORD - Password

Tests are skipped automatically when GOVERNOR_NEO4J_URI is not set.
"""

import os

import pytest


# ---------------------------------------------------------------------------
# Skip entire module if Neo4j is not configured
# ---------------------------------------------------------------------------

NEO4J_URI = os.environ.get("GOVERNOR_NEO4J_URI")
NEO4J_USER = os.environ.get("GOVERNOR_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("GOVERNOR_NEO4J_PASSWORD", "")

requires_neo4j = pytest.mark.skipif(
    NEO4J_URI is None,
    reason="GOVERNOR_NEO4J_URI not set — skipping Neo4j integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def neo4j_backend():
    """Create a Neo4jBackend, run schema setup, yield it, then clean up.

    After the test, all nodes and relationships are deleted so tests are
    fully isolated.
    """
    if NEO4J_URI is None:
        pytest.skip("GOVERNOR_NEO4J_URI not set")

    # Import here so the test file can be collected even without neo4j driver
    from governor.backend.neo4j_backend import Neo4jBackend

    backend = Neo4jBackend(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
    )

    # Ensure schema (indexes, constraints) exists
    backend.ensure_schema()

    yield backend

    # --------------- cleanup ---------------
    # Remove all nodes and relationships created during the test.
    with backend._driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    backend.close()
