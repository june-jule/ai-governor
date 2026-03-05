"""Abstract backend interface for Governor persistence.

All task data access goes through this interface, so the Governor
engine works with any backend. Implement this to integrate with your
own data store (Neo4j, PostgreSQL, in-memory, etc.).
"""

from abc import ABC, abstractmethod
import collections
import threading
import warnings
from typing import Any, Dict, List, Optional


# Known task field values for validation at the persistence boundary.
_VALID_STATUSES = frozenset({
    "PENDING", "ACTIVE", "READY_FOR_REVIEW", "READY_FOR_GOVERNOR",
    "COMPLETED", "REWORK", "BLOCKED", "FAILED", "ARCHIVED",
})
_VALID_PRIORITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
_VALID_TASK_TYPES = frozenset({
    "INVESTIGATION", "IMPLEMENTATION", "DEPLOY", "AUDIT",
})
_REQUIRED_TASK_FIELDS = ("task_id", "status")

MAX_FIELD_SIZE = 1_000_000  # 1 MB per string field


def validate_task_data(task_data: dict, *, strict: bool = True) -> list:
    """Validate task data before persistence.

    Args:
        task_data: Dict of task properties.
        strict: If True (default), also validate enum field values
            against known sets. Set False to only check required fields.

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list = []
    for field in _REQUIRED_TASK_FIELDS:
        if field not in task_data or not task_data[field]:
            errors.append(f"Missing required field: {field}")

    # Field size validation — enforced by all backends for test/prod parity.
    for key, value in task_data.items():
        if isinstance(value, str) and len(value) > MAX_FIELD_SIZE:
            errors.append(
                f"Field '{key}' exceeds maximum size "
                f"({len(value)} > {MAX_FIELD_SIZE} chars)"
            )

    if strict:
        status = str(task_data.get("status", "")).strip().upper()
        if status and status not in _VALID_STATUSES:
            errors.append(
                f"Invalid status '{task_data.get('status')}'. "
                f"Must be one of: {sorted(_VALID_STATUSES)}"
            )
        priority = str(task_data.get("priority", "")).strip().upper()
        if priority and priority not in _VALID_PRIORITIES:
            errors.append(
                f"Invalid priority '{task_data.get('priority')}'. "
                f"Must be one of: {sorted(_VALID_PRIORITIES)}"
            )
        task_type = str(task_data.get("task_type", "")).strip().upper()
        if task_type and task_type not in _VALID_TASK_TYPES:
            errors.append(
                f"Unknown task_type '{task_data.get('task_type')}'. "
                f"Known types: {sorted(_VALID_TASK_TYPES)}. "
                "Pass strict=False to allow custom types."
            )
    return errors


class GovernorBackend(ABC):
    """Abstract interface for Governor task persistence.

    Subclasses must implement all abstract methods. The Governor engine
    calls these methods instead of accessing any database directly.
    """

    @abstractmethod
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Load a task and its relationships.

        Args:
            task_id: Unique task identifier.

        Returns:
            Dict with keys:
                task: dict of task properties (task_id, task_name, role,
                      task_type, priority, status, content, etc.)
                relationships: list of dicts, each with:
                    type: relationship type (e.g. "HANDOFF_TO", "HAS_REVIEW")
                    node: dict of related node properties
                    node_labels: list of labels on the related node

        Raises:
            ValueError: If the task does not exist.
        """

    @abstractmethod
    def update_task(
        self,
        task_id: str,
        updates: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update task properties.

        Args:
            task_id: Unique task identifier.
            updates: Dict of property names to new values.
                     A value of None means clear/remove the property.
            expected_current_status: Optional optimistic-lock status check.
                If provided, backend should only update when current status
                equals this value.

        Returns:
            Dict with at least: {"success": True, "task_id": ..., "new_status": ...}
            If optimistic lock fails, return:
            {"success": False, "error_code": "STATE_CONFLICT", ...}

        Raises:
            ValueError: If the task does not exist.
        """

    @abstractmethod
    def task_exists(self, task_id: str) -> bool:
        """Check whether a task exists.

        Args:
            task_id: Unique task identifier.

        Returns:
            True if the task exists, False otherwise.
        """

    @abstractmethod
    def get_reviews_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all reviews linked to a task.

        Args:
            task_id: Unique task identifier.

        Returns:
            List of review dicts with at least: review_id, review_type, rating.
        """

    @abstractmethod
    def get_reports_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all reports linked to a task.

        Args:
            task_id: Unique task identifier.

        Returns:
            List of report dicts with at least: report_id, report_type.
        """

    # ------------------------------------------------------------------
    # Lifecycle helpers (optional — concrete defaults raise)
    # ------------------------------------------------------------------

    def create_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new task.

        Args:
            task_data: Dict with at least ``task_id`` plus any other properties.

        Returns:
            The created task dict.

        Raises:
            ValueError: If the task already exists.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement create_task(). "
            "Override this method in your backend subclass."
        )

    def add_review(self, task_id: str, review: Dict[str, Any]) -> None:
        """Link a review to a task.

        Args:
            task_id: Task to link the review to.
            review: Review dict with at least ``review_type``.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_review(). "
            "Override this method in your backend subclass."
        )

    def add_report(self, task_id: str, report: Dict[str, Any]) -> None:
        """Link a report to a task.

        Args:
            task_id: Task to link the report to.
            report: Report dict with at least ``report_type``.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_report(). "
            "Override this method in your backend subclass."
        )

    def add_handoff(self, task_id: str, handoff: Dict[str, Any]) -> None:
        """Link a handoff to a task.

        Args:
            task_id: Task to link the handoff to.
            handoff: Handoff dict with at least ``handoff_id``.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_handoff(). "
            "Override this method in your backend subclass."
        )

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a raw read-only query against the backend.

        .. deprecated::
            ``execute_query`` bypasses Governor's parameterization guardrails.
            Prefer the typed methods (``get_task``, ``get_task_audit_trail``,
            etc.) for standard operations. This method will be removed in a
            future version.

        Args:
            query: Query string in the backend's query language.
            params: Query parameters.

        Returns:
            List of result dicts.
        """
        warnings.warn(
            "execute_query() bypasses Governor's safety guardrails and will be "
            "removed in a future version. Use typed backend methods instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support raw queries. "
            "Use the typed methods (get_task, update_task, etc.) instead."
        )

    def record_transition_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a transition attempt and guard evaluations.

        Backends with graph/event support should implement this to write
        TransitionEvent / GuardEvaluation entities.
        """
        return {"success": False, "error_code": "NOT_SUPPORTED"}

    # Per-task locking for backends without native transactions.
    _use_task_locks: bool = False
    _MAX_TASK_LOCKS: int = 10_000

    def _get_task_lock(self, task_id: str) -> threading.Lock:
        """Return a per-task lock, creating it on first access.

        Uses an LRU-bounded ``OrderedDict`` capped at
        :attr:`_MAX_TASK_LOCKS` entries to prevent unbounded memory
        growth in long-running systems.
        """
        if not hasattr(self, "_task_locks_store"):
            self._task_locks_store: collections.OrderedDict[str, threading.Lock] = (
                collections.OrderedDict()
            )
            self._task_locks_meta = threading.Lock()
        with self._task_locks_meta:
            if task_id in self._task_locks_store:
                self._task_locks_store.move_to_end(task_id)
                return self._task_locks_store[task_id]
            lock = threading.Lock()
            self._task_locks_store[task_id] = lock
            while len(self._task_locks_store) > self._MAX_TASK_LOCKS:
                self._task_locks_store.popitem(last=False)
            return lock

    def apply_transition(
        self,
        task_id: str,
        updates: Dict[str, Any],
        event: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply status updates and persist event in one backend operation.

        Backends with transactional guarantees (for example Neo4j) should
        override this method to ensure task mutation and event persistence
        succeed or fail together.

        .. warning::
            The default implementation uses a best-effort rollback that is
            **not safe under concurrent access** unless ``_use_task_locks``
            is set to ``True`` on the subclass.  For multi-threaded
            environments, either override with a transactional
            implementation or enable per-task locking.
        """
        if self._use_task_locks:
            with self._get_task_lock(task_id):
                return self._apply_transition_inner(
                    task_id, updates, event, expected_current_status,
                )
        return self._apply_transition_inner(
            task_id, updates, event, expected_current_status,
        )

    def _apply_transition_inner(
        self,
        task_id: str,
        updates: Dict[str, Any],
        event: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inner apply logic; may be wrapped with a per-task lock."""
        original_task: Optional[Dict[str, Any]] = None
        if expected_current_status is not None:
            # Best-effort rollback snapshot for backends that do not provide
            # native transaction semantics.
            try:
                original_task = self.get_task(task_id).get("task")
            except Exception:
                original_task = None

        update_result = self.update_task(
            task_id=task_id,
            updates=updates,
            expected_current_status=expected_current_status,
        )
        if not update_result.get("success"):
            return update_result

        event_result = self.record_transition_event(event)
        if not event_result.get("success"):
            rollback_success = False
            if original_task is not None:
                rollback_updates: Dict[str, Any] = {}
                for key in updates.keys():
                    rollback_updates[key] = original_task.get(key)
                try:
                    rollback_result = self.update_task(
                        task_id=task_id,
                        updates=rollback_updates,
                        expected_current_status=update_result.get("new_status"),
                    )
                    rollback_success = bool(rollback_result.get("success"))
                except Exception:
                    rollback_success = False
            return {
                "success": False,
                "error_code": "EVENT_WRITE_FAILED",
                "task_id": task_id,
                "new_status": update_result.get("new_status"),
                "rollback_success": rollback_success,
            }

        return {
            "success": True,
            "task_id": task_id,
            "new_status": update_result.get("new_status"),
            "event_id": event_result.get("event_id"),
        }

    def health_check(self) -> Dict[str, Any]:
        """Return backend health status.

        Subclasses should override to provide meaningful health information
        (e.g. connection status, server version).  The default returns a
        minimal healthy response.
        """
        return {"healthy": True, "backend": self.__class__.__name__}

    def get_task_audit_trail(self, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Return transition events for a task."""
        return []

    def get_guard_failure_hotspots(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return top failing guards across transition events."""
        return []

    def get_policy_coverage(self) -> Dict[str, Any]:
        """Return guard evaluation coverage and pass/fail breakdown."""
        return {"guards": [], "totals": {"evaluations": 0, "passes": 0, "fails": 0}}

    def get_rework_lineage(self, task_id: str) -> Dict[str, Any]:
        """Return rework-oriented lineage for a task."""
        return {"task_id": task_id, "rework_count": 0, "lineage": []}
