SHELL := /bin/sh
.DEFAULT_GOAL := help
ENV_FILE ?= .env
ARGS ?= --version
COMPOSE = docker compose --env-file "$(ENV_FILE)"

export ERROR_LOOKUP_ID = $(ID)

.PHONY: errors webhooks-process monitor-once help config build up down status logs db test uv db-revision db-migrate db-check db-access

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  make %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf '\nSelect configuration with ENV_FILE=/path/to/file. Docker Compose v2+ required.\n'

config: ## Validate configuration without printing secrets
	@$(COMPOSE) config --quiet

build: ## Build the Python runtime and database tooling, without a local environment file
	docker build --target runtime --tag stock-radar-python:local .

up: config build ## Start the API and PostgreSQL and wait for process health
	$(COMPOSE) up --detach --wait --wait-timeout 90 postgres api

down: ## Stop containers and preserve the database volume
	$(COMPOSE) down

status: ## Show service status
	$(COMPOSE) ps --all

logs: ## Follow the last 100 lines of service logs
	$(COMPOSE) logs --follow --tail 100

db: ## Open psql inside the running database container
	$(COMPOSE) exec postgres sh -c 'exec psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

test: ## Test infrastructure, schema, REST and MCP in a disposable project
	@sh scripts/test-infra.sh

uv: ## Run uv in Docker, e.g. make uv ARGS="lock"
	docker build --target tooling --tag stock-radar-tooling:local .
	docker run --rm --user "$$(id -u):$$(id -g)" \
		--env HOME=/tmp --env UV_PROJECT_ENVIRONMENT=/tmp/stock-radar-venv \
		--mount "type=bind,source=$(CURDIR),target=/app" \
		stock-radar-tooling:local uv $(ARGS)

db-revision: config build ## Generate a migration from models; requires MESSAGE="description"
	@test -n "$(MESSAGE)" || { echo 'Set MESSAGE="describe the schema change".'; exit 1; }
	$(COMPOSE) run --rm --user "$$(id -u):$$(id -g)" \
		--volume "$(CURDIR)/migrations:/app/migrations" \
		migrations revision --autogenerate -m "$(MESSAGE)"

db-migrate: config build ## Apply reviewed pending migrations to the selected database
	$(COMPOSE) run --rm migrations upgrade head

db-check: config build ## Check for model/schema drift without applying migrations
	$(COMPOSE) run --rm migrations check

db-access: config build ## Configure reader, collector and webhook roles after migrations
	$(COMPOSE) run --rm --entrypoint python migrations -m stock_radar.db.provision

webhooks-process: config ## Retry a bounded batch of pending, unmapped and failed webhook receipts
	$(COMPOSE) exec -T api python -m stock_radar.webhooks $(ARGS_WEBHOOKS)

monitor-once: config build ## Run one quote monitoring cycle; requires MONITOR_ENABLED=true and BRAPI_API_KEY
	$(COMPOSE) run --rm monitor python -m stock_radar.monitor --once

errors: config ## Show retained warnings/errors, or find a request/error/receipt with ID=...
	$(COMPOSE) run --rm --no-deps errors
