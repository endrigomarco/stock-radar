from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from stock_radar.app import create_app
from stock_radar.settings import Settings


def main() -> None:
    settings = Settings.from_environment()
    reader = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}
    collector = {"Authorization": f"Bearer {settings.collector_token.get_secret_value()}"}
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        def call(tool, arguments, headers=reader):
            response = client.post("/mcp", headers={**headers, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})
            assert response.status_code == 200, response.text
            return response.json()["result"]

        assert client.post("/mcp", json={}).status_code == 401
        mcp_headers = {**reader, "Accept": "application/json, text/event-stream"}
        initialized = client.post("/mcp", headers=mcp_headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "synthetic-check", "version": "1"}}})
        assert initialized.status_code == 200, initialized.text
        listed = client.post("/mcp", headers=mcp_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
        assert {item["name"] for item in listed} == {"list_sources", "register_source", "register_collection", "get_collection", "list_signals", "service_status", "data_quality_report", "list_tracking_runs", "list_latest_quotes", "list_trigger_events", "cancel_tracking_run"}
        assert call("register_source", {"request": {"code": "forbidden", "name": "Forbidden"}})["isError"]
        source_request = {"code": "tradingview", "name": "TradingView"}
        response = client.post("/v1/sources", headers=collector, json=source_request)
        assert response.status_code == 200, response.text
        source = response.json()
        assert call("register_source", {"request": source_request}, collector)["structuredContent"]["id"] == source["id"]
        assert client.post("/v1/sources", headers=collector, json={**source_request, "name": "Changed"}).status_code == 409
        now = datetime.now(timezone.utc).isoformat()
        row = {"exchange": "SYNTH", "symbol": "TEST1", "currency": "BRL", "source_symbol": "SYNTH:TEST1", "signal_kind": "analyst_consensus", "original_rating": "Viés de alta forte", "observed_price": "10.25", "daily_change_percent": "-2.5", "observed_at": now}
        payload = {"client_collection_id": str(uuid4()), "source_id": source["id"], "source_url": "https://example.invalid/synthetic", "observed_at": now, "market_session_date": now[:10], "status": "partial", "schema_version": 2, "rows_examined": 5, "observations": [row, {**row, "symbol": "TEST2", "original_rating": "Strong Buy", "observed_price": None}, {**row, "symbol": "TEST3"}]}
        response = client.post("/v1/collections", headers=collector, json=payload)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["observation_count"] == 3 and receipt["eligible_count"] == 3 and receipt["incomplete_count"] == 1
        assert receipt["rows_examined"] == 5 and receipt["source_total"] is None
        replay = call("register_collection", {"request": payload}, collector)
        assert replay["structuredContent"]["duplicate"] and replay["structuredContent"]["id"] == receipt["id"], replay
        assert call("get_collection", {"collection_id": receipt["id"]})["structuredContent"]["observation_count"] == 3
        assert client.post("/v1/collections", headers=reader, json=payload).status_code == 403
        conflict = {**payload, "status": "complete"}
        assert client.post("/v1/collections", headers=collector, json=conflict).status_code == 409
        invalid = {**payload, "observations": [row, row]}
        assert client.post("/v1/collections", headers=collector, json=invalid).status_code == 422
        assert client.post("/v1/collections", headers=collector, json={**payload, "source_total": 2147483648}).status_code == 422
        invalid = deepcopy(payload)
        invalid["observations"][0]["observed_at"] = "2026-10-07T12:00:00"
        assert client.post("/v1/collections", headers=collector, json=invalid).status_code == 422
        rollback = {**payload, "client_collection_id": str(uuid4()), "observations": [{**row, "currency": "USD"}]}
        assert client.post("/v1/collections", headers=collector, json=rollback).status_code == 409
        rollback["observations"] = [row]
        assert client.post("/v1/collections", headers=collector, json=rollback).status_code == 200
        concurrent = {**payload, "client_collection_id": str(uuid4())}
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: client.post("/v1/collections", headers=collector, json=concurrent), range(2)))
        assert all(item.status_code == 200 for item in responses), [item.text for item in responses]
        assert sorted(item.json()["duplicate"] for item in responses) == [False, True]
        signals = call("list_signals", {"query": {"collection_id": receipt["id"], "eligible_only": True}})["structuredContent"]
        assert len(signals["items"]) == 3 and "10.25000000" in {item["observed_price"] for item in signals["items"]}
        assert client.get("/v1/collections/" + str(uuid4()), headers=reader).status_code == 404
        assert client.get("/v1/data-quality?days=32", headers=reader).status_code == 422
        quality = call("data_quality_report", {"query": {"source_id": source["id"]}})["structuredContent"]
        assert quality["collections"] == 3 and quality["incomplete_observations"] == 2, quality
        assert not quality["price_coverage_assessed"]
        assert "collections" in call("service_status", {})["structuredContent"]["capabilities"]
        assert len(call("list_sources", {"query": {}})["structuredContent"]["items"]) == 1
        assert client.post("/v1/collections", headers=collector, content=b"x" * 1048577).status_code == 413
    engine = create_engine(settings.database_url(write=True))
    for statement in ["DELETE FROM collection_runs", "SELECT * FROM webhook_receipts"]:
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except DBAPIError as error:
            assert error.orig.sqlstate == "42501"
        else:
            raise AssertionError("Collector exceeded database grants")
    engine.dispose()
    print("REST and MCP workflow checks passed: permissions, normalization, atomicity, retries, concurrency, queries and bounds.")


if __name__ == "__main__":
    main()
