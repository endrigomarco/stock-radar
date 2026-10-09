from fastapi.testclient import TestClient
from pydantic import ValidationError

from stock_radar.app import create_app
from stock_radar.settings import Settings

ALLOWED_HOST = "private-proxy.synthetic.example:8444"
READER_TOKEN = "synthetic-reader-token-for-transport-checks-only"
INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "synthetic-check", "version": "1"}}}


def settings(allowed_hosts: str) -> Settings:
    return Settings(
        webhook_token="synthetic-webhook-token-for-transport-checks-only",
        webhook_password="synthetic-password-for-transport-checks-only",
        reader_token=READER_TOKEN,
        collector_token="synthetic-collector-token-for-transport-checks-only",
        collector_password="synthetic-password-for-transport-checks-only",
        database_password="synthetic-password-for-transport-checks-only",
        database_name="synthetic",
        mcp_allowed_hosts=allowed_hosts,
    )


def initialize(client: TestClient, host: str | None, token: str | None = READER_TOKEN, origin: str | None = None) -> int:
    headers = {"Accept": "application/json, text/event-stream"}
    if host is not None:
        headers["Host"] = host
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    return client.post("/mcp", headers=headers, json=INITIALIZE).status_code


def main() -> None:
    with TestClient(create_app(settings(f" {ALLOWED_HOST.upper()} ,")), base_url="http://localhost:8000") as client:
        assert initialize(client, ALLOWED_HOST) == 200
        assert initialize(client, None) == 200
        assert initialize(client, "127.0.0.1:8001") == 200
        assert initialize(client, "private-proxy.synthetic.example") == 421
        assert initialize(client, "private-proxy.synthetic.example:9999") == 421
        assert initialize(client, "other.synthetic.example:8444") == 421
        assert initialize(client, f"evil.{ALLOWED_HOST}") == 421
        assert initialize(client, ALLOWED_HOST, token=None) == 401
        assert initialize(client, ALLOWED_HOST, token="synthetic-wrong-token-for-transport-checks-only") == 401
        assert initialize(client, "other.synthetic.example:8444", token=None) == 401
        assert initialize(client, ALLOWED_HOST, origin=f"https://{ALLOWED_HOST}") == 403
        assert initialize(client, ALLOWED_HOST, origin="http://localhost:8000") == 200
    with TestClient(create_app(settings("")), base_url="http://localhost:8000") as client:
        assert initialize(client, None) == 200
        assert initialize(client, ALLOWED_HOST) == 421
    for rejected in ("*", "*.synthetic.example:8444", "private-proxy.synthetic.example:*", "https://private-proxy.synthetic.example", "host name:1", ",".join(f"host{index}.example" for index in range(9))):
        try:
            settings(rejected)
        except ValidationError:
            continue
        raise AssertionError(f"accepted {rejected}")
    print("MCP transport host checks passed.")


if __name__ == "__main__":
    main()
