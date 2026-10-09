import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import anyio
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response

CHECKS_DIRECTORY = Path(__file__).resolve().parent
PLUGIN_DIRECTORY = Path(os.environ.get("BRIDGE_PLUGIN_DIRECTORY", "/plugin"))
BRIDGE_DIRECTORY = PLUGIN_DIRECTORY / "mcp"
SYNTHETIC_TOKEN = "synthetic-reader-token-for-bridge-checks-only"
WRONG_TOKEN = "synthetic-wrong-token-for-bridge-checks-only"

sys.path.insert(0, str(BRIDGE_DIRECTORY))

import bridge


class SyntheticStatus(BaseModel):
    version: str
    capabilities: list[str]


def synthetic_application(seen_authorization: list[str]):
    server = MCPServer("Synthetic Stock Radar", version="9.9.9", log_level="ERROR")

    @server.tool(description="Synthetic status with structured output.")
    def service_status() -> SyntheticStatus:
        return SyntheticStatus(version="9.9.9", capabilities=["synthetic"])

    @server.tool(description="Synthetic echo with one argument.")
    def echo(text: str) -> str:
        return f"echo:{text}"

    @server.tool(description="Synthetic tool that always fails.")
    def always_fails() -> str:
        raise ToolError("synthetic failure; request_id=synthetic")

    application = server.streamable_http_app(stateless_http=True, json_response=True)

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            authorization = headers.get(b"authorization", b"").decode("latin1")
            seen_authorization.append(authorization)
            if authorization != f"Bearer {SYNTHETIC_TOKEN}":
                await JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)(scope, receive, send)
                return
        await application(scope, receive, send)

    return guarded


def redirecting_application(location: str):
    async def application(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                    continue
                await send({"type": "lifespan.shutdown.complete"})
                return
        await Response(status_code=307, headers={"Location": location})(scope, receive, send)

    return application


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def running(application):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "synthetic server did not start"
        time.sleep(0.05)
    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@asynccontextmanager
async def bridged(endpoint: str, token: str, error_log):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-I", "-B", str(CHECKS_DIRECTORY / "bridge_harness.py")],
        env={
            "BRIDGE_TEST_PLUGIN_DIRECTORY": str(BRIDGE_DIRECTORY),
            "BRIDGE_TEST_ENDPOINT": endpoint,
            "BRIDGE_TEST_TOKEN": token,
        },
    )
    async with stdio_client(parameters, errlog=error_log) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=30) as session:
            await session.initialize()
            yield session


async def expect_failure(session: ClientSession) -> None:
    for operation in (session.list_tools, lambda: session.call_tool("service_status", {})):
        try:
            result = await operation()
        except MCPError as error:
            assert error.code == bridge.UNAVAILABLE_CODE, error
            continue
        raise AssertionError(f"transport failure became a result: {result}")


async def check_forwarding(endpoint: str, error_log) -> None:
    async with bridge.remote_session(endpoint, SYNTHETIC_TOKEN) as direct:
        expected = await direct.list_tools()
    async with bridged(endpoint, SYNTHETIC_TOKEN, error_log) as session:
        listed = await session.list_tools()
        assert [tool.model_dump() for tool in listed.tools] == [tool.model_dump() for tool in expected.tools]
        assert {tool.name for tool in listed.tools} == {"service_status", "echo", "always_fails"}
        status_tool = next(tool for tool in listed.tools if tool.name == "service_status")
        assert status_tool.description == "Synthetic status with structured output."
        assert status_tool.output_schema is not None
        status = await session.call_tool("service_status", {})
        assert status.is_error is False
        assert status.structured_content == {"version": "9.9.9", "capabilities": ["synthetic"]}
        assert json.loads(status.content[0].text) == status.structured_content
        echoed = await session.call_tool("echo", {"text": "synthetic"})
        assert echoed.is_error is False and echoed.content[0].text == "echo:synthetic"
        failed = await session.call_tool("always_fails", {})
        assert failed.is_error is True
        assert "synthetic failure; request_id=synthetic" in failed.content[0].text, failed
        invalid = await session.call_tool("echo", {})
        assert invalid.is_error is True
        missing = await session.call_tool("not_a_tool", {})
        assert missing.is_error is True


async def check_failures(endpoint: str, closed_endpoint: str, redirect_endpoint: str, error_log) -> None:
    async with bridged(endpoint, WRONG_TOKEN, error_log) as session:
        await expect_failure(session)
    async with bridged(closed_endpoint, SYNTHETIC_TOKEN, error_log) as session:
        await expect_failure(session)
    async with bridged(redirect_endpoint, SYNTHETIC_TOKEN, error_log) as session:
        await expect_failure(session)


def check_configuration() -> None:
    assert bridge.validate_endpoint(bridge.ENDPOINT) == bridge.ENDPOINT
    for rejected in ("http://synthetic.example/mcp", "https://user:secret@synthetic.example/mcp", "synthetic.example/mcp", ""):
        try:
            bridge.validate_endpoint(rejected)
        except bridge.BridgeConfigurationError:
            continue
        raise AssertionError(f"accepted endpoint {rejected}")
    original = bridge.SECURITY_COMMAND
    bridge.SECURITY_COMMAND = "/nonexistent/security"
    try:
        bridge.read_token()
    except bridge.BridgeConfigurationError:
        pass
    else:
        raise AssertionError("missing Keychain command was accepted")
    finally:
        bridge.SECURITY_COMMAND = original
    manifest = json.loads((PLUGIN_DIRECTORY / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["version"] == bridge.BRIDGE_VERSION
    server = manifest["mcpServers"]["stock-radar"]
    assert server == {"command": "/bin/sh", "args": ["${CLAUDE_PLUGIN_ROOT}/mcp/start.sh"]}
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(BRIDGE_DIRECTORY / "bridge.py"), "--check"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == bridge.EXIT_CONFIGURATION, completed
    assert completed.stdout == ""
    assert "Keychain" in completed.stderr


def main() -> None:
    check_configuration()
    seen_authorization: list[str] = []
    foreign_authorization: list[str] = []
    with tempfile.TemporaryFile(mode="w+") as error_log:
        with running(synthetic_application(seen_authorization)) as port, running(synthetic_application(foreign_authorization)) as foreign_port:
            endpoint = f"http://127.0.0.1:{port}/mcp"
            with running(redirecting_application(f"http://127.0.0.1:{foreign_port}/mcp")) as redirect_port:
                anyio.run(check_forwarding, endpoint, error_log)
                anyio.run(check_failures, endpoint, f"http://127.0.0.1:{free_port()}/mcp", f"http://127.0.0.1:{redirect_port}/mcp", error_log)
        error_log.seek(0)
        diagnostics = error_log.read()
    assert f"Bearer {SYNTHETIC_TOKEN}" in seen_authorization
    assert foreign_authorization == [], "credentials followed a redirect to another origin"
    assert SYNTHETIC_TOKEN not in diagnostics and WRONG_TOKEN not in diagnostics and "Bearer" not in diagnostics
    assert "request failed" in diagnostics
    print("Bridge checks passed: discovery, forwarding, tool errors, authentication, transport, redirects and diagnostics.")


if __name__ == "__main__":
    main()
