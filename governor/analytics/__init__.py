"""Governor Graph Analytics — Neo4j graph algorithm integration.

Provides graph-based analytics on Governor's audit trail using
both native Cypher queries and Neo4j GDS (Graph Data Science) algorithms.
"""

from governor.analytics.graph_algorithms import GovernorAnalytics

__all__ = ["GovernorAnalytics"]
