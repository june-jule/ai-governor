"""Async backend interface for Governor persistence.

Mirrors :class:`GovernorBackend` but with ``async`` methods for use
with :class:`AsyncTransitionEngine`.
"""

import asyncio
import collections
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AsyncGovernorBackend(ABC):
    """Async abstract interface for Governor task persistence.

    Subclasses must implement all abstract methods. Use this with
    :class:`~governor.engine.async_engine.AsyncTransitionEngine`.
    """

    @abstractmethod
    async def get_task(self, task_id: str) -> Dict[str, Any]:
        """Load a task and its relationships.

        Returns:
            Dict with keys: task (dict), relationships (list of dicts).

        Raises:
            ValueError: If the task does not exist.
        """

    @abstractmethod
    async def update_task(
        self,
        task_id: str,
        updates: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update task properties.

        Returns:
            Dict with at least: {"success": True, "task_id": ..., "new_status": ...}
        """

    @abstractmethod
    async def task_exists(self, task_id: str) -> bool:
        """Check whether a task exists."""

    @abstractmethod
    async def get_reviews_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all reviews linked to a task."""

    @abstractmethod
    async def get_reports_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all reports linked to a task."""

    async def execute_query(
        self, query: str, params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a raw query (optional extension point)."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support raw queries."
        )

    async def record_transition_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Persist transition attempt and guard evaluations."""
        return {"success": False, "error_code": "NOT_SUPPORTED"}

    # Per-task locking for backends without native transactions.
    _use_task_locks: bool = False
    _MAX_TASK_LOCKS: int = 10_000

    def _get_task_lock(self, task_id: str) -> asyncio.Lock:
        """Return a per-task async lock, creating it on first access.

        Uses an LRU-bounded ``OrderedDict`` capped at
        :attr:`_MAX_TASK_LOCKS` entries to prevent unbounded memory
        growth in long-running systems.
        """
        if not hasattr(self, "_task_locks_store"):
            self._task_locks_store: collections.OrderedDict[str, asyncio.Lock] = (
                collections.OrderedDict()
            )
        if task_id in self._task_locks_store:
            self._task_locks_store.move_to_end(task_id)
            return self._task_locks_store[task_id]
        lock = asyncio.Lock()
        self._task_locks_store[task_id] = lock
        while len(self._task_locks_store) > self._MAX_TASK_LOCKS:
            self._task_locks_store.popitem(last=False)
        return lock

    async def apply_transition(
        self,
        task_id: str,
        updates: Dict[str, Any],
        event: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply task updates and event persistence in one backend call.

        Async backends with transactional support should override this method.

        .. warning::
            The default implementation uses a best-effort rollback that is
            **not safe under concurrent access** unless ``_use_task_locks``
            is set to ``True`` on the subclass.
        """
        if self._use_task_locks:
            async with self._get_task_lock(task_id):
                return await self._apply_transition_inner(
                    task_id, updates, event, expected_current_status,
                )
        return await self._apply_transition_inner(
            task_id, updates, event, expected_current_status,
        )

    async def _apply_transition_inner(
        self,
        task_id: str,
        updates: Dict[str, Any],
        event: Dict[str, Any],
        expected_current_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inner apply logic; may be wrapped with a per-task lock."""
        original_task: Optional[Dict[str, Any]] = None
        if expected_current_status is not None:
            try:
                original_task = (await self.get_task(task_id)).get("task")
            except Exception:
                original_task = None

        update_result = await self.update_task(
            task_id=task_id,
            updates=updates,
            expected_current_status=expected_current_status,
        )
        if not update_result.get("success"):
            return update_result

        event_result = await self.record_transition_event(event)
        if not event_result.get("success"):
            rollback_success = False
            if original_task is not None:
                rollback_updates: Dict[str, Any] = {}
                for key in updates.keys():
                    rollback_updates[key] = original_task.get(key)
                try:
                    rollback_result = await self.update_task(
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

    async def get_task_audit_trail(self, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Return transition events for a task."""
        return []

    async def get_guard_failure_hotspots(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return top failing guards across transition events."""
        return []

    async def get_policy_coverage(self) -> Dict[str, Any]:
        """Return guard evaluation coverage and pass/fail breakdown."""
        return {"guards": [], "totals": {"evaluations": 0, "passes": 0, "fails": 0}}

    async def get_rework_lineage(self, task_id: str) -> Dict[str, Any]:
        """Return rework-oriented lineage for a task."""
        return {"task_id": task_id, "rework_count": 0, "lineage": []}
