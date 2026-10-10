# Observability and error tracking

## Implemented scope

The Docker API emits structured JSON logs, exports Prometheus-format metrics and captures errors at the
HTTP, MCP and webhook/recovery boundaries. `observability/` owns logging, correlation, metrics, the HTTP
boundary and the lookup command. Domain records remain in PostgreSQL; telemetry is not stored in business
tables and does not depend on database availability. No schema migration is required.

This increment uses the official [Prometheus Python client](https://prometheus.github.io/client_python/).
It provides metrics export, not a Prometheus server, historical time-series store, Grafana dashboard,
Sentry installation, distributed tracing backend or automatic notifications.

## Find a failure

Every HTTP response includes a server-generated `X-Request-ID`. Unexpected HTTP failures return a safe
500 `internal_error` response; database failures retain the safe 503 response. Captured server failures
also include `X-Error-ID`. Existing error body contracts remain intact. Expected validation, authentication,
missing-record and conflict responses keep their status and can be found using their request ID.
Client-supplied request IDs are not trusted or reused.

```sh
make errors
make errors ID=REPLACE_WITH_REQUEST_OR_ERROR_ID
make logs
```

`make errors` shows the latest 30 retained warnings/errors. With `ID`, it searches exact request IDs,
error IDs, webhook receipt IDs or error fingerprints and includes matching informational events too.
Use the actual identifier without angle brackets. It runs an on-demand Docker container with read-only
access to the log volume and no database/API credentials. It works while the API is stopped, provided
its runtime image has been built. ENV_FILE selects the same Compose project and volume as other commands.

Each captured failure has an occurrence-specific `error_id` and a fingerprint derived from exception type
and stack locations. Fingerprints group repeated failures at the same code locations and may change after
code changes. Logs include UTC timestamps, component, request correlation, exception class, filenames,
function names and line numbers. The endpoint/template or MCP tool identifies the operation. Webhook logs
include the receipt ID so a later recovery attempt can be connected to the original receipt, even though
it has a new request/correlation ID. Receipt status and its domain error code remain available through
`GET /v1/webhook-receipts/{receipt_id}`.

Stack frames deliberately omit source snippets, local variables and exception messages. They identify
where to investigate without persisting SQL parameter values, credentials or source evidence. Third-party
runtime logs retain logger, level and exception class when available, while their free-form messages and
tracebacks are discarded. Native PostgreSQL logs are separate and remain governed by database settings.

## Boundaries

- HTTP: completion logs contain method, route template, status and response duration. The outer application
  middleware catches unexpected exceptions before sending a safe response. Unknown paths use `unmatched`.
  If a response already started, its status cannot be changed; a failure is recorded with `phase=after_response`.
- MCP: tool failures are tracked independently of HTTP status because MCP can return `isError` with HTTP 200.
  Unexpected failures return only a safe code, error ID and request ID. Expected domain failures include the
  code and request ID. Actual tool invocation is instrumented; protocol-level validation/discovery is covered
  by HTTP completion logs and sanitized SDK logs, not the tool invocation counter.
- Webhooks: the receipt acknowledgement remains independent from later processing. Unexpected processing
  failures are captured by receipt ID and return failure to the caller without escaping the background task.
  Transactions still roll back and durable receipts remain recoverable. Domain outcomes such as unmapped
  or failed mappings are warning events, not fabricated successful processing.
- Recovery CLI: a correlation ID covers the batch, receipt IDs identify attempts, and unexpected top-level
  failures exit unsuccessfully with a safe error ID. Operator output describes attempts, not confirmed hits.

Context is isolated across concurrent requests and propagated to worker threads. An internal header carrying
the server-generated ID bridges the MCP transport's task boundary; the middleware always replaces any
client value. It is not an authentication mechanism. HTTP duration ends with the response body, excluding
subsequent background work. Successful liveness probes and metrics scrapes do not produce request logs.

## Metrics

`GET /metrics` accepts the reader or collector Bearer token. The webhook credential cannot read it.
The endpoint exposes:

| Metric | Meaning |
|---|---|
| stock_radar_http_requests_total | Completed responses by method, route template and status |
| stock_radar_http_duration_seconds | Response-time histogram by method and route template |
| stock_radar_errors_total | Captured failures by component |
| stock_radar_mcp_calls_total | Tool calls by tool and success/rejected/error outcome |
| stock_radar_mcp_duration_seconds | Tool execution-time histogram |
| stock_radar_webhook_processing_total | Processing attempts by outcome, including already-processed retries |

Metric labels never include request IDs, asset symbols, payloads, URLs or query values. Histograms expose
count, sum and buckets, suitable for aggregation by a future Prometheus collector. Counts describe technical
operations, not unique financial events. API metrics are in memory and reset when the process restarts;
CLI recovery runs have separate process-local counters and persistent logs. The configuration runs one
Uvicorn process. Multiple workers/replicas require an explicitly designed metrics aggregation setup.

## Docker storage and retention

The API writes logs to stdout and `/var/log/stock-radar/events.jsonl`. Compose sets `LOG_DIRECTORY` and
mounts the `application_logs` named volume. The API filesystem remains read-only except its log volume
and temporary directory. The application continues to run as UID 10001. The lookup container mounts the
same volume read-only. No Docker socket or external telemetry account is used.

The active file rotates at 10 MiB and keeps five backups, about 60 MiB per Compose project. Rotation uses
an OS file lock and reopens the active file so API and recovery processes can safely share the sink.
Container recreation and ordinary `make down` preserve the volume. Volume deletion removes the history;
rotation eventually evicts old records. This is bounded diagnostic retention, not an immutable audit archive.
The stdout stream also uses Compose's existing Docker log rotation.

File-sink write failures emit a fixed `log_storage_unavailable` warning to stderr and do not interrupt
request handling. Stdout remains a fallback; restore disk/volume access to resume durable logging.
A directory that cannot be created at startup prevents startup rather than silently pretending persistence
is enabled. Application settings without LOG_DIRECTORY, such as disposable tests, use stdout only.

Bodies, authorization headers, cookies, query strings, raw paths, SQL text/parameters, browser evidence
and exception messages are excluded from application telemetry. Do not add these fields during debugging.
Log access still belongs to the operator; the lookup facility is not a public HTTP endpoint. Public ingress,
remote authentication, dashboards, historical metric storage and alert delivery remain separate work.

## Quote monitoring events

The monitor process writes to the same structured log and volume, so `make errors` shows its warnings and
errors. It has no HTTP listener and exports no Prometheus metrics; `/metrics` covers the API process only.

| Event | Level | Meaning |
|---|---|---|
| `monitor_cycle` | INFO | Cycle summary: outcome (`completed`, `market_closed`, `session_ended`, `calendar_unavailable`), expired, admitted, instruments, recorded, unchanged, rejected, failed, skipped, stale symbols |
| `monitor_cycle_skipped` | WARNING | Another cycle held the lock |
| `monitor_disabled`, `monitor_configuration_invalid` | WARNING, ERROR | Process started without explicit enablement or with invalid settings |
| `calendar_unavailable` | WARNING | No `trading_days` row for the current date; polling suspended |
| `calendar_coverage_missing` | WARNING | A run could not be activated because `trading_days` lacks a row before its 20th session |
| `quote_failed` | WARNING | Provider or payload failure for one instrument, with a safe code |
| `quote_rejected` | WARNING, or INFO for `quote_too_old` | Quote failed temporal validation and was not stored |
| `quote_stale` | WARNING | Five or more consecutive cycles without a newer accepted quote for an instrument |
| `tracking_activated` | INFO | Reference locked and levels created |

`quote_stale` only reports that the provider's market time stopped advancing. It does not declare the market
closed and does not stop other instruments. The counter is in memory and resets on restart. Events carry
instrument IDs, symbols and safe codes; the API key, request headers and response bodies are never logged.
Unexpected failures go through the shared error capture with component `monitor`.
