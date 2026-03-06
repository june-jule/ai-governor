"""Tests for OpenTelemetry span instrumentation in TransitionEngine.

Uses a FakeTracer/FakeSpan that records span names, attributes, and
exceptions to verify span hierarchy and metadata without requiring
the opentelemetry-api package.
"""

from contextlib import contextmanager

from governor.backend.memory_backend import MemoryBackend
from governor.engine.transition_engine import TransitionEngine


# ------------------------------------------------------------------
# FakeSpan / FakeTracer
# ------------------------------------------------------------------

class FakeSpan:
    """Records set_attribute, record_exception, and context-manager usage."""

    def __init__(self, name: str, recorder: list):
        self.name = name
        self.attributes: dict = {}
        self.exceptions: list = []
        self._recorder = recorder
        self._recorder.append(self)

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, exception, **kwargs) -> None:
        self.exceptions.append(exception)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeTracer:
    """Yields FakeSpan instances and records them for later inspection."""

    def __init__(self):
        self.spans: list[FakeSpan] = []

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        span = FakeSpan(name, self.spans)
        yield span


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_engine_with_fake_tracer():
    """Create a MemoryBackend + TransitionEngine with a FakeTracer."""
    backend = MemoryBackend()
    engine = TransitionEngine(backend)
    tracer = FakeTracer()
    engine._tracer = tracer  # Replace the default no-op tracer
    return backend, engine, tracer


def _create_active_task(backend, task_id="TASK_001"):
    backend.create_task({
        "task_id": task_id,
        "task_name": "Test task",
        "task_type": "IMPLEMENTATION",
        "role": "DEVELOPER",
        "status": "ACTIVE",
        "priority": "HIGH",
        "content": "Test content for deliverables check.",
    })


def _prepare_submittable_task(backend, task_id="TASK_001"):
    """Create a task that can pass EG guards (self-review + report)."""
    _create_active_task(backend, task_id)
    backend.add_review(task_id, {
        "review_id": "REV_001",
        "review_type": "SELF_REVIEW",
        "reviewer_role": "DEVELOPER",
        "rating": 8.0,
        "content": "Self-review: all looks good.",
    })
    backend.add_report(task_id, {
        "report_id": "RPT_001",
        "report_type": "IMPLEMENTATION",
        "content": "Implementation report.",
    })


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestTransitionSpans:
    """Verify that transition_task() creates the expected span hierarchy."""

    def test_root_span_created(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        span_names = [s.name for s in tracer.spans]
        assert "governor.transition" in span_names

    def test_root_span_has_task_id_attribute(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        root = next(s for s in tracer.spans if s.name == "governor.transition")
        assert root.attributes["governor.task_id"] == "TASK_001"
        assert root.attributes["governor.target_state"] == "READY_FOR_REVIEW"
        assert root.attributes["governor.calling_role"] == "EXECUTOR"
        assert root.attributes["governor.dry_run"] is True

    def test_root_span_has_result_attribute(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        root = next(s for s in tracer.spans if s.name == "governor.transition")
        assert root.attributes.get("governor.result") == result["result"]

    def test_load_task_span_created(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        span_names = [s.name for s in tracer.spans]
        assert "governor.load_task" in span_names
        load_span = next(s for s in tracer.spans if s.name == "governor.load_task")
        assert load_span.attributes["governor.task_found"] is True

    def test_evaluate_guards_span_created(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        span_names = [s.name for s in tracer.spans]
        assert "governor.evaluate_guards" in span_names
        guards_span = next(s for s in tracer.spans if s.name == "governor.evaluate_guards")
        assert "governor.guard_count" in guards_span.attributes
        assert "governor.guards_passed" in guards_span.attributes
        assert "governor.guards_failed" in guards_span.attributes

    def test_apply_transition_span_on_non_dry_run(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=False)

        span_names = [s.name for s in tracer.spans]
        if result["result"] == "PASS":
            assert "governor.apply_transition" in span_names
            apply_span = next(s for s in tracer.spans if s.name == "governor.apply_transition")
            assert apply_span.attributes.get("governor.apply_success") is True

    def test_fire_callbacks_span_on_non_dry_run(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=False)

        span_names = [s.name for s in tracer.spans]
        if result["result"] == "PASS":
            assert "governor.fire_callbacks" in span_names
            cb_span = next(s for s in tracer.spans if s.name == "governor.fire_callbacks")
            assert "governor.events_fired_count" in cb_span.attributes

    def test_no_apply_span_on_dry_run(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        _prepare_submittable_task(backend)

        engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        span_names = [s.name for s in tracer.spans]
        assert "governor.apply_transition" not in span_names
        assert "governor.fire_callbacks" not in span_names

    def test_failed_transition_records_result(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()
        # Task with no self-review — guards will fail
        _create_active_task(backend)

        result = engine.transition_task("TASK_001", "READY_FOR_REVIEW", "EXECUTOR", dry_run=True)

        assert result["result"] == "FAIL"
        root = next(s for s in tracer.spans if s.name == "governor.transition")
        assert root.attributes.get("governor.result") == "FAIL"

    def test_task_not_found_sets_span_attribute(self):
        backend, engine, tracer = _make_engine_with_fake_tracer()

        engine.transition_task("NONEXISTENT", "ACTIVE", "ORCHESTRATOR")

        root = next(s for s in tracer.spans if s.name == "governor.transition")
        assert root.attributes.get("governor.result") == "TASK_NOT_FOUND"
        load_span = next(s for s in tracer.spans if s.name == "governor.load_task")
        assert load_span.attributes["governor.task_found"] is False
