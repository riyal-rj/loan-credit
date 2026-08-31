"""Structured logging bootstrap (structlog over the standard library `logging` module).

Every log event is a JSON object (or a human-readable console renderer in local dev) carrying a
stable event name plus the fields required by the master instruction §19.1: timestamp, severity,
service, environment, version, trace/span/correlation IDs when available, and no raw sensitive
payloads. Redaction of known-sensitive field names is applied centrally here so call sites cannot
forget it.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from asgi_correlation_id.context import correlation_id
from opentelemetry import trace

from finassist.bootstrap.settings import Settings

_REDACTED = "***REDACTED***"

# Field names that must never reach a log sink in cleartext, regardless of which module emits
# them. This is a defense-in-depth backstop, not a substitute for not logging sensitive values
# in the first place.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "authorization",
        "api_key",
        "ssn",
        "national_id",
        "account_number",
        "card_number",
        "document_text",
        "prompt",
        "model_output",
    }
)


def _redact_sensitive_fields(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _inject_correlation_id(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    cid = correlation_id.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def _inject_trace_context(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging for the current process.

    Must be called exactly once, as early as possible in process startup (before any other module
    obtains a logger), so every subsequent log line -- including from third-party libraries routed
    through stdlib logging -- carries the same structured fields.
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_correlation_id,
        _inject_trace_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive_fields,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: structlog.types.Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        # `format_exc_info` above already renders exceptions to plain text for the (mandatory,
        # stdlib-integration-required) foreign_pre_chain, so ConsoleRenderer's default "pretty"
        # exception formatter has nothing left to prettify -- use the plain formatter to match
        # reality instead of letting it warn about the redundancy on every exception log.
        renderer = structlog.dev.ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    static_context = {
        "service": settings.service_name,
        "environment": settings.environment.value,
        "version": settings.service_version,
    }
    structlog.contextvars.bind_contextvars(**static_context)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog-bound logger for ``name``. Prefer ``__name__`` at the call site."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
