from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util._once import Once

from finassist.bootstrap.settings import Settings
from finassist.bootstrap.telemetry import configure_telemetry, shutdown_telemetry, span


def _reset_otel_provider_guard() -> None:
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE = Once()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_otel_global_tracer_provider() -> Iterator[None]:
    """Reset OpenTelemetry's process-global tracer provider around each test.

    The stable `opentelemetry.trace` API only allows `set_tracer_provider` to succeed once per
    process by design, guarded by an internal `Once` flag (a real production process calls
    `configure_telemetry` exactly once at startup, so it never hits this guard). Resetting both
    the private global and its `Once` guard between tests is the same technique OpenTelemetry's
    own test suite uses for isolation; it has no equivalent in production code.
    """
    _reset_otel_provider_guard()
    yield
    _reset_otel_provider_guard()


def test_configure_telemetry_registers_a_tracer_provider() -> None:
    settings = Settings(environment="local", otel_console_fallback=True)

    provider = configure_telemetry(settings)

    assert trace.get_tracer_provider() is provider
    shutdown_telemetry()


def test_span_context_manager_creates_a_recorded_span() -> None:
    settings = Settings(environment="local", otel_enabled=True, otel_console_fallback=True)
    provider = configure_telemetry(settings)

    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with span("phase1a.unit_test_span", attribute_one="value"):
        pass

    finished_spans = exporter.get_finished_spans()
    assert any(s.name == "phase1a.unit_test_span" for s in finished_spans)
    matching = next(s for s in finished_spans if s.name == "phase1a.unit_test_span")
    assert matching.attributes["attribute_one"] == "value"

    shutdown_telemetry()


def test_otel_disabled_registers_provider_without_exporter() -> None:
    settings = Settings(environment="local", otel_enabled=False)

    provider = configure_telemetry(settings)

    assert trace.get_tracer_provider() is provider
    shutdown_telemetry()
