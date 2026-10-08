from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from stock_radar.app import create_app
from stock_radar.observability.logging import JsonFormatter, SharedRotatingHandler, configure_logging, emit
from stock_radar.observability.middleware import TelemetryBoundary
from stock_radar.observability.telemetry import Telemetry
from stock_radar.services.sources import SourceService
from stock_radar.services.webhooks import WebhookService, process_receipt
from stock_radar.settings import Settings


def main() -> None:
    secret = "SENSITIVE_TEST_MARKER_DO_NOT_LOG"
    settings = Settings.from_environment()
    reader = {"Authorization": "Bearer " + settings.reader_token.get_secret_value()}
    with TemporaryDirectory() as directory:
        configured = settings.model_copy(update={"log_directory": directory})
        app = create_app(configured)
        with TestClient(app, base_url="http://localhost:8000") as client:
            response = client.get("/v1/sources", headers=reader)
            UUID(response.headers["x-request-id"])
            assert client.get("/metrics").status_code == 401
            with patch.object(SourceService, "list_sources", side_effect=RuntimeError(secret)):
                response = client.get("/v1/sources?code=" + secret, headers={**reader, "X-Request-ID": secret, "X-Stock-Radar-Request-ID": secret})
                assert response.status_code == 500 and response.json() == {"error": {"code": "internal_error"}}
                error_id = response.headers["x-error-id"]
                failed_request = response.headers["x-request-id"]
                UUID(error_id)
                assert secret not in response.text and failed_request != secret
                mcp = client.post("/mcp", headers={**reader, "Accept": "application/json, text/event-stream", "X-Stock-Radar-Request-ID": secret}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_sources", "arguments": {"query": {}}}})
                result = mcp.json()["result"]
                assert result["isError"] and "internal_error" in str(result)
                assert mcp.headers["x-request-id"] in str(result), result
                assert secret not in mcp.text
            with patch.object(SourceService, "list_sources", side_effect=SQLAlchemyError(secret)):
                response = client.get("/v1/sources", headers=reader)
                assert response.status_code == 503 and response.headers["x-error-id"]
            with ThreadPoolExecutor(max_workers=4) as executor:
                responses = list(executor.map(lambda _: client.get("/v1/sources", headers=reader), range(8)))
            assert len({item.headers["x-request-id"] for item in responses}) == 8
            for _ in range(3):
                client.get("/v1/collections/" + str(uuid4()), headers=reader)
            receipt_id = uuid4()
            with patch.object(WebhookService, "process", side_effect=RuntimeError(secret)):
                assert not process_receipt(None, receipt_id, app.state.telemetry)
            metrics = client.get("/metrics", headers=reader)
            assert metrics.status_code == 200
            assert 'stock_radar_mcp_calls_total{outcome="error",tool="list_sources"} 1.0' in metrics.text
            assert 'stock_radar_errors_total{component="webhook"} 1.0' in metrics.text
            assert 'route="/v1/collections/{collection_id}"' in metrics.text
            assert secret not in metrics.text and failed_request not in metrics.text
            with patch("stock_radar.observability.logging.SharedRotatingHandler._open", side_effect=OSError(secret)):
                assert client.get("/v1/sources", headers=reader).status_code == 200
        telemetry = Telemetry()

        async def interrupted(scope, receive, send):
            await send({"type": "http.response.start", "status": 202, "headers": []})
            await send({"type": "http.response.body", "body": b"accepted"})
            raise RuntimeError(secret)

        boundary_client = TestClient(TelemetryBoundary(interrupted, telemetry))
        response = boundary_client.get("/" + secret)
        assert response.status_code == 202 and response.text == "accepted"
        boundary_client.close()
        configure_logging(directory)
        emit("test_logger_reopened")
        records = [json.loads(line) for line in (Path(directory) / "events.jsonl").read_text().splitlines()]
        error = next(item for item in records if item.get("error_id") == error_id)
        assert error["request_id"] == failed_request and error["frames"]
        assert "fingerprint" in error and "message" not in error
        assert any(item.get("request_id") == mcp.headers["x-request-id"] and item.get("component") == "mcp" for item in records)
        assert any(item.get("receipt_id") == str(receipt_id) and item.get("component") == "webhook" for item in records)
        assert any(item.get("phase") == "after_response" for item in records)
        retained = (Path(directory) / "events.jsonl").read_text()
        for private in [secret, settings.reader_token.get_secret_value(), settings.database_password.get_secret_value()]:
            assert private not in retained
        result = subprocess.run([sys.executable, "-m", "stock_radar.observability.query", "--id", error_id], env={**os.environ, "LOG_DIRECTORY": directory}, capture_output=True, text=True, check=True)
        assert error_id in result.stdout and secret not in result.stdout
        rotation = Path(directory) / "rotation"
        rotation.mkdir()
        handlers = [SharedRotatingHandler(rotation / "events.jsonl", maxBytes=600, backupCount=2, delay=True) for _ in range(2)]
        for handler in handlers:
            handler.setFormatter(JsonFormatter())

        def write(index):
            record = logging.LogRecord("rotation", logging.ERROR, __file__, 1, "ignored", (), None)
            record.event_data = {"event": "rotation_check", "index": index}
            handlers[index % 2].handle(record)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(write, range(30)))
        for handler in handlers:
            handler.close()
        assert (rotation / "events.jsonl.2").exists()
        assert not (rotation / "events.jsonl.3").exists()
        for path in [rotation / "events.jsonl", rotation / "events.jsonl.1", rotation / "events.jsonl.2"]:
            assert all(json.loads(line)["event"] == "rotation_check" for line in path.read_text().splitlines())
        configure_logging(None)
    print("Observability checks passed: safe HTTP/MCP boundaries, correlation, concurrent isolation, metrics, webhook errors, durable lookup and log-storage failure isolation.")


if __name__ == "__main__":
    main()
