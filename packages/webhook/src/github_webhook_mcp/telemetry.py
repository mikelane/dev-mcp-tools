"""Webhook-specific OpenTelemetry helpers built on mcp_shared.telemetry."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, TypeVar

from mcp_shared.telemetry import get_meter, get_tracer, init_telemetry
from opentelemetry import trace

F = TypeVar("F", bound=Callable[..., Any])

SERVICE_NAME = "webhook-mcp"

_meter = get_meter(SERVICE_NAME)

tool_calls_counter = _meter.create_counter(
    "webhook.tool.calls",
    description="Number of webhook MCP tool invocations",
)

events_received_counter = _meter.create_counter(
    "webhook.events.received",
    description="Number of webhook events received via SSE",
)

query_results_counter = _meter.create_counter(
    "webhook.events.query_results",
    description="Number of events returned per query",
)


def trace_tool_async(tool_name: str) -> Callable[[F], F]:
    """Async-aware version of trace_tool for webhook MCP tool functions."""

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer("mcp.tools")
                with tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
                    span.set_attribute("mcp.tool.name", tool_name)
                    tool_calls_counter.add(1, {"tool.name": tool_name})
                    try:
                        result = await func(*args, **kwargs)
                        if isinstance(result, str):
                            span.set_attribute("mcp.tool.result_length", len(result))
                        return result
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(trace.StatusCode.ERROR, str(exc))
                        raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer("mcp.tools")
            with tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
                span.set_attribute("mcp.tool.name", tool_name)
                tool_calls_counter.add(1, {"tool.name": tool_name})
                try:
                    result = func(*args, **kwargs)
                    if isinstance(result, str):
                        span.set_attribute("mcp.tool.result_length", len(result))
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    raise

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def init_webhook_telemetry() -> None:
    """Initialize OpenTelemetry for the webhook-mcp service."""
    init_telemetry(SERVICE_NAME)
