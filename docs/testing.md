# Testing and validation

## Current stage

`make test` runs infrastructure, schema and API checks, with standard-library assertions, FastAPI
TestClient and real PostgreSQL. Collection services and local MCP tools are implemented; financial analysis and live-provider workflows are pending. It runs the infrastructure smoke
check described below. Validate Markdown links, manifest JSON,
skill frontmatter, package-contained references and whitespace. If available, use Claude's plugin manifest
validator, but distinguish it from installation or execution in Cowork. Do not describe these checks as
live-provider validation.

## Proportional testing and coverage

Test to establish confidence in the current behavior and catch meaningful regressions. We do not require
100% coverage. The implementing agent may choose 85%, 90% or another justified target according to the
project stage, risk and value of additional tests. These numbers are examples, not a default minimum.
No coverage gate is configured today; do not add tooling or a gate solely to reach a percentage.

When adopting or changing a target, briefly record its scope, rationale and material untested behavior
here. This is an ordinary engineering decision and does not require separate user approval. Do not lower
a target or exclude meaningful code merely to hide a regression or make a failing check pass. A high
overall percentage cannot compensate for untested critical behavior.

Prioritize the happy path, material failures and known regressions. Give particular attention to financial
calculations, access control, transaction boundaries, idempotency and recovery as those capabilities arrive.
Test concurrency where competing operations could violate a real invariant. Focus integration tests on
the boundaries whose behavior cannot be established adequately in smaller tests.

Do not add tests that merely repeat the implementation, exercise third-party internals, freeze incidental
text or exhaust combinations with no plausible failure impact. Avoid duplicating the same assertion at
every test layer unless each layer addresses a different risk. Simple documentation edits and low-impact
configuration changes usually need focused validation, not a new automated test suite.

Use the smallest checks that adequately cover the change. Once they pass, broaden testing only when
failures, wider impact or an unresolved risk justify it. Explain material omissions briefly; do not create
an exhaustive exception register. The scenarios below guide each increment rather than require every
future test to exist before the first capability is implemented.

## Docker infrastructure checks

Run `make build` and `make test` with Docker running. No host Python, PostgreSQL or `.env` is required.
The test creates a unique Compose project and temporary credentials, validates configuration, builds
the Python image, verifies the uv lockfile offline, starts PostgreSQL, checks non-root Python execution and network connectivity, and
performs authenticated SQL writes. It recreates the database container and verifies the synthetic row
survives in its volume. Cleanup removes only the test project and its volume, including on failure.
A forced process kill may require manual cleanup of the printed test project name.

Validated locally on 2026-10-07: image build, complete infrastructure smoke check, persistence after
container recreation and test-resource cleanup passed. Empty-password rejection and the resolved
configuration (no database port published, internal network, read-only Python filesystem) were also
checked. The uv setup also passed lockfile generation/checking inside Docker and rejection of a
stale lockfile using a disposable copy. VPS execution remains untested; application checks were added in the increments below.

The schema check applies the real initial revision to a disposable PostgreSQL database. It verifies
model/schema agreement, random UUID defaults, primary keys, multiple sources sharing an instrument,
multiple experiments sharing an observation, duplicate rejection, foreign keys, price/window checks,
exact Decimal persistence, unknown alert mappings and first-hit uniqueness. It also verifies restricted
deletes, empty-revision suppression, repeated upgrade, downgrade and re-upgrade. Revisions are copied
inside the test container; no test data or generated revision is saved to the repository. Persistent
local and production databases are not used by `make test`. The complete schema and infrastructure
checks passed on 2026-10-07. Separately, the initial revision was applied to the local development
database and a schema comparison passed. No production or VPS migration was run.

API checks additionally exercise authentication, invalid query rejection, pagination, explicit mappings,
limited response fields, weak-configuration rejection and safe database failure responses. They verify
that the application reader cannot insert sources or read webhook receipts. Synthetic sources are
removed, and the entire test project is discarded afterward. The test HTTP client is installed only
in the tests image. The current Starlette version emits a deprecation warning for its httpx adapter;
the HTTP assertions still pass. No coverage percentage gate is introduced for this small increment.

Validated on 2026-10-07: the full disposable test run passed. The local API also passed real HTTP
liveness, authenticated readiness and source-list checks. Host access on 127.0.0.1:8000 was verified
after adding the API-only HTTP bridge; the database remains on its internal network.

These checks validate the implemented API foundation, infrastructure and migration tooling, not market
analysis, backups or live providers.
Future application tests must also execute inside Docker and use isolated databases.

## Tests as capabilities are implemented

Add each test group with its corresponding roadmap increment, not as a prerequisite for the first API
route. Routine checks remain local and synthetic; live-provider checks are a separate activity.

Use synthetic fixtures and an isolated PostgreSQL database. Test decimal thresholds, localized number
parsing, rating normalization, immutable references, idempotent ingestion and conflict handling. Database
integration tests must use PostgreSQL rather than substituting SQLite for concurrency/constraint behavior.

Webhook tests cover invalid input and identity, duplicates, unmapped alerts, out-of-order delivery,
database failure before acknowledgement and recovery of committed pending receipts after restart.
Analysis tests cover pending, expired/no-hit, incomplete and ambiguous cases, coverage exclusions and
repeat daily runs for the same asset. Missing notifications must not become verified non-hits.

Contract tests cover REST and MCP schemas and access scopes. Plugin checks cover missing capabilities,
partial tables, prompt injection in page content and uncertain write outcomes. Live browser/provider checks
are separate, explicitly scoped evidence, never hidden inside routine automated tests.

Add runnable commands and CI with implementation. Do not copy another repository's unavailable `make`
targets or impose an arbitrary coverage percentage. Test behavioral and integrity risks, not incidental wording.

## Collection and MCP increment

The workflow check uses the real Streamable HTTP protocol through the SDK application: initialization,
tool discovery and every implemented tool, with real PostgreSQL and synthetic observations. It exercises
reader/collector permissions, source idempotency, analyst versus technical/unknown normalization,
Decimal persistence, collection read-back, changed-payload conflicts, transaction rollback on currency
conflict, concurrent identical retries, invalid inputs, bounded reports and the 1 MiB body limit.
Database checks deny collector deletes and reads of webhook data. The disposable project contains all
synthetic records and is removed afterward. No new coverage gate is introduced: integrity and access
boundaries are the focus. Live Cowork, browser collection and provider transport remain unverified.

Validated on 2026-10-07: the complete disposable infrastructure, migration, API and MCP workflow suite
passed, including persistence after database recreation and removal of the test volume.

## Webhook increment

The Docker suite checks separate authentication, JSON/type/time/price validation, canonical payload
retries, explicit event-ID conflicts, concurrent submissions, one event per level, late earlier events,
unknown mappings and subsequent reconciliation. It verifies atomic rollback of event selection and
receipt state on a simulated processing database failure, a real unavailable-database 503 before
acknowledgement, and restricted database privileges. A pending receipt is left deliberately, the database
container is recreated, and the operator recovery command must process it. This establishes durable
recovery with synthetic data, not a live TradingView connection or production latency guarantee.

Validated on 2026-10-07: the full Docker suite passed, including webhook processing rollback and
operator recovery of a committed pending receipt after PostgreSQL container recreation.

## Observability increment

Docker checks inject HTTP, MCP, database and webhook processing failures. They verify safe responses,
request/error correlation, isolation across concurrent requests, sanitized stack frames, bounded metric
labels, MCP failures counted despite HTTP 200, post-response failure capture, persistent log lookup,
concurrent sink rotation and continued responses when the file sink fails. Synthetic secret markers
must be absent from logs, metrics and error responses. No public debug route is installed. These tests
cover application telemetry, not production alert delivery or a remote monitoring service.

Validated on 2026-10-07: the complete disposable Docker suite passed with observability checks. A separate
container check confirmed application stack frames survive deep driver failures without leaking credentials.
Local authenticated metrics and HTTP correlation probes also passed.
The named log volume also preserved a request event across local API container recreation; the Docker
lookup command retrieved it by its original request ID.

## Quote monitoring increment

`tests/check_monitoring.py` drives the real monitoring cycle against PostgreSQL through the restricted monitor
role, with a fake provider and an injected clock. It never calls brapi. It checks the next
wake-up computed from a controlled instant before, at and after minutes 10 and 40, across the hour and the
day. It covers repeated indications reusing
one run, a concurrent creation race across two experiment versions, the capacity limit and oldest-first
admission, cancellation (idempotent, permission-checked, freeing a slot), activation only from a quote not
earlier than the origin observation, the immutable reference and the 20 session expiry computed across a
holiday. Temporal checks cover a future timestamp followed by a valid quote, a quote older than 60 minutes
and one outside the session. Hit checks cover several levels in one quote, repeated and out-of-order quotes,
completion, and a hit from the last session followed by expiry on a closed-market cycle with no provider call.
It also checks a holiday, a weekend, the late opening on 18 February 2026, a missing calendar year, an
activation without calendar coverage, a provider failure for one instrument, a run cancelled during the
external call, the stale signal after five cycles, a first request that outlasts the close so the second is never started, overlap prevention, a pre-existing webhook run left
untouched, an earlier webhook replacing quote evidence through the webhook role, the read routes and tools,
and denied privileges. The provider client is checked with synthetic payloads and a loopback HTTP server
for the Authorization header, the absence of the key in the URL and refused redirects.

`tests/check_migrations.py` now upgrades to the initial revision, inserts tracking runs in every legacy
status with a level, a receipt and an event, then applies the new revision and verifies those rows. It also
checks the new constraints, the refusal to downgrade over polling evidence and a clean downgrade afterwards.

Validated on 2026-10-08: the complete disposable Docker suite passed. Not validated: any real brapi request,
the provider's actual delay and timestamp behavior, the continuous process over real 10 and 40 minute slots,
the migration on the development or any persistent database, and VPS operation. The calendar and hours were
checked against B3 pages by reading, not by an automated test. No coverage gate is introduced.

Validated on 2026-10-09: the complete disposable Docker suite passed after the schedule moved to minutes 10
and 40. Not validated: the sleeping loop itself over real time, any real brapi request and VPS operation.

## Plugin package increment

Checked on 2026-10-09 for plugin version 0.2.0: `claude plugin validate ./plugin`, JSON parsing of the
manifest and the synthetic example, skill names against their folders, description lengths, relative links
inside `plugin/`, the absence of em dashes and secret-like strings, and the archive layout. The synthetic
example was validated against the real `CollectionInput` model in the Docker runtime image, without a
database. `make test` was not rerun because no application code changed.

Not validated: installation or skill discovery in Cowork, reading the real TradingView table, the access
pause, any MCP call from Cowork, a real `register_collection` write and scheduling. These need the pending
items in [plugin](plugin.md) and must not be inferred from the static checks.

Checked on 2026-10-09 for plugin version 0.2.1, after adding `make package` and correcting the
`prepare-triggers` description: `make package` produced `dist/stock-radar-0.2.1.zip` with the manifest at
the archive root and the same nine files as the distributable content of `plugin/`, each byte-identical;
`claude plugin validate ./plugin`; `git diff --check`. `make test` was not rerun because no application code
changed. Not validated, as before: installation, skill discovery and any MCP call in Cowork. The 0.2.0
archive no longer matches `plugin/`.

## Plugin connection increment

Tested by the owner in Cowork on the MacBook Pro, reported on 2026-10-09 for version 0.2.1: the plugin was
installed and enabled, the interface recognized its nine files and four skills, and `check-status` stated
that the MCP tools were absent, without claiming backend access or changed records. This validates
installation and the behaviour without a connection. It does not validate connectivity.

The checks below describe the local bridge and sandbox of version 0.3.0. That solution was retired in
0.4.0 and its scripts no longer exist; the record is kept as history and none of it applies to the current
package.

Checked on the development machine on 2026-10-09 for version 0.3.0, outside any Claude client:

- `make sandbox-up` created an isolated Compose project on `127.0.0.1:18001` after confirming the port was
  free, migrated and provisioned only that database and left the monitor stopped.
- `mcp-remote@0.14.3`, started through `npx` with the header placeholder and the sandbox reader token in
  its environment, was driven over stdio: `initialize` answered, `tools/list` returned the 11 tools,
  `service_status` returned the version and capabilities, and `register_source` returned `forbidden`.
- With the sandbox collector token in the environment, the same proxy registered a synthetic source, sent
  the packaged example with that source `id` and a `client_collection_id` generated once, received a receipt
  with `duplicate: false`, read it back with `get_collection` and received `duplicate: true` with the same
  `id` for the identical repeat.
- The proxy log named the header and did not contain the token.
- With a wrong token the proxy probed the same loopback service for OAuth, received 404 and exited. No
  browser opened and no external request was made.
- A request with a foreign Host header received 421 and a request without a token received 401.
- With `COMPOSE_PROJECT_NAME`, `API_PORT` and `MONITOR_ENABLED` set to conflicting values in the terminal
  and on the `make` command line, `make sandbox-up`, `sandbox-down` and `sandbox-destroy` created, stopped
  and removed only `stock-radar-sandbox` resources on port 18001, with no monitor container. No other
  container changed.
- `make sandbox-token` was run against a recording stand-in for the `security` command: the recorded
  arguments were `-i` and the read-back query, with no token, and the token arrived on standard input.
  The same standard-input form was confirmed to write and update an item in a throwaway keychain file.
  The login Keychain was not modified.
- `plugin/mcp/bridge.sh` exited with a clear message when the Keychain item was absent.
- `claude --plugin-dir ./plugin mcp list` resolved `${CLAUDE_PLUGIN_ROOT}`, started the launcher and showed
  the server as failed, as expected without the Keychain item. This is Claude Code, not Cowork.
- `make package`, `claude plugin validate ./plugin` and `git diff --check`.

Not validated: `make sandbox-token` writing to the login Keychain and the launcher reading it back, since
no item was created in the login Keychain of the development machine; the bridge started by the Claude desktop app; any MCP call from Cowork; the synthetic
collection with receipt and idempotent repeat from Cowork; scheduling; any VPS operation. `make test` was
not rerun because no application code changed.

## Removal of the local bridge

Checked on 2026-10-09 for plugin version 0.4.0: the manifest has no `mcpServers` entry and the package
holds no script, so installing it starts no local process; `make package` produced
`dist/stock-radar-0.4.0.zip` with the nine distributable files of `plugin/`, each byte-identical, and no
`mcp/` entry; `claude plugin validate ./plugin`; `git diff --check`. `make test` was not rerun because no
application code changed. No sandbox resource, Keychain item or program was removed from any machine.

Not validated: installation of 0.4.0 in Cowork, any MCP connection from Cowork and any VPS operation. The
connection to the service on the VPS is pending; see [plugin](plugin.md).

## MCP allowed hosts

`tests/check_transport.py` builds the application with synthetic settings and no database and is part of
`make test`. With one synthetic `host:port` in `MCP_ALLOWED_HOSTS` it checks that an authenticated
`initialize` returns 200 for that Host and for loopback names; 421 for the same name without the port, with
another port, for another name and for a name that only ends with the allowed one; 401 without a token or
with a wrong token, whatever the Host; 403 for a non-loopback Origin and 200 for a loopback Origin. With
the variable empty the same Host returns 421. Wildcards, schemes, spaces and more than eight entries are
rejected at start.

Validated on 2026-10-09: the complete disposable Docker suite passed with this check included. Not
validated: the setting on the VPS, the Host value that Tailscale Serve actually forwards, and any request
through the tailnet. The 421 that prompted the change was reported by the owner and not reproduced here.

## Python bridge

`tests/check_bridge.py` is part of `make test`. It starts synthetic MCP servers on loopback, launches the
bridge as a child process over stdio through `tests/bridge_harness.py`, which replaces only the endpoint
and the Keychain read, and drives it with the SDK client. No real token, host or data is used.

Checked on 2026-10-09 for plugin version 0.5.0, in the tests image without network and natively on macOS
with Python 3.13 in a scratch environment built from `plugin/mcp/requirements.txt` with hash checking:

- the tool list through the bridge equals the list read directly, including descriptions and input and
  output schemas;
- a successful call returns the same structured content and text with `isError` false;
- a tool error, invalid arguments and an unknown tool arrive with `isError` true and the service's text;
- a refused token, a closed port and a redirect to another origin each end `tools/list` and `tools/call`
  with MCP error -32001, never a result, and the other origin receives no request;
- diagnostics contain no token and no `Bearer` value;
- the endpoint check rejects `http` and embedded credentials, a missing Keychain command or item stops the
  bridge with exit code 1 and nothing on standard output, and the launcher reports a missing environment;
- the manifest declares the launcher by `${CLAUDE_PLUGIN_ROOT}` and its version equals the bridge version;
- `make package`, `claude plugin validate ./plugin` and `git diff --check`.

Reported by the owner, not reproduced here: from a terminal on the MacBook Pro an authenticated
`initialize` to the VPS endpoint over Tailscale returned 200 with server name `Stock Radar`, version
`0.1.0` and protocol version `2025-03-26`; a shell command of a Cowork task ran in the cloud and did not
reach that address.

Not validated: the bridge against the real endpoint, the Keychain read with a real item, Cowork starting
the bridge, tool discovery and `service_status` from a Cowork task, and Python 3.10 to 3.12. The complete
`make test` was not rerun for this increment because no application code changed; the new check was run
alone in the same image.


## Qualified observations only

Collection schema version 2: the collector sends only Strong Buy analyst rows with a negative daily change
and the service rejects a collection that contains any other row. `tests/check_collection_rules.py` is part
of `make test` and uses synthetic rows only.

Validated on 2026-10-09 with the complete disposable Docker suite, including the new migration and the
schema drift check:

- a qualified row together with, or replaced by, each of these is rejected with `observation_not_eligible`
  and stores nothing, not even the collection or the instrument: another analyst label, an empty rating, a
  technical rating carrying the Strong Buy label, and a zero, positive or missing daily change;
- qualified rows alone are stored, with `observation_count` equal to `eligible_count`, the sent
  `rows_examined` and `source_total` in the receipt, one tracking run each, and labels preserved as sent;
- an identical repeat returns the same receipt with `duplicate: true` and the same identifier with other
  content returns 409;
- a complete collection with no observation is accepted and is idempotent;
- `rows_examined` below the number of observations, a complete collection whose `rows_examined` differs from
  `source_total`, a missing `rows_examined` and schema version 1 are rejected as invalid requests;
- pruning a synthetic legacy collection: the dry run changes nothing; wrong expected totals, eligible counts
  or tickers, an unknown collection, a collection of version 2 and a tracking run on a removable observation
  each abort without changes; applying removes only the ineligible observations of that collection, keeps
  the eligible ones and their tracking run, records `rows_examined`, leaves instruments and other
  collections untouched, and a second run aborts.

The packaged example was validated against `CollectionInput`. Plugin version 0.6.0 was packaged and checked.

Not validated: the migration and the pruning on the VPS, the collection the owner reported
(`2776fe1c-bf06-4cb4-a536-1fe0e13c4674`, 51 observations, 3 eligible), and the changed skill in Cowork
against the real page. No real data was used.

## Trading calendar in PostgreSQL

The calendar moved from code to the `trading_days` table. `tests/check_monitoring.py` reads the rows the
migration inserts and drives the monitor against them; `tests/check_migrations.py` covers upgrade, downgrade
and schema drift for the new table.

Validated on 2026-10-09 with the complete disposable Docker suite:

- 365, 365 and 366 rows for 2026, 2027 and 2028; every weekend closed; 29 February 2028 open;
- 2026 preserved: the same 14 weekday closures, 13:00 opening on 18 February and 10:00 to 17:00 on every
  other session, with the existing monitor checks for a holiday, a weekend, the late opening, the close and
  a 20 session expiry unchanged and passing against the table;
- 2027 and 2028: weekday closures are exactly the national holidays, and Carnival Monday and Good Friday of
  2027 are open, as the authorized basis implies;
- year change: a run activated on 14 December 2026 expires at the close of 14 January 2027, the 20th
  session counted by hand, including the activation day;
- the 20 session count executes one SQL statement;
- internal gap: with the row of 6 January 2027 removed the same quote leaves the run prepared, and it
  activates once the row is back;
- preserved expiry: after 5 January 2027 is changed to closed, a new calculation gives 15 January while the
  active run keeps its stored `expires_at`;
- a date with no row gives `calendar_unavailable` and no provider call, and a day outside a loaded range is
  not treated as covered;
- the monitor role reads `trading_days` and cannot update or delete it; collector and reader cannot read it.

Not validated: the migration on any persistent database or on the VPS, real sessions of 2027 and 2028, and
the official hours outside the configured 10:00 to 17:00. No provider was called.
