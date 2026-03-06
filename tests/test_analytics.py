"""Tests for governor.analytics.graph_algorithms module.

Tests the GovernorAnalytics class methods that work without Neo4j GDS.
Uses the MemoryBackend with monkey-patched _run_query for Cypher simulation.
"""

from governor.analytics.graph_algorithms import GovernorAnalytics


class FakeBackend:
    """Minimal mock that captures _run_query calls."""

    def __init__(self):
        self._queries = []
        self._results = []

    def _run_query(self, query, params=None, mode="read"):
        self._queries.append({"query": query, "params": params, "mode": mode})
        if self._results:
            return self._results.pop(0)
        return []


class TestGovernorAnalyticsReadyNow:
    """Tests for methods that work with existing schema (no GDS)."""

    def test_get_guard_bottlenecks_calls_correct_query(self):
        backend = FakeBackend()
        backend._results = [
            [
                {"guard_id": "EG-01", "evaluations": 50, "failures": 15, "failure_rate": 30.0},
                {"guard_id": "EG-05", "evaluations": 50, "failures": 5, "failure_rate": 10.0},
            ]
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_guard_bottlenecks(limit=5)

        assert len(result) == 2
        assert result[0]["guard_id"] == "EG-01"
        assert result[0]["failures"] == 15
        assert backend._queries[0]["params"] == {"limit": 5}
        assert backend._queries[0]["mode"] == "read"

    def test_get_rework_hotspots_calls_correct_query(self):
        backend = FakeBackend()
        backend._results = [
            [
                {"task_id": "T1", "task_type": "IMPLEMENTATION", "role": "DEV", "status": "COMPLETED", "rework_cycles": 3},
            ]
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_rework_hotspots(limit=5)

        assert len(result) == 1
        assert result[0]["rework_cycles"] == 3
        assert "REWORK" in backend._queries[0]["query"]

    def test_get_guard_cooccurrence_passes_params(self):
        backend = FakeBackend()
        backend._results = [
            [
                {"guard_a": "EG-01", "guard_b": "EG-02", "co_failures": 10},
            ]
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_guard_cooccurrence(min_cooccurrence=3, limit=10)

        assert len(result) == 1
        assert result[0]["co_failures"] == 10
        assert backend._queries[0]["params"]["min_cooccurrence"] == 3
        assert backend._queries[0]["params"]["limit"] == 10

    def test_get_role_efficiency_with_since(self):
        backend = FakeBackend()
        backend._results = [
            [
                {"role": "EXECUTOR", "total_transitions": 20, "passes": 15, "fails": 5, "pass_rate": 75.0},
            ]
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_role_efficiency(since="2026-01-01")

        assert len(result) == 1
        assert result[0]["pass_rate"] == 75.0
        assert backend._queries[0]["params"]["since"] == "2026-01-01"
        assert "WHERE" in backend._queries[0]["query"]

    def test_get_role_efficiency_without_since(self):
        backend = FakeBackend()
        backend._results = [[]]
        analytics = GovernorAnalytics(backend)
        analytics.get_role_efficiency()

        assert backend._queries[0]["params"] == {}

    def test_get_transition_timeline_with_task_filter(self):
        backend = FakeBackend()
        backend._results = [[]]
        analytics = GovernorAnalytics(backend)
        analytics.get_transition_timeline(task_id="TASK_001", limit=10)

        assert backend._queries[0]["params"]["task_id"] == "TASK_001"
        assert "WHERE" in backend._queries[0]["query"]


class TestGovernorAnalyticsDependencies:
    """Tests for task dependency methods."""

    def test_get_task_dependencies_both(self):
        backend = FakeBackend()
        backend._results = [
            [{"task_id": "T2", "task_name": "Dep", "status": "ACTIVE", "priority": "HIGH"}],
            [{"task_id": "T3", "task_name": "Rev", "status": "COMPLETED", "priority": "LOW"}],
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_task_dependencies("T1", direction="both")

        assert result["task_id"] == "T1"
        assert len(result["depends_on"]) == 1
        assert len(result["depended_by"]) == 1
        assert len(backend._queries) == 2

    def test_get_task_dependencies_outgoing_only(self):
        backend = FakeBackend()
        backend._results = [
            [{"task_id": "T2", "task_name": "Dep", "status": "ACTIVE", "priority": "HIGH"}],
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_task_dependencies("T1", direction="outgoing")

        assert len(result["depends_on"]) == 1
        assert result["depended_by"] == []
        assert len(backend._queries) == 1

    def test_add_task_dependency_depends_on(self):
        backend = FakeBackend()
        backend._results = [
            [{"rel_type": "DEPENDS_ON"}],
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.add_task_dependency("T1", "T2", rel_type="DEPENDS_ON")

        assert result["success"] is True
        assert "MERGE" in backend._queries[0]["query"]
        assert backend._queries[0]["mode"] == "write"

    def test_add_task_dependency_invalid_type(self):
        backend = FakeBackend()
        analytics = GovernorAnalytics(backend)
        result = analytics.add_task_dependency("T1", "T2", rel_type="INVALID")

        assert result["success"] is False
        assert "Invalid" in result["error"]

    def test_remove_task_dependency(self):
        backend = FakeBackend()
        backend._results = [
            [{"deleted": 1}],
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.remove_task_dependency("T1", "T2")

        assert result["success"] is True
        assert result["deleted"] == 1
        assert "DELETE" in backend._queries[0]["query"]


class TestGovernorAnalyticsGDS:
    """Tests for GDS-dependent methods (mock error handling)."""

    def test_get_task_criticality_gds_not_installed(self):
        backend = FakeBackend()
        # Simulate GDS not installed error
        def raise_gds_error(query, params=None, mode="read"):
            raise Exception("There is no procedure with the name `gds.graph.project.cypher`")

        backend._run_query = raise_gds_error
        analytics = GovernorAnalytics(backend)
        result = analytics.get_task_criticality()

        assert len(result) == 1
        assert result[0]["error"] == "Neo4j GDS plugin not installed"

    def test_get_blocking_bottlenecks_gds_not_installed(self):
        backend = FakeBackend()
        def raise_gds_error(query, params=None, mode="read"):
            raise Exception("Unknown procedure gds.betweenness.stream")

        backend._run_query = raise_gds_error
        analytics = GovernorAnalytics(backend)
        result = analytics.get_blocking_bottlenecks()

        assert result[0]["error"] == "Neo4j GDS plugin not installed"

    def test_detect_circular_dependencies_gds_not_installed(self):
        backend = FakeBackend()
        def raise_gds_error(query, params=None, mode="read"):
            raise Exception("There is no procedure with the name `gds.scc.stream`")

        backend._run_query = raise_gds_error
        analytics = GovernorAnalytics(backend)
        result = analytics.detect_circular_dependencies()

        assert result[0]["error"] == "Neo4j GDS plugin not installed"

    def test_get_task_clusters_gds_not_installed(self):
        backend = FakeBackend()
        def raise_gds_error(query, params=None, mode="read"):
            raise Exception("procedure gds.louvain.stream not found")

        backend._run_query = raise_gds_error
        analytics = GovernorAnalytics(backend)
        result = analytics.get_task_clusters()

        assert result[0]["error"] == "Neo4j GDS plugin not installed"

    def test_get_task_criticality_success(self):
        backend = FakeBackend()
        backend._results = [
            # First call: graph projection
            [{"graphName": "gov_task_deps_pr_test"}],
            # Second call: algorithm + results
            [
                {"task_id": "T1", "task_name": "Critical", "status": "ACTIVE", "priority": "HIGH", "criticality_score": 0.9234},
                {"task_id": "T2", "task_name": "Normal", "status": "ACTIVE", "priority": "MEDIUM", "criticality_score": 0.1234},
            ],
        ]
        analytics = GovernorAnalytics(backend)
        result = analytics.get_task_criticality(status_filter="ACTIVE")

        assert len(result) == 2
        assert result[0]["criticality_score"] == 0.9234
