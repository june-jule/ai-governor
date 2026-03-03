"""Optional OpenTelemetry integration for Governor.

Provides a thin wrapper that is a no-op when ``opentelemetry`` is not
installed. Import and use :func:`get_tracer` to create spans around
guard evaluation and transition execution without adding a hard
dependency.

Usage::

    from governor.engine.telemetry import get_tracer

    tracer = get_tracer()
    with tracer.start_as_current_span("my_operation"):
        ...

When ``opentelemetry-api`` is installed, spans are emitted to the
configured exporter.  Otherwise all calls are silently ignored.
"""

from contextlib import contextmanager
from typing import Any, Optional

try:
    from opentelemetry import trace as _otel_trace  # type: ignore[import-untyped]

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


class _NoOpSpan:
    """Minimal stand-in when OpenTelemetry is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        pass

    def record_exception(self, exception: BaseException, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Minimal tracer stand-in when OpenTelemetry is not installed."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any):  # type: ignore[override]
        yield _NoOpSpan()


_TRACER_NAME = "governor.engine"


def get_tracer(name: Optional[str] = None) -> Any:
    """Return an OpenTelemetry ``Tracer`` or a silent no-op equivalent.

    Args:
        name: Tracer instrumentation name.  Defaults to ``governor.engine``.
    """
    if _HAS_OTEL:
        return _otel_trace.get_tracer(name or _TRACER_NAME)
    return _NoOpTracer()


def otel_available() -> bool:
    """Return True if OpenTelemetry API is installed."""
    return _HAS_OTEL
