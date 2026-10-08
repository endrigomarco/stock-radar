# Roadmap

## 0. Documentation, instructions and Docker infrastructure (current state)

README, agent and Cursor instructions, domain and integration documents, plugin manifest and draft skills.
Dockerfile, Compose, an environment template and a selective Makefile now support an empty PostgreSQL
database and Python runtime. uv, a dependency manifest and generated lockfile are configured inside
Docker. SQLAlchemy, psycopg and Alembic provide ten normalized tables and an initial migration.
The schema supports multiple sources and experiment versions without implementing their services. Infrastructure checks use a disposable project. No live data, installed
plugin or VPS deployment. OpenAI / Codex handles planning and review, with the
current setup-edit exception; Claude Code owns ongoing implementation as defined in the root agent files.

The backend now uses controller/service/entity layers with input/output ViewModels. A read-only source
listing and health endpoints validate the architecture, with reader authentication and a restricted
database role. Collection persistence and local REST/MCP tools are now implemented; live provider workflows remain pending.

## 1. Integration feasibility

Validate the actual Cowork browser and MCP capabilities, the complete analyst-rating capture, permitted
collection/storage use, TradingView plan/real-time entitlement and compatible webhook authentication.
Choose reference acquisition, session/window rules and alert activation semantics. Record observed evidence,
not assumptions. A provider blocker does not prevent developing the local synthetic increments below.

## 2. Collection persistence (implemented locally)

FastAPI and MCP share authenticated atomic ingestion/read-back against PostgreSQL, with synthetic tests. Acceptance: original labels and server normalization are preserved, partial traversal is
explicit, duplicate submission returns the original receipt, and changed content with the same identity
is rejected. Select/pin tooling and add setup commands and focused CI for this capability only.
No tracking engine, webhook receiver or full analytical tool catalog is required for this step.

## 3. Tracking and webhook receipt (receiver/processor implemented locally)

Durable webhook receipt, deduplication, mapping validation and first-event processing are implemented
against existing schema records. Tracking creation with a versioned experiment, immutable reference and
six levels is implemented by the quote polling increment below. Use synthetic messages. Acceptance: retries cannot create duplicate runs or hits; unmapped events
remain identifiable; committed pending receipts survive restart; network arrival order does not substitute
for event evidence. Select only the session/reference rules needed by this increment.

## 3a. brapi quote polling (implemented locally, live provider unverified)

Eligible observations create or reuse one open tracking run per instrument and experiment. A single Docker
process polls brapi every 30 minutes during B3 sessions for at most 30 instruments, locks the reference at
the first valid quote, creates six levels, records first observed hits and ends runs by completion, expiry
or cancellation. REST and MCP expose runs, latest quotes, hits and cancellation. Validated with a fake
provider and disposable PostgreSQL only. Pending: a first authorized live cycle from the container, the 2027
calendar, confirmation of B3 hours after the next change, and deployment. External webhooks are deferred.

## 4. MCP and plugin connection

The local read tools and authorized ingestion path exist. Cowork connection and plugin authentication
remain unverified. Connect the plugin to an authorized test service.
Acceptance: Cowork submits a synthetic list, reads it back and explains stored events with coverage limits.
Missing tools and failed writes are reported accurately. Validate the actual distributable plugin and
its authentication. Add aggregate and comparison tools incrementally when their inputs are available.

## 5. VPS pilot

After deployment is authorized, use three actual instruments and manually configured alerts under verified
provider conditions. Confirm activation, receive events, compare provider history and inspect durable data.
Live events validate transport and mappings; they do not prove the investment hypothesis. Check backup
restore and the existing VPS workloads before relying on unattended operation.

## 6. Daily operation and evaluation

Configure daily scheduling for the agreed time and market sessions. The user wants daily collection;
exact scheduling and missed-run handling still need configuration. Collect mature cohorts and distinguish
observed notification counts from metrics that require independently verified coverage. Polled quotes give
partial coverage only; add price history when needed for reconciliation, fixed-horizon returns and excursion metrics.

## Deferred

Additional platforms, chart-image interpretation, author-level recommendations and script backtesting.
Pine Script requires its own execution or validated conversion path; Python does not run it natively.
No frontend, Redis, multi-user SaaS or generalized strategy engine is required for these initial milestones.
