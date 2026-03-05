"""In-memory backend for Governor — ideal for testing and demos.

Stores tasks, reviews, and reports in plain Python dicts.
No external dependencies required.

Classes:
    MemoryBackend — Not thread-safe. For single-threaded tests and demos.
    ThreadSafeMemoryBackend — Uses per-task locking for concurrent access.
"""

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from governor.backend.base import GovernorBackend, validate_task_data, MAX_FIELD_SIZE


class MemoryBackend(GovernorBackend):
    """Dict-based in-memory backend.

    .. warning::
        MemoryBackend is **not thread-safe**.  It is designed for single-threaded
        usage in tests, demos, and development.  For multi-threaded or concurrent
        agent scenarios, use :class:`Neo4jBackend` or guard access with an
        external lock.

    Usage::

        backend = MemoryBackend()
        backend.create_task({
            "task_id": "TASK_001",
            "task_name": "My first task",
            "task_type": "IMPLEMENTATION",
            "role": "DEVELOPER",
            "status": "ACTIVE",
            "priority": "HIGH",
            "content": "Implement the feature.",
        })
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._reviews: Dict[str, List[Dict[str, Any]]] = {}  # task_id -> [review, ...]
        self._reports: Dict[str, List[Dict[str, Any]]] = {}  # task_id -> [report, ...]
        self._handoffs: Dict[str, List[Dict[str, Any]]] = {}  # task_id -> [handoff, ...]
        self._transition_events: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # GovernorBackend interface
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Dict[str, Any]:
        if task_id not in self._tasks:
            raise ValueError(f"Task not found: {task_id}")

        task = copy.deepcopy(self._tasks[task_id])
        relationships = self._build_relationships(task_id)
        return {"task": task, "relationships": relationships}

    def update_task(
        self,
        task_id: str,
        updates: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        if task_id not in self._tasks:
            raise ValueError(f"Task not found during update: {task_id}")

        task = self._tasks[task_id]
        if expected_current_status is not None and task.get("status") != expected_current_status:
            return {
                "success": False,
                "error_code": "STATE_CONFLICT",
                "task_id": task_id,
                "expected_current_status": expected_current_status,
                "actual_current_status": task.get("status"),
            }
        for key, value in updates.items():
            if value is None:
                task.pop(key, None)
            else:
                task[key] = _normalize_task_field(key, value)

        task["last_updated"] = datetime.now(timezone.utc).isoformat()
        return {"success": True, "task_id": task_id, "new_status": task.get("status")}

    def task_exists(self, task_id: str) -> bool:
        return task_id in self._tasks

    def get_reviews_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._reviews.get(task_id, []))

    def get_reports_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._reports.get(task_id, []))

    # ------------------------------------------------------------------
    # Convenience methods (not part of the abstract interface)
    # ------------------------------------------------------------------

    def create_task(self, task_data: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
        """Create a new task in the in-memory store.

        Args:
            task_data: Dict with at least task_id plus any other properties.
            strict: Validate enum fields against known values. Default True.

        Returns:
            The created task dict.

        Raises:
            ValueError: If validation fails or task already exists.
        """
        errors = validate_task_data(task_data, strict=strict)
        if errors:
            raise ValueError(f"Invalid task data: {'; '.join(errors)}")
        task_id = task_data["task_id"]
        if task_id in self._tasks:
            raise ValueError(f"Task already exists: {task_id}")
        now = datetime.now(timezone.utc).isoformat()
        task = {k: _normalize_task_field(k, v) for k, v in task_data.items()}
        task.setdefault("created_date", now[:10])
        task.setdefault("last_updated", now)
        self._tasks[task_id] = task
        return copy.deepcopy(task)

    def apply_transition(
        self,
        task_id: str,
        updates: Dict[str, Any],
        event: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically apply status update and append transition event in-memory."""
        if task_id not in self._tasks:
            raise ValueError(f"Task not found during update: {task_id}")

        original_task = copy.deepcopy(self._tasks[task_id])
        original_events_len = len(self._transition_events)
        try:
            update_result = self.update_task(
                task_id=task_id,
                updates=updates,
                expected_current_status=expected_current_status,
            )
            if not update_result.get("success"):
                return update_result

            event_result = self.record_transition_event(event)
            if not event_result.get("success"):
                # Roll back state update to keep state/event consistency.
                self._tasks[task_id] = original_task
                self._transition_events = self._transition_events[:original_events_len]
                return {
                    "success": False,
                    "error_code": "EVENT_WRITE_FAILED",
                    "task_id": task_id,
                }

            return {
                "success": True,
                "task_id": task_id,
                "new_status": update_result.get("new_status"),
                "event_id": event_result.get("event_id"),
            }
        except Exception:
            self._tasks[task_id] = original_task
            self._transition_events = self._transition_events[:original_events_len]
            raise

    def add_review(self, task_id: str, review: Dict[str, Any]) -> None:
        """Link a review to a task.

        Args:
            task_id: Task to link the review to.
            review: Review dict with at least review_type.
        """
        self._reviews.setdefault(task_id, []).append(copy.deepcopy(review))

    def add_report(self, task_id: str, report: Dict[str, Any]) -> None:
        """Link a report to a task.

        Args:
            task_id: Task to link the report to.
            report: Report dict with at least report_type.
        """
        self._reports.setdefault(task_id, []).append(copy.deepcopy(report))

    def add_handoff(self, task_id: str, handoff: Dict[str, Any]) -> None:
        """Link a handoff to a task.

        Args:
            task_id: Task to link the handoff to.
            handoff: Handoff dict with at least handoff_id, from_role, to_role.
        """
        self._handoffs.setdefault(task_id, []).append(copy.deepcopy(handoff))

    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of all tasks."""
        return copy.deepcopy(self._tasks)

    def record_transition_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        event_copy = copy.deepcopy(event)
        event_copy.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        event_copy.setdefault("event_id", f"EVT_{len(self._transition_events) + 1:06d}")
        self._transition_events.append(event_copy)
        return {"success": True, "event_id": event_copy["event_id"]}

    def get_task_audit_trail(self, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit))
        matching = [e for e in self._transition_events if e.get("task_id") == task_id]
        # Align ordering with Neo4jBackend: newest events first.
        # ISO timestamps sort lexicographically, so we can sort safely when present.
        def _sort_key(e: Dict[str, Any]) -> str:
            return str(e.get("occurred_at") or e.get("recorded_at") or e.get("event_id") or "")

        matching_sorted = sorted(matching, key=_sort_key, reverse=True)
        return copy.deepcopy(matching_sorted[:safe_limit])

    def get_guard_failure_hotspots(self, limit: int = 10) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit))
        counts: Dict[str, Dict[str, Any]] = {}
        for event in self._transition_events:
            for result in event.get("guard_results", []):
                guard_id = str(result.get("guard_id", "UNKNOWN"))
                entry = counts.setdefault(guard_id, {"guard_id": guard_id, "evaluations": 0, "failures": 0})
                entry["evaluations"] += 1
                if not bool(result.get("passed")):
                    entry["failures"] += 1
        ranked = sorted(counts.values(), key=lambda row: (row["failures"], row["evaluations"]), reverse=True)
        return ranked[:safe_limit]

    def get_policy_coverage(self) -> Dict[str, Any]:
        stats: Dict[str, Dict[str, int]] = {}
        total_evals = 0
        total_pass = 0
        total_fail = 0
        for event in self._transition_events:
            for result in event.get("guard_results", []):
                guard_id = str(result.get("guard_id", "UNKNOWN"))
                item = stats.setdefault(guard_id, {"evaluations": 0, "passes": 0, "fails": 0})
                item["evaluations"] += 1
                total_evals += 1
                if bool(result.get("passed")):
                    item["passes"] += 1
                    total_pass += 1
                else:
                    item["fails"] += 1
                    total_fail += 1
        guards = [{"guard_id": gid, **vals} for gid, vals in sorted(stats.items())]
        return {"guards": guards, "totals": {"evaluations": total_evals, "passes": total_pass, "fails": total_fail}}

    def get_rework_lineage(self, task_id: str) -> Dict[str, Any]:
        events = [e for e in self._transition_events if e.get("task_id") == task_id]
        lineage = [
            {
                "transition_id": e.get("transition_id"),
                "from_state": e.get("from_state"),
                "to_state": e.get("to_state"),
                "result": e.get("result"),
                "occurred_at": e.get("occurred_at"),
            }
            for e in events
            if e.get("result") == "PASS"
        ]
        rework_count = sum(1 for e in lineage if e.get("to_state") == "REWORK")
        return {"task_id": task_id, "rework_count": rework_count, "lineage": lineage}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_relationships(self, task_id: str) -> List[Dict[str, Any]]:
        """Build a relationships list matching the GovernorBackend contract."""
        rels: List[Dict[str, Any]] = []

        for review in self._reviews.get(task_id, []):
            rels.append({
                "type": "HAS_REVIEW",
                "node": copy.deepcopy(review),
                "node_labels": ["Review"],
            })

        for report in self._reports.get(task_id, []):
            rels.append({
                "type": "REPORTS_ON",
                "node": copy.deepcopy(report),
                "node_labels": ["Report"],
            })

        for handoff in self._handoffs.get(task_id, []):
            rels.append({
                "type": "HANDOFF_TO",
                "node": copy.deepcopy(handoff),
                "node_labels": ["Handoff"],
            })

        return rels


class ThreadSafeMemoryBackend(MemoryBackend):
    """Thread-safe variant of :class:`MemoryBackend`.

    Wraps every public method with a :class:`threading.RLock` so concurrent
    callers (e.g. multi-threaded agent runners) don't corrupt shared state.
    Also enables per-task locking via the base class ``_use_task_locks``
    flag for finer-grained concurrency on ``apply_transition``.

    Performance: the global lock serialises all operations. For high-throughput
    production use cases, prefer :class:`Neo4jBackend` which offloads
    concurrency to the database.

    Usage::

        from governor.backend.memory_backend import ThreadSafeMemoryBackend

        backend = ThreadSafeMemoryBackend()
        # Safe to use from multiple threads.
    """

    _use_task_locks = True

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.RLock()

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            return super().get_task(task_id)

    def update_task(
        self,
        task_id: str,
        updates: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            return super().update_task(task_id, updates, expected_current_status)

    def task_exists(self, task_id: str) -> bool:
        with self._lock:
            return super().task_exists(task_id)

    def get_reviews_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return super().get_reviews_for_task(task_id)

    def get_reports_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return super().get_reports_for_task(task_id)

    def create_task(self, task_data: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
        with self._lock:
            return super().create_task(task_data, strict=strict)

    def apply_transition(
        self,
        task_id: str,
        updates: Dict[str, Any],
        event: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            return super().apply_transition(task_id, updates, event, expected_current_status)

    def add_review(self, task_id: str, review: Dict[str, Any]) -> None:
        with self._lock:
            super().add_review(task_id, review)

    def add_report(self, task_id: str, report: Dict[str, Any]) -> None:
        with self._lock:
            super().add_report(task_id, report)

    def add_handoff(self, task_id: str, handoff: Dict[str, Any]) -> None:
        with self._lock:
            super().add_handoff(task_id, handoff)

    def record_transition_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return super().record_transition_event(event)

    def get_task_audit_trail(self, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return super().get_task_audit_trail(task_id, limit)

    def get_guard_failure_hotspots(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            return super().get_guard_failure_hotspots(limit)

    def get_policy_coverage(self) -> Dict[str, Any]:
        with self._lock:
            return super().get_policy_coverage()

    def get_rework_lineage(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            return super().get_rework_lineage(task_id)

    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return super().get_all_tasks()


def _normalize_task_field(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and len(value) > MAX_FIELD_SIZE:
        raise ValueError(
            f"Field '{key}' exceeds maximum size "
            f"({len(value)} > {MAX_FIELD_SIZE} chars)"
        )
    if key in {"task_type", "status", "role", "priority"} and isinstance(value, str):
        return value.strip().upper()
    return value
