import hashlib
import logging
from pathlib import Path
import traceback
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Histogram

from stock_radar.observability.logging import emit, request_id


class Telemetry:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter("stock_radar_http_requests", "Completed HTTP requests", ["method", "route", "status"], registry=self.registry)
        self.duration = Histogram("stock_radar_http_duration_seconds", "Time until HTTP response completion", ["method", "route"], registry=self.registry)
        self.errors = Counter("stock_radar_errors", "Captured operational and unexpected failures", ["component"], registry=self.registry)
        self.tools = Counter("stock_radar_mcp_calls", "MCP tool outcomes, including errors returned with HTTP 200", ["tool", "outcome"], registry=self.registry)
        self.tool_duration = Histogram("stock_radar_mcp_duration_seconds", "MCP tool execution time", ["tool"], registry=self.registry)
        self.webhooks = Counter("stock_radar_webhook_processing", "Webhook processing attempts by outcome", ["outcome"], registry=self.registry)

    def error(self, error: Exception, component: str, **fields) -> str:
        error_id = str(uuid4())
        frames = []
        for frame, line in traceback.walk_tb(error.__traceback__):
            filename = frame.f_code.co_filename
            marker = "stock_radar/"
            filename = marker + filename.split(marker, 1)[1] if marker in filename else Path(filename).name
            frames.append({"file": filename, "function": frame.f_code.co_name, "line": line})
        application_frames = [frame for frame in frames if frame["file"].startswith("stock_radar/")]
        library_frames = [frame for frame in frames if not frame["file"].startswith("stock_radar/")]
        frames = application_frames[-12:] + library_frames[-8:]
        exception_type = type(error).__name__
        fingerprint = hashlib.sha256(repr((exception_type, frames)).encode()).hexdigest()[:16]
        self.errors.labels(component).inc()
        emit("error_captured", logging.ERROR, error_id=error_id, fingerprint=fingerprint,
             component=component, exception_type=exception_type, frames=frames, **fields)
        return error_id


def correlation_id() -> str:
    return request_id.get() or str(uuid4())
