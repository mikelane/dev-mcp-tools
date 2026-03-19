"""Tests for OpenTelemetry infrastructure."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from mcp_shared.telemetry import (
    _is_enabled,
    get_meter,
    get_tracer,
    init_telemetry,
    trace_tool,
)


class TestTelemetryEnabled:
    def test_returns_true_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _is_enabled() is True

    def test_returns_false_when_disabled(self) -> None:
        with patch.dict(os.environ, {"ORACLE_TELEMETRY_ENABLED": "false"}):
            assert _is_enabled() is False

    def test_is_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"ORACLE_TELEMETRY_ENABLED": "FALSE"}):
            assert _is_enabled() is False


class TestGetTracer:
    def test_returns_a_tracer(self) -> None:
        tracer = get_tracer("test")
        assert tracer is not None


class TestGetMeter:
    def test_returns_a_meter(self) -> None:
        meter = get_meter("test")
        assert meter is not None


class TestTraceTool:
    def test_wraps_function_and_returns_result(self) -> None:
        @trace_tool("test_tool")
        def my_tool(x: int) -> str:
            return f"result-{x}"

        assert my_tool(42) == "result-42"

    def test_preserves_function_name(self) -> None:
        @trace_tool("test_tool")
        def my_tool() -> str:
            return "ok"

        assert my_tool.__name__ == "my_tool"

    def test_propagates_exceptions(self) -> None:
        @trace_tool("failing_tool")
        def bad_tool() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            bad_tool()


class TestInitTelemetry:
    def test_is_idempotent(self) -> None:
        with patch.dict(os.environ, {"ORACLE_TELEMETRY_ENABLED": "false"}):
            init_telemetry("test-service")
            init_telemetry("test-service")

    def test_skips_when_disabled(self) -> None:
        with patch.dict(os.environ, {"ORACLE_TELEMETRY_ENABLED": "false"}):
            import mcp_shared.telemetry as mod

            mod._initialized = False
            init_telemetry("test-service")
            assert mod._initialized is False
