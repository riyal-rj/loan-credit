from __future__ import annotations

import json

from finassist.bootstrap.logging import _redact_sensitive_fields, configure_logging, get_logger
from finassist.bootstrap.settings import Settings


def test_redact_sensitive_fields_masks_known_keys() -> None:
    event_dict = {
        "event": "user.login",
        "password": "hunter2",
        "api_key": "sk-abc123",
        "safe_field": "keep-me",
    }

    result = _redact_sensitive_fields(None, "info", event_dict)

    assert result["password"] == "***REDACTED***"
    assert result["api_key"] == "***REDACTED***"
    assert result["safe_field"] == "keep-me"


def test_configure_logging_emits_valid_json_with_required_fields(capsys: object) -> None:
    settings = Settings(
        environment="local",
        service_name="finassist-test",
        service_version="9.9.9",
        log_format="json",
    )
    configure_logging(settings)
    logger = get_logger("test.logger")

    logger.info("phase1a.test_event", operation="unit_test")

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    line = next(ln for ln in captured.out.splitlines() if "phase1a.test_event" in ln)
    payload = json.loads(line)

    assert payload["event"] == "phase1a.test_event"
    assert payload["service"] == "finassist-test"
    assert payload["environment"] == "local"
    assert payload["version"] == "9.9.9"
    assert payload["operation"] == "unit_test"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_configure_logging_redacts_sensitive_field_end_to_end(capsys: object) -> None:
    settings = Settings(environment="local", service_name="finassist-test", log_format="json")
    configure_logging(settings)
    logger = get_logger("test.logger")

    logger.info("phase1a.sensitive_event", password="hunter2")

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    line = next(ln for ln in captured.out.splitlines() if "phase1a.sensitive_event" in ln)
    payload = json.loads(line)

    assert payload["password"] == "***REDACTED***"
    assert "hunter2" not in captured.out
