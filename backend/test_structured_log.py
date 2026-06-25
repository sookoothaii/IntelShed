"""Unit tests for structured_log module."""

import json
import unittest
from io import StringIO
from logging import StreamHandler

from structured_log import (
    get_logger,
    StructuredLogger,
    JsonFormatter,
    _redact_value,
    _redact_dict,
)


class TestStructuredLog(unittest.TestCase):
    def test_redact_sensitive_key(self):
        result = _redact_value("secret123", "api_key")
        self.assertEqual(result, "[REDACTED]")

    def test_redact_token_key(self):
        result = _redact_value("abc123", "NODE_INGEST_TOKEN")
        self.assertEqual(result, "[REDACTED]")

    def test_redact_non_sensitive_key(self):
        result = _redact_value(42, "count")
        self.assertEqual(result, 42)

    def test_redact_dict_nested(self):
        d = {"outer": {"api_key": "secret", "count": 5}}
        result = _redact_dict(d)
        self.assertEqual(result["outer"]["api_key"], "[REDACTED]")
        self.assertEqual(result["outer"]["count"], 5)

    def test_logger_returns_structured_logger(self):
        log = get_logger("test_module_1")
        self.assertIsInstance(log, StructuredLogger)

    def test_logger_info_with_kwargs(self):
        log = get_logger("test_module_2")
        # Capture output
        inner = log._logger
        stream = StringIO()
        for h in inner.handlers:
            inner.removeHandler(h)
        h = StreamHandler(stream)
        h.setFormatter(JsonFormatter())
        inner.addHandler(h)
        log.info("test_event", count=5, name="worldbase")
        output = stream.getvalue().strip()
        data = json.loads(output)
        self.assertEqual(data["msg"], "test_event")
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["name"], "worldbase")
        self.assertEqual(data["level"], "INFO")

    def test_logger_redacts_secrets(self):
        log = get_logger("test_module_3")
        inner = log._logger
        stream = StringIO()
        for h in inner.handlers:
            inner.removeHandler(h)
        h = StreamHandler(stream)
        h.setFormatter(JsonFormatter())
        inner.addHandler(h)
        log.info("auth_event", api_key="my-secret-key", token="abc123")
        output = stream.getvalue().strip()
        data = json.loads(output)
        self.assertEqual(data["api_key"], "[REDACTED]")
        self.assertEqual(data["token"], "[REDACTED]")

    def test_logger_idempotent(self):
        log1 = get_logger("test_module_4")
        log2 = get_logger("test_module_4")
        # Same inner logger, no duplicate handlers
        self.assertIs(log1._logger, log2._logger)
        self.assertEqual(len(log1._logger.handlers), 1)


if __name__ == "__main__":
    unittest.main()
