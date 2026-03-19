"""OpenTelemetry infrastructure for MCP servers — traces, metrics, and logs to SigNoz."""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any, TypeVar

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

F = TypeVar("F", bound=Callable[..., Any])

_DEFAULT_ENDPOINT = "http://signoz.local:4317"
_initialized = False


def _is_enabled() -> bool:
    return os.environ.get("ORACLE_TELEMETRY_ENABLED", "true").lower() != "false"


def init_telemetry(service_name: str) -> None:
    global _initialized
    if _initialized or not _is_enabled():
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", _DEFAULT_ENDPOINT)
    resource = Resource.create({"service.name": service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, insecure=True),
                export_interval_millis=30000,
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)

    _initialized = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    return metrics.get_meter(name)


def trace_tool(tool_name: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer("mcp.tools")
            with tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
                span.set_attribute("mcp.tool.name", tool_name)
                try:
                    result = func(*args, **kwargs)
                    if isinstance(result, str):
                        span.set_attribute("mcp.tool.result_length", len(result))
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator
