"""OpenTelemetry tracing bootstrap.

Owns only tracer-provider setup and FastAPI instrumentation for Phase 1A. Metrics are exposed
separately via `prometheus-client` (see `finassist.observability.metrics`) rather than the
OpenTelemetry metrics SDK, matching the ownership split in docs/adr/0007: Prometheus scrapes
`/metrics` directly, OpenTelemetry carries traces (and, from Phase 8 onward, logs) to the
Collector.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.trace import Tracer

from finassist.bootstrap.settings import Environment, Settings

_tracer_provider: TracerProvider | None = None


def configure_telemetry(settings: Settings) -> TracerProvider:
    """Configure and register the global OpenTelemetry tracer provider.

    Idempotent: calling this more than once (e.g. across tests) tears down and replaces the
    previously configured provider rather than stacking exporters.
    """
    global _tracer_provider

    resource = Resource.create(
        {
            SERVICE_NAME: settings.service_name,
            SERVICE_VERSION: settings.service_version,
            "deployment.environment": settings.environment.value,
        }
    )
    provider = TracerProvider(resource=resource)

    if not settings.otel_enabled:
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
        return provider

    exporter: SpanExporter
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    elif settings.otel_console_fallback and settings.environment is not Environment.PRODUCTION:
        exporter = ConsoleSpanExporter()
    else:
        # No endpoint configured and console fallback disallowed (always true in production,
        # per Settings validation): register the provider with no exporter rather than silently
        # falling back, so a missing OTLP endpoint is visibly "no traces" instead of a surprise.
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
        return provider

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider


def get_tracer(name: str) -> Tracer:
    """Return a tracer for ``name``. Prefer ``__name__`` at the call site."""
    return trace.get_tracer(name)


def shutdown_telemetry() -> None:
    """Flush and shut down the tracer provider. Call during process shutdown."""
    global _tracer_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None


@contextmanager
def span(
    name: str, tracer_name: str = __name__, **attributes: str | int | float | bool
) -> Iterator[trace.Span]:
    """Convenience context manager for a manual span with attributes set atomically."""
    tracer = get_tracer(tracer_name)
    with tracer.start_as_current_span(name) as current_span:
        for key, value in attributes.items():
            current_span.set_attribute(key, value)
        yield current_span
