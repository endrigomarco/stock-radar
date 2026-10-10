import logging
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import anyio
import httpx2
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

BRIDGE_NAME = "stock-radar-bridge"
BRIDGE_VERSION = "0.6.0"
ENDPOINT = "https://private-server.tail72966f.ts.net:8444/mcp"
KEYCHAIN_SERVICE = "stock-radar-mcp"
KEYCHAIN_ACCOUNT = "reader"
SECURITY_COMMAND = "/usr/bin/security"
KEYCHAIN_TIMEOUT_SECONDS = 10
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 60.0
MAX_TOKEN_LENGTH = 512
UNAVAILABLE_CODE = -32001
EXIT_CONFIGURATION = 1
EXIT_UNAVAILABLE = 2

logger = logging.getLogger(BRIDGE_NAME)


class BridgeConfigurationError(Exception):
    pass


def validate_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise BridgeConfigurationError("The Stock Radar endpoint must be an https URL without credentials.")
    return endpoint


def read_token() -> str:
    try:
        completed = subprocess.run(
            [SECURITY_COMMAND, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BridgeConfigurationError(f"The macOS Keychain could not be read ({type(error).__name__}).") from None
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        raise BridgeConfigurationError(
            f"Keychain item '{KEYCHAIN_SERVICE}' with account '{KEYCHAIN_ACCOUNT}' was not found or is empty."
        )
    if len(token) > MAX_TOKEN_LENGTH or not token.isascii() or not token.isprintable() or " " in token:
        raise BridgeConfigurationError(f"Keychain item '{KEYCHAIN_SERVICE}' does not hold a usable token.")
    return token


def describe_failure(error: BaseException) -> str:
    leaves: list[BaseException] = []
    pending = [error]
    while pending:
        current = pending.pop()
        nested = getattr(current, "exceptions", None)
        if nested:
            pending.extend(nested)
            continue
        leaves.append(current)
    names = sorted({type(leaf).__name__ for leaf in leaves})
    statuses = sorted({str(leaf.response.status_code) for leaf in leaves if isinstance(leaf, httpx2.HTTPStatusError)})
    detail = ", ".join(names)
    if statuses:
        detail = f"{detail}; HTTP {', '.join(statuses)}"
    return detail


def unavailable(error: BaseException) -> MCPError:
    detail = describe_failure(error)
    logger.warning("Stock Radar service request failed: %s", detail)
    return MCPError(UNAVAILABLE_CODE, f"Stock Radar service is unavailable through the bridge ({detail}).")


@asynccontextmanager
async def remote_session(endpoint: str, token: str) -> AsyncIterator[ClientSession]:
    timeout = httpx2.Timeout(CONNECT_TIMEOUT_SECONDS, read=READ_TIMEOUT_SECONDS)
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=timeout, verify=True) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client, terminate_on_close=False) as streams:
            async with ClientSession(
                streams[0],
                streams[1],
                read_timeout_seconds=READ_TIMEOUT_SECONDS,
                client_info=types.Implementation(name=BRIDGE_NAME, version=BRIDGE_VERSION),
            ) as session:
                await session.initialize()
                yield session


def create_bridge(endpoint: str, token: str) -> Server:
    async def list_tools(context, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        try:
            async with remote_session(endpoint, token) as session:
                return await session.list_tools(params=params)
        except MCPError:
            raise
        except Exception as error:
            raise unavailable(error) from None

    async def call_tool(context, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            async with remote_session(endpoint, token) as session:
                result = await session.call_tool(params.name, params.arguments)
        except MCPError:
            raise
        except Exception as error:
            raise unavailable(error) from None
        if not isinstance(result, types.CallToolResult):
            raise MCPError(types.INTERNAL_ERROR, "The Stock Radar service returned an unsupported tool result.")
        return result

    return Server(BRIDGE_NAME, version=BRIDGE_VERSION, on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(endpoint: str, token: str) -> None:
    bridge = create_bridge(endpoint, token)
    async with stdio_server() as (read_stream, write_stream):
        await bridge.run(read_stream, write_stream, bridge.create_initialization_options())


async def check(endpoint: str, token: str) -> int:
    try:
        async with remote_session(endpoint, token) as session:
            listed = await session.list_tools()
    except Exception as error:
        print(f"{BRIDGE_NAME}: check failed ({describe_failure(error)}).", file=sys.stderr)
        return EXIT_UNAVAILABLE
    print(f"{BRIDGE_NAME}: check passed, {len(listed.tools)} tools discovered.", file=sys.stderr)
    return 0


def main(arguments: list[str]) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(name)s: %(message)s")
    try:
        endpoint = validate_endpoint(ENDPOINT)
        token = read_token()
    except BridgeConfigurationError as error:
        print(f"{BRIDGE_NAME}: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION
    if arguments == ["--check"]:
        return anyio.run(check, endpoint, token)
    if arguments:
        print(f"{BRIDGE_NAME}: unknown arguments. Use no argument or --check.", file=sys.stderr)
        return EXIT_CONFIGURATION
    anyio.run(serve, endpoint, token)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
