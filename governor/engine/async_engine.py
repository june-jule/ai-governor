"""Async Transition Engine — async variant of the core state machine.

Shares guard registry, state machine loading, and helpers with the
synchronous :class:`TransitionEngine`. Only backend I/O is async.

Usage::

    from governor.engine.async_engine import AsyncTransitionEngine

    engine = AsyncTransitionEngine(backend=my_async_backend)
    result = await engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR")
"""

import asyncio
import logging
import inspect
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from governor.backend.async_base import AsyncGovernorBackend
from governor.engine.telemetry import get_tracer
from governor.engine.transition_engine import (
    GuardContext,
    GuardResult,
    GuardCallable,
    _RateLimiter,
    _load_state_machine,
    _error_response,
    _render_template,
    _resolve_guard,
    _guard_registry,
    _ensure_builtin_guards_loaded,
    _normalize_state,
)
from governor.engine.validation import validate_state_machine

logger = logging.getLogger("governor.engine.async")


class AsyncTransitionEngine:
    """Async state machine enforcement engine.

    Mirrors :class:`~governor.engine.transition_engine.TransitionEngine`
    but uses ``await`` for all backend calls. Guards remain synchronous
    (they are pure CPU evaluations with no I/O).

    Args:
        backend: An :class:`AsyncGovernorBackend` implementation.
        state_machine_path: Path to state machine JSON. Defaults to bundled
            ``governor/schema/state_machine.json``.
        role_aliases: Optional role alias mapping.
        event_callbacks: Optional post-transition callbacks.
        strict: Raise on unregistered guards (default True).
        guard_timeout_seconds: Per-guard execution timeout in seconds.
            ``None`` disables (default).

            **Timeout semantics (fail-closed):**

            - A timed-out guard produces ``GuardResult(passed=False)`` —
              the transition is blocked, never silently allowed.
            - All guards run to completion; no short-circuit on timeout.
            - The timed-out coroutine is cancelled via
              ``asyncio.wait_for``, which provides true cancellation
              unlike the sync engine's thread-based timeout.
            - **Retry guidance:** Timeouts do *not* auto-retry. Callers
              should inspect ``guard_results`` for ``"Guard timed out"``
              reasons and retry the transition if appropriate.  Retries
              are safe (optimistic concurrency control).

        parallel_guards: Evaluate guards concurrently via
            ``asyncio.gather``. Automatically enabled when
            ``guard_timeout_seconds`` is set.
    """

    def __init__(
        self,
        backend: AsyncGovernorBackend,
        state_machine_path: Optional[str] = None,
        role_aliases: Optional[Dict[str, str]] = None,
        event_callbacks: Optional[List[Callable[..., Any]]] = None,
        strict: bool = True,
        guard_timeout_seconds: Optional[float] = None,
        parallel_guards: bool = False,
        rate_limit: Optional[tuple[int, float]] = None,
    ) -> None:
        self._backend = backend
        self._role_aliases = role_aliases or {}
        self._strict = strict
        self._event_callbacks = event_callbacks or []
        self._guard_timeout_seconds = guard_timeout_seconds
        self._parallel_guards = bool(parallel_guards or guard_timeout_seconds is not None)

        self._rate_limiter: Optional[_RateLimiter] = None
        if rate_limit is not None:
            max_attempts, window_seconds = rate_limit
            self._rate_limiter = _RateLimiter(max_attempts, window_seconds)

        self._state_machine = _load_state_machine(state_machine_path)
        self._state_machine_version: str = (
            self._state_machine.get("_meta", {}).get("version", "unknown")
        )
        _ensure_builtin_guards_loaded(self._state_machine)

        # Instance-level guard registry: copy from global so each engine
        # is isolated from other engines' guard registrations.
        self._instance_guard_registry: Dict[str, GuardCallable] = dict(_guard_registry)

        errors = validate_state_machine(self._state_machine)
        if errors:
            raise ValueError(f"Invalid state machine: {'; '.join(errors)}")
        self._tracer = get_tracer()

    @property
    def state_machine_version(self) -> str:
        """Return the version string from the loaded state machine ``_meta``."""
        return self._state_machine_version

    # ------------------------------------------------------------------
    # Helpers (shared logic with sync engine)
    # ------------------------------------------------------------------

    def _normalize_calling_role(self, calling_role: str) -> str:
        normalized = calling_role.strip().upper()
        return self._role_aliases.get(normalized, normalized)

    def _find_transition(self, from_state: str, to_state: str) -> Optional[Dict[str, Any]]:
        for t in self._state_machine["transitions"]:
            if t["from_state"] == from_state and t["to_state"] == to_state:
                return t
        return None

    def _get_all_transitions_from(self, from_state: str) -> List[Dict[str, Any]]:
        return [t for t in self._state_machine["transitions"] if t["from_state"] == from_state]

    def register_guard(
        self,
        guard_id: str,
        fn: GuardCallable,
        overwrite: bool = True,
    ) -> None:
        """Register a guard on this engine instance (does not affect other instances)."""
        if not overwrite and guard_id in self._instance_guard_registry:
            return
        self._instance_guard_registry[guard_id] = fn

    def _resolve_guard_instance(self, guard_ref: Any) -> tuple[str, GuardCallable]:
        """Resolve a guard reference using the instance registry first."""
        if isinstance(guard_ref, str):
            guard_id = guard_ref
            fn = self._instance_guard_registry.get(guard_id) or _guard_registry.get(guard_id)
            if fn is None:
                if self._strict:
                    raise ValueError(
                        f"Guard '{guard_id}' not found in registry. "
                        "Register it with @register_guard or engine.register_guard()."
                    )
                return guard_id, lambda ctx: GuardResult(guard_id, True, "Guard not found — skipped (non-strict)")
            return guard_id, fn

        if isinstance(guard_ref, dict):
            guard_id = guard_ref.get("guard_id", "")
            if not guard_id:
                raise ValueError("Guard definition missing 'guard_id'")
            fn = self._instance_guard_registry.get(guard_id) or _guard_registry.get(guard_id)
            if fn is None:
                if self._strict:
                    raise ValueError(f"Guard '{guard_id}' not found in registry.")
                return guard_id, lambda ctx: GuardResult(guard_id, True, "Guard not found — skipped (non-strict)")
            return guard_id, fn

        raise ValueError(f"Invalid guard reference type: {type(guard_ref)}")

    async def _fire_events(
        self, transition_def: Dict[str, Any], task_id: str,
        task: Dict[str, Any], transition_params: Dict[str, Any],
    ) -> List[str]:
        events_fired: List[str] = []
        for event in transition_def.get("events", []):
            event_id = event.get("event_id", "unknown")
            event_type = event.get("type")
            config = event.get("config", {})
            try:
                if event_type == "notification":
                    template = config.get("template", "")
                    rendered = _render_template(template, task_id, task, transition_params)
                    severity = config.get("severity", "INFO")
                    logger.info(f"[EVENT:{event_id}] [{severity}] {rendered}")
                    events_fired.append(event_id)
                else:
                    all_ok = True
                    for cb in self._event_callbacks:
                        try:
                            cb_result = cb(event_type, config, task_id, task, transition_params)
                            if inspect.isawaitable(cb_result):
                                await cb_result
                        except Exception as cb_err:
                            logger.error(f"Event callback error for {event_id}: {cb_err}")
                            all_ok = False
                    if all_ok:
                        events_fired.append(event_id)
            except Exception as e:
                logger.error(f"Event {event_id} ({event_type}) failed: {e}")
        return events_fired

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def _evaluate_single_guard(
        self,
        guard_id: str,
        guard_fn: Callable[[GuardContext], GuardResult],
        ctx: GuardContext,
        task_id: str,
        transition_id: str,
    ) -> GuardResult:
        """Run a single guard with optional timeout (fail-closed).

        Timeout behaviour: a guard exceeding ``guard_timeout_seconds``
        produces ``GuardResult(passed=False)`` with reason
        ``"Guard timed out after Xs"``.  The coroutine is cancelled via
        ``asyncio.wait_for``.  The transition is never silently allowed
        on timeout — this is a fail-closed design.
        """
        with self._tracer.start_as_current_span(f"guard.{guard_id}") as span:
            span.set_attribute("governor.guard_id", guard_id)
            span.set_attribute("governor.task_id", task_id)
            try:
                coro = asyncio.to_thread(guard_fn, ctx)
                if self._guard_timeout_seconds is not None:
                    result = await asyncio.wait_for(coro, timeout=self._guard_timeout_seconds)
                else:
                    result = await coro
                span.set_attribute("governor.guard_passed", result.passed)
                return result
            except asyncio.TimeoutError:
                logger.error(
                    "Guard %s timed out after %.1fs",
                    guard_id,
                    self._guard_timeout_seconds,
                    extra={"ctx": {"guard_id": guard_id, "task_id": task_id, "transition_id": transition_id}},
                )
                span.set_attribute("governor.guard_passed", False)
                return GuardResult(guard_id, False, f"Guard timed out after {self._guard_timeout_seconds}s")
            except Exception as e:
                logger.error(
                    f"Guard {guard_id} raised exception: {e}",
                    exc_info=True,
                    extra={"ctx": {"guard_id": guard_id, "task_id": task_id, "transition_id": transition_id}},
                )
                span.record_exception(e)
                span.set_attribute("governor.guard_passed", False)
                return GuardResult(guard_id, False, f"Guard error: {e}")

    async def transition_task(
        self,
        task_id: str,
        target_state: str,
        calling_role: str,
        dry_run: bool = False,
        transition_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute (or dry-run) a state transition. Async version."""
        transition_params = transition_params or {}

        with self._tracer.start_as_current_span("governor.transition") as _root_span:
            _root_span.set_attribute("governor.task_id", task_id)
            _root_span.set_attribute("governor.target_state", target_state)
            _root_span.set_attribute("governor.calling_role", calling_role)
            _root_span.set_attribute("governor.dry_run", dry_run)
            return await self._do_transition(
                task_id, target_state, calling_role, dry_run, transition_params, _root_span,
            )

    async def _do_transition(
        self,
        task_id: str,
        target_state: str,
        calling_role: str,
        dry_run: bool,
        transition_params: Dict[str, Any],
        _span: Any,
    ) -> Dict[str, Any]:
        """Inner transition logic — extracted to avoid re-indenting the entire method."""

        # 0. Rate-limit check (before any backend call)
        if self._rate_limiter is not None and not self._rate_limiter.check(task_id):
            _span.set_attribute("governor.result", "RATE_LIMITED")
            return _error_response(
                "RATE_LIMITED",
                f"Too many transition attempts for task '{task_id}'. Try again later.",
            )

        with self._tracer.start_as_current_span("governor.load_task") as load_span:
            try:
                task_data = await self._backend.get_task(task_id)
                load_span.set_attribute("governor.task_found", True)
            except ValueError as e:
                load_span.set_attribute("governor.task_found", False)
                _span.set_attribute("governor.result", "TASK_NOT_FOUND")
                return _error_response("TASK_NOT_FOUND", str(e))
            except Exception as e:
                load_span.set_attribute("governor.task_found", False)
                load_span.record_exception(e)
                _span.set_attribute("governor.result", "BACKEND_ERROR")
                logger.error(f"Backend read failed for task '{task_id}': {e}", exc_info=True)
                return _error_response("BACKEND_ERROR", f"Backend read failed: {e}")

        task = task_data["task"]
        from_state = _normalize_state(task.get("status"))
        target_state = _normalize_state(target_state)

        transition_def = self._find_transition(from_state, target_state)
        if transition_def is None:
            return _error_response(
                "ILLEGAL_TRANSITION",
                f"No transition defined from '{from_state}' to '{target_state}'",
                from_state=from_state, to_state=target_state,
            )

        effective_role = self._normalize_calling_role(calling_role)
        allowed_roles = transition_def.get("allowed_roles", [])
        if effective_role not in allowed_roles:
            return _error_response(
                "ROLE_NOT_AUTHORIZED",
                f"Role '{calling_role}' not authorized for {from_state} -> {target_state}. "
                f"Allowed: {allowed_roles}",
                from_state=from_state, to_state=target_state, allowed_roles=allowed_roles,
            )

        ctx = GuardContext(task_id, task_data, transition_params, backend=self._backend)

        resolved_guards: List[tuple[str, Callable[[GuardContext], GuardResult]]] = []
        for guard_ref in transition_def.get("guards", []):
            try:
                guard_id, guard_fn = self._resolve_guard_instance(guard_ref)
            except ValueError as e:
                return _error_response(
                    "GUARD_NOT_FOUND",
                    str(e),
                    transition_id=transition_def.get("id"),
                    from_state=from_state,
                    to_state=target_state,
                )
            resolved_guards.append((guard_id, guard_fn))

        with self._tracer.start_as_current_span("governor.evaluate_guards") as guards_span:
            guards_span.set_attribute("governor.guard_count", len(resolved_guards))
            guards_span.set_attribute("governor.parallel", self._parallel_guards)
            guard_results: List[GuardResult] = []
            if self._parallel_guards and len(resolved_guards) > 1:
                guard_tasks = [
                    self._evaluate_single_guard(guard_id, guard_fn, ctx, task_id, transition_def.get("id", ""))
                    for guard_id, guard_fn in resolved_guards
                ]
                guard_results = list(await asyncio.gather(*guard_tasks))
            else:
                for guard_id, guard_fn in resolved_guards:
                    result = await self._evaluate_single_guard(
                        guard_id,
                        guard_fn,
                        ctx,
                        task_id,
                        transition_def.get("id", ""),
                    )
                    guard_results.append(result)

            # Ensure deterministic ordering for parallel evaluation so that
            # rejection_reason always reports the same failing guard.
            if self._parallel_guards and len(guard_results) > 1:
                guard_results.sort(key=lambda gr: gr.guard_id)
            guards_span.set_attribute("governor.guards_passed", sum(1 for g in guard_results if g.passed))
            guards_span.set_attribute("governor.guards_failed", sum(1 for g in guard_results if not g.passed))

        # Compute overall PASS/FAIL (supports AND/OR guard composition)
        guard_mode = transition_def.get("guard_mode", "AND").upper()
        rejection_reason = None
        if guard_mode == "OR" and guard_results:
            any_passed = any(gr.passed for gr in guard_results)
            overall_result = "PASS" if any_passed else "FAIL"
            if not any_passed:
                rejection_reason = "; ".join(
                    gr.reason for gr in guard_results if not gr.passed
                )
        else:
            overall_result = "PASS"
            for gr in guard_results:
                if not gr.passed:
                    overall_result = "FAIL"
                    if not rejection_reason:
                        rejection_reason = gr.reason

        response: Dict[str, Any] = {
            "result": overall_result,
            "transition_id": transition_def["id"],
            "from_state": from_state,
            "to_state": target_state,
            "guard_results": [gr.to_dict() for gr in guard_results],
            "dry_run": dry_run,
            "events_fired": [],
            "temporal_updates": {},
            "rejection_reason": rejection_reason,
        }

        event_payload: Dict[str, Any] = {
            "task_id": task_id,
            "transition_id": transition_def["id"],
            "from_state": from_state,
            "to_state": target_state,
            "calling_role": effective_role,
            "result": overall_result,
            "dry_run": bool(dry_run),
            "rejection_reason": rejection_reason,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "guard_results": [gr.to_dict() for gr in guard_results],
            "state_machine_version": self._state_machine_version,
        }

        if dry_run or overall_result == "FAIL":
            _span.set_attribute("governor.result", overall_result)
            _span.set_attribute("governor.from_state", from_state)
            try:
                await self._backend.record_transition_event(event_payload)
            except Exception as e:
                logger.warning(f"Failed to record transition event for task '{task_id}': {e}")
            return response

        # 9. Apply state change via backend
        with self._tracer.start_as_current_span("governor.apply_transition") as apply_span:
            updates: Dict[str, Any] = {"status": target_state}
            temporal = transition_def.get("temporal_fields", {})
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            for field in temporal.get("set", []):
                updates[field] = now_iso
                response["temporal_updates"][field] = now_iso
            for field in temporal.get("clear", []):
                updates[field] = None
                response["temporal_updates"][field] = None
            if "increment" in temporal:
                for field in temporal["increment"]:
                    current_val = int(task.get(field) or 0)
                    updates[field] = current_val + 1
                    response["temporal_updates"][field] = current_val + 1
            if "reset" in temporal:
                for field in temporal["reset"]:
                    updates[field] = 0
                    response["temporal_updates"][field] = 0

            event_payload["result"] = "PASS"
            try:
                apply_result = await self._backend.apply_transition(
                    task_id=task_id,
                    updates=updates,
                    event=event_payload,
                    expected_current_status=from_state,
                )
                if not apply_result.get("success"):
                    apply_span.set_attribute("governor.apply_success", False)
                    if apply_result.get("error_code") == "STATE_CONFLICT":
                        return _error_response(
                            "STATE_CONFLICT",
                            (
                                "Task state changed concurrently during transition. "
                                f"Expected '{from_state}', found '{apply_result.get('actual_current_status')}'."
                            ),
                            from_state=from_state,
                            to_state=target_state,
                        )
                    if apply_result.get("error_code") == "EVENT_WRITE_FAILED":
                        return _error_response(
                            "EVENT_WRITE_FAILED",
                            "Transition event persistence failed; transition aborted.",
                            from_state=from_state,
                            to_state=target_state,
                        )
                    return _error_response("CRUD_FAILED", f"Backend update failed: {apply_result}")
                apply_span.set_attribute("governor.apply_success", True)
            except Exception as e:
                apply_span.record_exception(e)
                apply_span.set_attribute("governor.apply_success", False)
                logger.error(f"Atomic transition apply failed: {e}", exc_info=True)
                return _error_response("CRUD_FAILED", f"Transition apply failed: {e}")

        # 10. Fire post-transition events
        with self._tracer.start_as_current_span("governor.fire_callbacks") as cb_span:
            updated_task = task
            try:
                updated_task_data = await self._backend.get_task(task_id)
                updated_task = updated_task_data.get("task", task)
            except Exception as e:
                logger.warning(f"Failed to reload task '{task_id}' for callbacks (non-fatal): {e}")

            event_params = {**transition_params, "calling_role": effective_role}
            events_fired = await self._fire_events(transition_def, task_id, updated_task, event_params)
            response["events_fired"] = events_fired
            cb_span.set_attribute("governor.events_fired_count", len(events_fired))

        _span.set_attribute("governor.result", overall_result)
        _span.set_attribute("governor.from_state", from_state)
        return response

    async def get_available_transitions(
        self, task_id: str, calling_role: str,
    ) -> Dict[str, Any]:
        """Return available transitions for a task and role. Async version."""
        try:
            task_data = await self._backend.get_task(task_id)
        except ValueError as e:
            return {"error": "TASK_NOT_FOUND", "message": str(e)}
        except Exception as e:
            logger.error(f"Backend read failed for task '{task_id}': {e}", exc_info=True)
            return {"error": "BACKEND_ERROR", "message": f"Backend read failed: {e}"}

        task = task_data["task"]
        current_state = _normalize_state(task.get("status"))
        effective_role = self._normalize_calling_role(calling_role)

        all_transitions = self._get_all_transitions_from(current_state)
        ctx = GuardContext(task_id, task_data, backend=self._backend)

        transitions_out = []
        for tdef in all_transitions:
            role_authorized = effective_role in tdef.get("allowed_roles", [])
            guards_met = 0
            guards_total = len(tdef.get("guards", []))
            guards_missing = []
            guard_warnings = []

            for guard_ref in tdef.get("guards", []):
                try:
                    guard_id, guard_fn = self._resolve_guard_instance(guard_ref)
                except ValueError as e:
                    guard_id = (
                        guard_ref
                        if isinstance(guard_ref, str)
                        else str((guard_ref or {}).get("guard_id") or "UNKNOWN")
                    )
                    guards_missing.append(
                        {
                            "guard_id": guard_id,
                            "reason": str(e),
                            "fix_hint": "Register/import the guard implementation before engine initialization.",
                        }
                    )
                    continue
                try:
                    result = guard_fn(ctx)
                except Exception as e:
                    result = GuardResult(guard_id, False, f"Guard error: {e}")

                if result.passed:
                    guards_met += 1
                    if result.warning:
                        guard_warnings.append({
                            "guard_id": result.guard_id,
                            "reason": result.reason,
                            "fix_hint": result.fix_hint,
                        })
                else:
                    guards_missing.append({
                        "guard_id": result.guard_id,
                        "reason": result.reason,
                        "fix_hint": result.fix_hint,
                    })

            guard_mode = tdef.get("guard_mode", "AND").upper()
            if guard_mode == "OR" and guards_total > 0:
                guards_satisfied = guards_met >= 1
            else:
                guards_satisfied = guards_met == guards_total

            transitions_out.append({
                "transition_id": tdef["id"],
                "target_state": tdef["to_state"],
                "description": tdef.get("description", ""),
                "allowed_roles": tdef.get("allowed_roles", []),
                "role_authorized": role_authorized,
                "guards_total": guards_total,
                "guards_met": guards_met,
                "guards_missing": guards_missing,
                "guard_warnings": guard_warnings,
                "guard_mode": guard_mode,
                "warnings_count": len(guard_warnings),
                "ready": role_authorized and guards_satisfied,
            })

        return {
            "task_id": task_id,
            "current_state": current_state,
            "transitions": transitions_out,
        }
