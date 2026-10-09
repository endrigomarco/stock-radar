# Stock Radar

Track stock recommendations, monitor price triggers, and analyze outcomes to measure how market signals perform over time.

## Current status

**Local REST and MCP backend with synthetic validation.** PostgreSQL, Python and all checks run in
Docker. Eleven normalized tables use random UUID primary keys and Alembic migrations. FastAPI and the
official MCP SDK share services for sources, atomic collection ingestion, signal queries, status and
quality reports, with separate reader and collector permissions. An authenticated webhook inbox deduplicates notifications and processes existing alert mappings.
Eligible signals now create reusable tracking runs, and a single Docker monitoring process can poll brapi
quotes every 30 minutes, at minutes 10 and 40, during B3 sessions to lock references and record first observed threshold hits.
Monitoring is disabled by default and has only been validated with a fake provider. Financial metrics,
VPS deployment and live-provider integration remain pending. The plugin package for Cowork was
installed by the owner and its skills were discovered; its local bridge to a disposable sandbox is implemented
but no MCP connection from Cowork has been validated.

## First experiment

Observe Brazilian stocks on TradingView's biggest losers list and select those whose **analyst rating**
is **Strong Buy** (shown as `Viés de alta forte`). Record the original daily observations and evaluate
whether each selected stock reaches +1%, +2%, +3%, -1%, -2%, and -3% relative to a fixed reference price.
A rebound is a hypothesis to test, not an assumed outcome. Analyst consensus and technical ratings are
separate signal types.

## Architecture

```text
MacBook Pro: Claude Cowork + Stock Radar plugin
  browser observations -> authenticated MCP tools
  analysis requests    -> authenticated MCP tools
                                   |
VPS, running continuously           v
  Python / FastAPI -> shared application services -> PostgreSQL
  webhook receiver -> durable event inbox -> trigger evaluation
  MCP queries      -> reproducible metrics -> Claude's analysis
                                   ^
                     TradingView alert notifications
```

No frontend is planned for the MVP. Claude is the conversational interface. PostgreSQL on the VPS is
the source of truth; no local SQLite database is needed. The MacBook is needed for local collection,
not for the VPS to receive notifications. An MCP tool may wrap ingestion, but it must reuse the same
validation and persistence path as the API.

## Decisions and open questions

Confirmed: Python, FastAPI, PostgreSQL, Docker Compose, existing VPS, webhooks, Claude Cowork, skills in
this repository, MCP for analysis, and no frontend. Application execution and tests must run in containers.
Python 3.13, PostgreSQL 18 and uv 0.12.23 images are pinned by digest. uv manages `pyproject.toml`
and `uv.lock` entirely inside Docker. SQLAlchemy, Alembic and psycopg are installed for code-first
persistence. FastAPI, Pydantic and Uvicorn provide the API. Caddy, Ruff and pytest remain proposed.

Before live operation, validate browser access and data-use conditions, the complete analyst-rating
capture, alert creation, the price-reference policy, webhook authentication, and Cowork MCP connectivity.
See [integration findings](docs/integrations.md) and [experiment rules](docs/experiment.md).

## Repository map

| Path | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | OpenAI / Codex planning, review and initial setup instructions |
| [CLAUDE.md](CLAUDE.md) | Claude Code implementation instructions |
| [.cursor/rules/project.mdc](.cursor/rules/project.mdc) | Cursor entry point to shared rules |
| [docs/README.md](docs/README.md) | Documentation index |
| [plugin/](plugin/README.md) | Claude plugin manifest, skills and runtime reference |

## Local Docker setup

Requires Docker with Compose v2.20+ and Make. No host Python or PostgreSQL installation is required.

```sh
cp .env.example .env
chmod 600 .env
# Set distinct POSTGRES_PASSWORD, APP_POSTGRES_PASSWORD, API_READER_TOKEN, COLLECTOR_POSTGRES_PASSWORD, API_COLLECTOR_TOKEN, WEBHOOK_TOKEN and WEBHOOK_POSTGRES_PASSWORD values.
# Application passwords and tokens require at least 32 characters.
make db-migrate
make db-access
make up
```

`make help` lists the supported commands. `make package` builds the plugin archive in `dist/` without `.env` or Docker; see [plugin](docs/plugin.md). `make build` builds Python and database tooling; `make test`
checks the schema, infrastructure and API against a disposable database without requiring `.env`. `make down` preserves local data.
PostgreSQL has no published host port; use `make db` for SQL access. The initial schema supports multiple sources and versioned experiments. The code-first workflow is described in
[database design](docs/database.md). See [operations](docs/operations.md) for environment selection and VPS boundaries.

Manage packages with `make uv ARGS="add --no-sync PACKAGE"` or regenerate the lockfile with
`make uv ARGS="lock"`. Then run `make build` to synchronize the image from the lockfile.
No uv installation or virtual environment is needed on the host.

The API listens at `http://127.0.0.1:8000` by default. `/health/live` is public; `/health/ready` and
`/v1/*` require a reader or collector Bearer token. Writes require the collector token.
MCP is available at `/mcp`. See [API contracts](docs/api/README.md) and [MCP tools](docs/api/mcp.md).
The local webhook receiver and recovery procedure are documented in [webhooks](docs/api/webhooks.md).

Structured logs, request/error IDs and authenticated `/metrics` are available locally.
Use `make errors` or `make errors ID=...` to investigate retained events. See [observability](docs/observability.md).

The next step is integration feasibility, followed by small local synthetic increments in
[the roadmap](docs/roadmap.md). Local implementation can proceed independently of blocked provider access.
