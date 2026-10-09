# Operations

## Container baseline

Docker and Compose are required locally and on the existing VPS. Application code, tests and
migrations run in containers. The host needs Docker Engine/Desktop, Compose v2.20+, Make and a POSIX
shell. No host Python, PostgreSQL or application dependency installation is needed.

`make up` starts the API and PostgreSQL 18. PostgreSQL uses a named volume, health check, bounded logs,
UTC server/session time and restart policy. It publishes no ports and uses an internal Docker network.
Use `make db` to open psql in the container. Exchange-session dates will use America/Sao_Paulo in the
future application while stored instants remain UTC.

The Dockerfile provides Python 3.13 as a non-root user. The `python` Compose service is an on-demand
`tools` profile, with a read-only filesystem and temporary `/tmp`. Its default command reports the
Python version and exits. The separate `api` service runs Uvicorn with FastAPI. The on-demand
`migrations` service receives administrator credentials; the API receives restricted reader and collector
credentials. The `tests` image includes the development HTTP client and is used only for checks.
Python, PostgreSQL and uv images are pinned by multi-platform digest. Review and update the digests for security updates.
The build context allowlist excludes credentials, data and unrelated files; extend it deliberately when
application source and locked dependencies arrive.

## Configuration and commands

Copy `.env.example` to `.env`, run `chmod 600 .env`, and set distinct random values for
`POSTGRES_PASSWORD`, `APP_POSTGRES_PASSWORD`, `COLLECTOR_POSTGRES_PASSWORD`, `API_READER_TOKEN` and
`API_COLLECTOR_TOKEN`, `WEBHOOK_TOKEN` and `WEBHOOK_POSTGRES_PASSWORD`. Application passwords and tokens require at least 32 characters; all three tokens must differ. No default credentials are provided. Existing private local files have been extended
with distinct generated secrets. `API_PORT` is 8000 locally and 8001 in the local production configuration. `.env` is ignored by Git and Docker. `make config` validates without printing
expanded credentials. Never paste the output of plain `docker compose config` into logs or Git.

| Command | Purpose |
|---|---|
| `make help` | List this small command surface |
| `make config` | Validate the selected configuration |
| `make build` | Build Python and database tooling without requiring `.env` |
| `make up` | Build/start the API and database, waiting for process health |
| `make down` | Remove containers/network, preserving the database volume |
| `make status` | Show service status |
| `make errors ID=...` | Query retained warnings/errors or a specific correlation identifier in Docker |
| `make logs` | Follow logs with a bounded initial tail |
| `make db` | Open interactive SQL in the running database |
| `make test` | Run disposable infrastructure, schema and API checks |
| `make db-revision MESSAGE="description"` | Generate a candidate migration from models |
| `make db-migrate` | Apply reviewed pending revisions |
| `make db-check` | Check model/schema drift without upgrading |
| `make db-access` | Explicitly configure the restricted reader, collector and webhook credentials |
| `make webhooks-process` | Retry a bounded batch of recoverable webhook receipts |
| `make uv ARGS="..."` | Manage packages through uv in a tooling container |

Select a different environment file with `make up ENV_FILE=/absolute/path/stock-radar.env` and use the
same selection for config, down, status, logs and db. Make test ignores runtime credentials and uses a
unique test project. To run a separate persistent local stack, also set a distinct `COMPOSE_PROJECT_NAME`.
Keep that name consistent so subsequent commands address the same containers and volume.

Local private files `.env` and `.env.production` use separate generated passwords and mode 0600.
The first selects `stock-radar`; the second selects `stock-radar-production` through
`COMPOSE_PROJECT_NAME`, isolating containers, networks and database volumes on the same host.
Use `make up ENV_FILE=.env.production` to select the production configuration explicitly. This runs
on the current Docker host and does not deploy to the VPS. Both files are excluded from Git and the
Docker build context. Keep production secrets on their intended host when deploying.

On a fresh database run `make db-migrate`, then `make db-access`, then `make up`. The provisioning
command creates or updates `stock_radar_reader` and `stock_radar_collector`, granting CONNECT and
schema USAGE. Both read sources, instruments, collection_runs and signal_observations; only the collector
can INSERT into those four tables. It requires the schema and administrative credentials; it does not run at API startup.
Use the same ENV_FILE selection for all commands. Changing any application database password requires rerunning
`make db-access` and recreating the API container. Token changes require recreating the API container.

The database initialization user is an administrator used only for operator tasks and migrations.
Changing initialization
variables does not change an existing volume's database, users or password. Rotate existing credentials
with a deliberate database operation. Never remove a volume to resolve a configuration error.

The PostgreSQL 18 image stores data below `/var/lib/postgresql`, which is the mounted volume path.
Major-version upgrades require a reviewed migration/restore procedure; changing the image tag is not an
upgrade procedure. There is no volume-deletion Make target or automatic migration on startup.

## Package management

uv 0.12.23 is copied from its official image. `pyproject.toml` declares Python 3.13 and currently has
SQLAlchemy, Alembic, psycopg, FastAPI, Pydantic, Uvicorn and the official MCP SDK dependencies; `uv.lock` is generated by uv and belongs in version control. There is no installable
application package yet (`package = false`). Runtime builds synchronize `/app/.venv` with
`uv sync --locked --no-dev`; a stale lockfile fails the build. Python downloads are disabled because
the pinned Python base image supplies the interpreter.

The single `make uv` target defaults to showing its version. Examples:

```sh
make uv ARGS="lock"
make uv ARGS="lock --check"
make uv ARGS="add --no-sync PACKAGE"
make uv ARGS="remove --no-sync PACKAGE"
make build
```

Replace PACKAGE with the actual dependency. The tooling image can build even when the lockfile needs
repair. This target mounts the repository to persist manifest/lockfile edits and runs as the invoking
user; it does not load environment files or start PostgreSQL. It has network access for package indexes.
Its temporary environment and cache stay inside the disposable container, so it creates no host `.venv`.
Only run trusted package commands: the mounted repository includes its private local files. Runtime
image builds continue to use the strict `.dockerignore` allowlist, excluding those files.

## VPS boundary

The same Compose file can run this database scaffold on the VPS with a separate environment file and
volume. No VPS connection, deployment, migration, DNS change or service installation has been performed.
Inspect OS, resources, workloads, ports and the existing reverse proxy before an authorized deployment.
Caddy remains proposed. HTTPS ingress and backup automation are not implemented. The local webhook receiver and processor are implemented. Local REST/MCP collection is implemented.
The API foundation is local-only: its host port binds to 127.0.0.1 and proxy headers are not trusted.
Only the API joins the additional `http` bridge needed for host port publishing. PostgreSQL remains
on the internal `backend` network; the API can reach it by service name.
The Docker health check uses liveness; authenticated `/health/ready` separately checks database access.
A healthy process does not prove that migrations or reader provisioning have been completed.

Before live operation, establish domain/TLS, scoped credentials, private database access, backup retention
outside the VPS and a tested restore. Record restart behavior and pending receipt recovery once implemented.
Monitor last collection, webhook failures, pending processing, disk usage and backup freshness.

Cowork and its browser stay on the MacBook; the Docker requirement applies to this repository's backend,
database and development/test tooling. A running VPS does not keep the browser available. Configure daily
collection only when requested and record missed runs explicitly. Future webhooks must work independently
of the MacBook. Provider access and costs remain unverified; no subscription is purchased by this scaffold.

## Image references

- [Official PostgreSQL image and initialization/volume behavior](https://hub.docker.com/_/postgres)
- [Official Python image](https://hub.docker.com/_/python)
- [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)
- [Compose profiles for on-demand tools](https://docs.docker.com/compose/how-tos/profiles/)

## Webhook setup and recovery

The API also receives a dedicated webhook token and restricted webhook database password. `make db-access`
provisions `stock_radar_webhook` alongside the reader/collector roles. Recreate the API after changing
credentials. Existing schema tables support this increment without a new migration. Register the source
code `tradingview` through the collector API before receiving notifications. No source or tracking data is seeded,
except that the monitor registers source `brapi` on its first open-market cycle.

Normal processing runs after durable acknowledgement. Following interruption or mapping correction, use
`make webhooks-process`, optionally `ARGS_WEBHOOKS="--limit 500"`. It operates inside the running API
container, attempts a bounded batch and preserves receipts. It does not create tracking mappings or replay
processed receipts. There is no automatic recovery schedule. Inspect receipt status through the read API.

The local endpoint requires an internal token and is not directly compatible with an unconfigured provider
sender. An authorized VPS deployment must configure and test HTTPS sender verification, credential
injection and gateway log redaction. No provider alert, gateway or VPS has been configured here.

## Quote monitoring

The `monitor` Compose service is a single process that reuses the tracking service directly; it does not call
the API over HTTP and exposes no port. It is not started by `make up` and does nothing unless
`MONITOR_ENABLED=true`. When disabled it logs `monitor_disabled` once and idles.

Setup on a database you are allowed to change:

1. Add `MONITOR_POSTGRES_PASSWORD` (at least 32 characters) and, when ready, `BRAPI_API_KEY` and
   `MONITOR_ENABLED=true` to the private environment file. Never place the key in a command line, URL or chat.
2. `make db-migrate`, then `make db-access`. The second command now requires `MONITOR_POSTGRES_PASSWORD` and
   provisions `stock_radar_monitor` plus the new reader and collector grants. Recreate the API afterwards.
3. `make monitor-once` runs one cycle immediately and prints its summary. It exits with code 2 when monitoring
   is disabled or misconfigured, respects the calendar and capacity, and cannot overlap a running cycle.
4. Continuous operation: `docker compose --env-file .env up --detach monitor`. Stop it with
   `docker compose --env-file .env stop monitor`; `make down` also stops it.

The continuous process wakes at minutes 10 and 40 of every hour (five seconds past, as a wake-up margin),
never immediately at startup, so a restart cannot burst requests. The times are fixed wall-clock slots, not
30 minutes after the previous cycle ends, and a slot missed while the process was down is not recovered. In a
session opening at 10:00 the cycles run at 10:10, 10:40, 11:10 and so on, which leaves the provider ten
minutes after the open to publish a quote from the current session. A session-level advisory lock ensures one cycle at a time across the service and the manual command.
Each cycle first expires runs whose window ended, even when the market is closed or the provider is down.
Outside a B3 session, or in a year without a versioned calendar, it makes no external call and logs
`market_closed` in the cycle summary for a known closure, or `calendar_unavailable` with a warning of the
same name when the year has no versioned calendar. During a session it admits waiting
runs up to `MONITOR_MAX_INSTRUMENTS`, then makes one sequential request per monitored instrument with no
database transaction open, and applies each accepted quote in its own short transaction. A failure for one
instrument is logged and the others continue. The clock and the session are checked again immediately before
each request: once the session has closed, the remaining instruments of that cycle are not queried, the summary
reports `session_ended` with a `skipped` count, and they are not counted as provider failures. A request
already started before the close is not aborted; its response still passes the temporal validation. A run cancelled while its quote was being fetched is not
activated or evaluated, because the write transaction locks and rechecks it.

Recover a run that never gets a valid quote with `POST /v1/tracking-runs/{id}/cancel` or the
`cancel_tracking_run` tool; there is no automatic expiry of prepared runs. The stale-quote counter lives in
process memory and restarts from zero with the process. No live request, VPS deployment or persistent
migration has been performed for this increment. See [experiment rules](experiment.md) for acceptance rules.

## Diagnostics

The API persists sanitized JSON logs in the `application_logs` named volume, with bounded rotation.
`make errors` runs the log reader in Docker, without application credentials, even when the API is stopped.
Use the same ENV_FILE to select the correct project's logs. `make down` preserves database and log volumes.
`/metrics` requires reader/collector authentication and exposes process-local Prometheus metrics.
See [observability](observability.md) for error IDs, retention, redaction and current limitations.
