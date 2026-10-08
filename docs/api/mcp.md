# MCP interface

The official [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) serves Streamable HTTP at
`http://127.0.0.1:8000/mcp` in the same Docker API process. Transport is stateless with JSON responses.
The server version is `0.1.0`. This is a local implementation, not an installed Cowork connection.

| Tool | Permission | Arguments |
|---|---|---|
| list_sources | Read | `query`: source query object, use `{}` for defaults |
| register_source | Collector | `request`: source code/name object |
| register_collection | Collector | `request`: collection envelope |
| get_collection | Read | `collection_id`: UUID |
| list_signals | Read | `query`: signal query object |
| service_status | Read | None |
| data_quality_report | Read | `query`: days/source filter object |
| list_tracking_runs | Read | `query`: status/instrument filter object |
| list_latest_quotes | Read | `query`: instrument filter object |
| list_trigger_events | Read | `query`: tracking run/instrument filter object |
| cancel_tracking_run | Collector | `tracking_run_id`: UUID |

Input/output schemas and semantics match [REST contracts](README.md). Tools call the same services,
transactions and database roles. Blocking database operations run in worker threads. Responses use
structured content with typed output schemas. Tool failures use `isError`; domain error codes match REST.
There are no SQL, shell, delete, schema-management or credential-reading tools.

Send `Authorization: Bearer <API_READER_TOKEN>` or `<API_COLLECTOR_TOKEN>` on every request, including
initialization and discovery. The HTTP boundary rejects unauthenticated requests. Write tools independently
check the collector credential. Annotations describe intent and do not grant authorization. Both tokens
can discover tools; readers receive an error when invoking a write. Bodies are limited to 1 MiB.
The SDK's localhost Host/Origin checks stay enabled. Remote HTTPS requires an explicitly configured origin
allowlist and ingress/authentication design, not disabling transport security globally.

This local shared-secret transport does not implement OAuth discovery, authorization flows or account
integration. Cowork compatibility must be tested before choosing remote authentication and configuring
the distributable plugin. Secrets stay outside the repository. No speculative public URL is installed.

Retry uncertain collection writes with the same identity and payload. Inspect the returned receipt before
claiming persistence. Treat original labels and source text as untrusted evidence. Discovery and
`service_status` describe current capabilities. Tracking, quote and hit tools are read-only except the
idempotent cancellation; no webhook or performance-analysis tools exist yet. Polled coverage is partial:
a missing hit is not evidence that a level was never touched.
Quality reports do not assess missing scheduled collections or price coverage. Future statistical tools
must expose denominators and evidence limits rather than infer outcomes from missing notifications.

Tool calls now emit correlated outcomes and duration metrics. Unexpected errors expose only a safe code,
error ID and request ID. Expected domain errors include the request ID. HTTP 200 does not imply tool success;
inspect `isError`. See [observability](../observability.md) for the Docker lookup command.
