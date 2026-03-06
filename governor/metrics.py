"""Metrics collection and Prometheus export for Governor.

Provides counters, histograms, and gauges for transition engine
operations. Works with or without ``prometheus_client`` installed.

Usage::

    from governor.metrics import get_metrics

    metrics = get_metrics()

    # Record a transition attempt
    metrics.transition_attempted("T01", "EXECUTOR")

    # Record a transition result
    metrics.transition_completed("T01", "EXECUTOR", result="PASS")

    # Record guard evaluation
    metrics.guard_evaluated("EG-01", passed=True)

    # Get current snapshot (always works, even without prometheus_client)
    snapshot = metrics.snapshot()

When ``prometheus_client`` is installed, metrics are automatically
available at the default Prometheus scrape endpoint. Without it,
``snapshot()`` returns a plain dict of counters.
"""

import threading
from typing import Any, Dict, Optional

try:
    from prometheus_client import Counter, Histogram, Gauge  # type: ignore[import-untyped]
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


class _InternalCounters:
    """Thread-safe in-memory counters for when prometheus_client is absent."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._durations: Dict[str, float] = {}
        self._duration_counts: Dict[str, int] = {}

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe_duration(self, name: str, duration: float) -> None:
        with self._lock:
            self._durations[name] = self._durations.get(name, 0.0) + duration
            self._duration_counts[name] = self._duration_counts.get(name, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            result: Dict[str, Any] = dict(self._counters)
            for name in self._durations:
                count = self._duration_counts.get(name, 1)
                result[f"{name}_total_seconds"] = round(self._durations[name], 6)
                result[f"{name}_avg_seconds"] = (
                    round(self._durations[name] / count, 6) if count else 0.0
                )
            return result


class GovernorMetrics:
    """Metrics collector for Governor engine operations.

    Automatically uses ``prometheus_client`` if installed, otherwise
    falls back to in-memory counters accessible via ``snapshot()``.
    """

    def __init__(self, namespace: str = "governor") -> None:
        self._ns = namespace
        self._internal = _InternalCounters()

        if _HAS_PROMETHEUS:
            self._transitions_total = Counter(
                f"{namespace}_transitions_total",
                "Total transition attempts",
                ["transition_id", "calling_role", "result"],
            )
            self._guard_evals_total = Counter(
                f"{namespace}_guard_evaluations_total",
                "Total guard evaluations",
                ["guard_id", "passed"],
            )
            self._transition_duration = Histogram(
                f"{namespace}_transition_duration_seconds",
                "Transition execution duration",
                ["transition_id"],
                buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            )
            self._guard_duration = Histogram(
                f"{namespace}_guard_duration_seconds",
                "Per-guard evaluation duration",
                ["guard_id"],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            )
            self._active_transitions = Gauge(
                f"{namespace}_active_transitions",
                "Currently in-flight transitions",
            )
            self._rate_limited_total = Counter(
                f"{namespace}_rate_limited_total",
                "Transitions rejected by rate limiter",
                ["task_id_prefix"],
            )

    def transition_attempted(
        self, transition_id: str, calling_role: str,
    ) -> None:
        """Record a transition attempt starting."""
        key = f"transition_attempted:{transition_id}:{calling_role}"
        self._internal.inc(key)
        if _HAS_PROMETHEUS:
            self._active_transitions.inc()

    def transition_completed(
        self,
        transition_id: str,
        calling_role: str,
        result: str = "PASS",
        duration_seconds: Optional[float] = None,
    ) -> None:
        """Record a transition completion."""
        key = f"transition_completed:{transition_id}:{result}"
        self._internal.inc(key)
        if duration_seconds is not None:
            self._internal.observe_duration(f"transition_duration:{transition_id}", duration_seconds)

        if _HAS_PROMETHEUS:
            self._transitions_total.labels(
                transition_id=transition_id,
                calling_role=calling_role,
                result=result,
            ).inc()
            self._active_transitions.dec()
            if duration_seconds is not None:
                self._transition_duration.labels(transition_id=transition_id).observe(
                    duration_seconds
                )

    def guard_evaluated(
        self,
        guard_id: str,
        passed: bool,
        duration_seconds: Optional[float] = None,
    ) -> None:
        """Record a guard evaluation."""
        result_label = "true" if passed else "false"
        key = f"guard_eval:{guard_id}:{result_label}"
        self._internal.inc(key)
        if duration_seconds is not None:
            self._internal.observe_duration(f"guard_duration:{guard_id}", duration_seconds)

        if _HAS_PROMETHEUS:
            self._guard_evals_total.labels(guard_id=guard_id, passed=result_label).inc()
            if duration_seconds is not None:
                self._guard_duration.labels(guard_id=guard_id).observe(duration_seconds)

    def rate_limited(self, task_id: str) -> None:
        """Record a rate-limited transition rejection."""
        prefix = task_id.split("_")[0] if "_" in task_id else task_id
        self._internal.inc(f"rate_limited:{prefix}")
        if _HAS_PROMETHEUS:
            self._rate_limited_total.labels(task_id_prefix=prefix).inc()

    def snapshot(self) -> Dict[str, Any]:
        """Return current metrics as a plain dict (always works)."""
        return {
            "prometheus_available": _HAS_PROMETHEUS,
            "counters": self._internal.snapshot(),
        }


# Module-level singleton
_metrics: Optional[GovernorMetrics] = None
_metrics_lock = threading.Lock()


def get_metrics(namespace: str = "governor") -> GovernorMetrics:
    """Return the global GovernorMetrics singleton.

    Thread-safe. Creates the instance on first call.
    """
    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = GovernorMetrics(namespace=namespace)
    return _metrics


def prometheus_available() -> bool:
    """Return True if prometheus_client is installed."""
    return _HAS_PROMETHEUS
