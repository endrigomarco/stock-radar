from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from stock_radar.controllers import collections, health, metrics, sources, status, tracking, webhooks
from stock_radar.mcp import create_mcp
from stock_radar.middleware import RequestBoundary
from stock_radar.services.errors import ServiceError
from stock_radar.settings import Settings

from stock_radar.observability.logging import configure_logging, emit
from stock_radar.observability.middleware import TelemetryBoundary, route_name
from stock_radar.observability.telemetry import Telemetry


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    configure_logging(settings.log_directory)
    telemetry = Telemetry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = create_engine(
            settings.database_url(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=0,
            pool_timeout=5,
            hide_parameters=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        app.state.collector_engine = create_engine(
            settings.database_url(write=True), pool_pre_ping=True, pool_size=3, max_overflow=0,
            pool_timeout=5, hide_parameters=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        app.state.webhook_engine = create_engine(
            settings.webhook_database_url(), pool_pre_ping=True, pool_size=3, max_overflow=0,
            pool_timeout=0.5, hide_parameters=True,
            connect_args={"connect_timeout": 1, "options": "-c statement_timeout=1000 -c lock_timeout=500"},
        )
        try:
            async with mcp.session_manager.run():
                emit("application_started")
                yield
        finally:
            app.state.engine.dispose()
            app.state.collector_engine.dispose()
            app.state.webhook_engine.dispose()
            emit("application_stopped")

    app = FastAPI(title="Stock Radar", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.telemetry = telemetry
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(sources.router)
    app.include_router(collections.router)
    app.include_router(status.router)
    app.include_router(tracking.router)
    app.include_router(webhooks.router)
    mcp = create_mcp(app)
    app.mount("/", mcp.streamable_http_app(stateless_http=True, json_response=True))
    app.add_middleware(RequestBoundary, settings=settings)
    app.add_middleware(TelemetryBoundary, telemetry=telemetry)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError) -> JSONResponse:
        headers = {}
        if error.status_code >= 500:
            headers["X-Error-ID"] = telemetry.error(error, "http", route=route_name(request.scope))
        return JSONResponse(status_code=error.status_code, content={"error": {"code": error.code}}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(part) for part in item["loc"]), "type": item["type"]} for item in error.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "details": details}})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        identity = telemetry.error(error, "http", route=route_name(request.scope))
        return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable"}}, headers={"X-Error-ID": identity})

    return app
