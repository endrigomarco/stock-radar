# Technical overview

## Implemented scope

The Docker backend includes REST and MCP interfaces, Pydantic ViewModels, SQLAlchemy entities, ten
normalized tables and Alembic migrations. Shared services register sources, persist collections atomically,
normalize ratings, list signals and report status/data quality. Reader and collector tokens map to separate
restricted database roles. Webhook receipt and processing of existing mappings are implemented with a restricted third database role.
Tracking creation, financial metrics and live integrations remain pending.

## Backend layers

Use a small modular monolith with the flow `controller -> service -> model/entity`. Request and response
ViewModels form the API boundary. This applies the requested MVC separation with ViewModels for the
API; there is no frontend View, client state binding or separate UI MVVM framework.

```text
HTTP request
  -> input ViewModel validation + authentication
  -> controller
  -> service._transform_input()
  -> service operation -> SQLAlchemy entity -> PostgreSQL
  -> service._transform_output()
  -> output ViewModel -> HTTP response
```

| Location | Responsibility |
|---|---|
| `app.py` | Application factory, connection-pool lifecycle, router registration, safe error responses |
| `controllers/` | Routes, HTTP contracts, authentication dependencies, delegation to services |
| `services/` | Use-case orchestration, rules, explicit transformations, queries and transaction boundaries |
| `viewmodels/` | Separate typed input/output contracts, field validation and response shape |
| `db/models.py` | SQLAlchemy entities, relationships and durable database constraints |
| `dependencies.py` | Request-scoped database session injection |
| `security.py` | Reader/collector credential verification |
| `settings.py` | Validated environment configuration without loading local files |

Controllers contain no business calculations or database queries. Services do not depend on FastAPI
Request, Response or HTTPException. SQLAlchemy entities do not import ViewModels or the HTTP framework.
The existing model registry remains in place; splitting ten entities into many files is not required.

SourceService is the first complete example. Its input transformation produces a small immutable query
value and normalizes a supplied source code to lowercase. Its output transformation explicitly selects
`id`, `code` and `name`. The list method performs stable ordering and bounded pagination with one extra
row to compute `has_more`. No ORM objects, internal timestamps or provider URLs escape through that response.
New source-writing workflows must normalize source codes to lowercase consistently.

Use explicit assignments for mappings. Do not add reflection-based mappers, automatic relationship
traversal, BaseController, BaseService, generic repositories, event buses or dependency-injection containers.
Add a repository abstraction only when a concrete persistence use case needs it. Relationships currently
use explicit FKs and queries; automatic ORM relationship expansion is not a serialization strategy.
Operations without meaningful input or output transformations do not need empty mapping methods.

## Validation and transactions

Pydantic validates API input shape, allowed fields, lengths and pagination bounds. ViewModels are distinct
from database entities and expose only the fields that their operation accepts or returns. Cross-record
business rules and financial calculations belong to the service. Database constraints protect persistent
integrity and competing writes. These responsibilities complement each other without duplicating every rule.

The current routes and services use synchronous functions, so FastAPI runs blocking database work outside
its event loop. Each request receives its own Session, closed on completion or error. Read queries do not
commit. Write services own a transaction and return success only after commit. MCP runs the same synchronous services in worker threads.
No service or startup handler creates tables or runs migrations.

The application owns a bounded connection pool, a connection timeout and a database statement timeout.
Shutdown disposes the pool. Configuration is validated at startup; database availability is checked by
protected readiness, independently of process liveness.

## Security and operations

The API receives reader/collector tokens and restricted database passwords, without administrator credentials.
The reader has SELECT and the collector SELECT/INSERT on sources, instruments, collection_runs and
signal_observations. Neither role can update/delete these records or read the tracking/webhook tables. Local HTTP is published on loopback only, with no trusted proxy
headers, wildcard CORS or public interactive documentation. HTTPS and public-ingress controls remain
requirements before an authorized VPS deployment. See [security](security-basic.md).

`make up` builds and starts the API and database. Migrations and reader provisioning remain explicit
operator commands. Tests run against disposable PostgreSQL and use a separate image with test-only
HTTP client dependencies. See [operations](operations.md) and [testing](testing.md).

## Future boundaries

REST and MCP handlers must call the same services. The model extracts observations and explains
verified metrics; backend services own normalization, reference locking, levels and denominators.
TradingView detection, browser collection and webhook delivery remain separate integrations.
Webhook receipts commit before acknowledgement. Post-response processing uses a separate transaction,
and an explicit recovery command retries durable pending/unmapped/failed receipts after interruption. A worker,
queue or new infrastructure dependency should be introduced only when the current use case requires it.

## Observability boundary

`observability/` owns structured logging, per-request correlation, metrics, the HTTP error boundary and
operator log lookup. REST, MCP and webhook/recovery adapters report failures through this shared module.
Operational telemetry is independent of PostgreSQL and persists in a bounded Docker log volume.
No domain schema or external monitoring service is required. See [observability](observability.md).
