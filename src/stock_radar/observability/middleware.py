import logging
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse

from stock_radar.observability.logging import emit, request_id


def route_name(scope) -> str:
    if scope["path"] == "/mcp":
        return "/mcp"
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path or "unmatched"
    return "unmatched"


class TelemetryBoundary:
    def __init__(self, app, telemetry):
        self.app = app
        self.telemetry = telemetry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identity = str(uuid4())
        token = request_id.set(identity)
        scope["headers"] = [(key, value) for key, value in scope["headers"] if key.lower() != b"x-stock-radar-request-id"] + [(b"x-stock-radar-request-id", identity.encode())]
        start = perf_counter()
        status = 500
        started = False
        finished = False
        method = scope["method"] if scope["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} else "OTHER"

        def complete():
            nonlocal finished
            if finished:
                return
            finished = True
            elapsed = perf_counter() - start
            route = route_name(scope)
            self.telemetry.requests.labels(method, route, str(status)).inc()
            self.telemetry.duration.labels(method, route).observe(elapsed)
            if route not in {"/health/live", "/metrics"} or status >= 400:
                emit("http_request", logging.WARNING if status >= 400 else logging.INFO,
                     method=method, route=route, status=status, duration_ms=round(elapsed * 1000, 3))

        async def observed_send(message):
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", identity.encode())]}
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                complete()

        try:
            await self.app(scope, receive, observed_send)
        except Exception as error:
            error_id = self.telemetry.error(error, "http", route=route_name(scope), phase="after_response" if started else "before_response")
            if not started:
                await JSONResponse({"error": {"code": "internal_error"}}, status_code=500, headers={"X-Error-ID": error_id})(scope, receive, observed_send)
            elif not finished:
                await observed_send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            request_id.reset(token)
