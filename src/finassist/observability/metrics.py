"""Prometheus metrics registry and Phase 1A metric definitions.

Per docs/adr/0007, Prometheus scrapes `/metrics` directly rather than going through the
OpenTelemetry metrics SDK. Labels are deliberately low-cardinality (§19.3): no application ID,
document ID, user ID, or free-form error text may ever become a label value here.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS_TOTAL = Counter(
    "finassist_http_requests_total",
    "Total HTTP requests handled by the API service.",
    labelnames=("method", "route", "status_code"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "finassist_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

HTTP_REQUESTS_IN_FLIGHT = Gauge(
    "finassist_http_requests_in_flight",
    "Number of HTTP requests currently being handled by the API service.",
    registry=REGISTRY,
)

READINESS_CHECK_FAILURES_TOTAL = Counter(
    "finassist_readiness_check_failures_total",
    "Count of failed readiness dependency checks, by dependency name.",
    labelnames=("dependency",),
    registry=REGISTRY,
)
