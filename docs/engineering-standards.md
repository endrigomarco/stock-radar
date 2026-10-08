# Engineering standards

Use readable, typed Python with cohesive functions and modules. Apply single responsibility and explicit
dependencies without introducing interfaces or layers solely to satisfy a pattern. Prefer composition.

Follow controller -> service -> model/entity, using separate Pydantic input/output ViewModels.
Service mapping methods use explicit fields, with `_transform_input` and `_transform_output` where
transformations are needed. Keep reflection, generic base classes and automatic ORM serialization out
of the initial architecture. See [technical overview](technical-overview.md).

FastAPI routes and MCP handlers validate transport input and delegate to shared services. Domain calculations
should be deterministic and independently testable. Persistence code owns transactions and parameterized
queries. Do not return ORM objects as public contracts or perform blocking I/O on an async event loop.
SQLAlchemy models define the intended database schema. Generate Alembic revisions from registered
metadata, review them, and apply explicitly. Never create or migrate tables automatically at startup.
The API currently uses synchronous routes and request-scoped SQLAlchemy sessions. Services own write
transactions when write operations are introduced; read requests close their sessions without committing.

Use Decimal for monetary calculations, aware datetime values for instants, explicit enums for rating and
coverage states, and bounded schema validation for external input. Parse localized numbers deliberately.
Unknown rating labels remain unknown rather than defaulting to Strong Buy.

Raise meaningful errors, redact secrets, and log collection/run/receipt IDs for traceability. Use bounded
timeouts and retries only where an idempotency contract makes replay safe. Retry uncertain writes with the
same identity, never a newly generated one that could duplicate a run.

Docker and Compose are required for runtime, tests and migrations. The Makefile owns the small
set of routine commands. Keep image digests reviewed and updated explicitly.

uv 0.12.23 is configured in Docker, with `pyproject.toml` and `uv.lock` intended for version control.
Use `make uv ARGS="add --no-sync PACKAGE"` to add a dependency, then `make build`. Builds use
`uv sync --locked --no-dev` and fail when the lockfile is stale. Do not install packages with pip or
require a host virtual environment. The empty scaffold is not an installable Python package yet.

Proposed tooling: Ruff, pytest and a type checker selected in the first code increment. Add configuration, commands and CI only with executable code. Keep third-party dependencies
minimal and use maintained official SDKs for protocols. Verify current APIs before implementing integrations.
