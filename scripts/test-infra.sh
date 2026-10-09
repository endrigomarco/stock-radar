#!/bin/sh
# Synthetic infrastructure and migration checks only.
set -eu
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d)
test_project="stock-radar-test-$(basename "$test_dir" | tr '[:upper:].' '[:lower:]-')"
compose() {
    docker compose --env-file "$test_dir/env" --project-name "$test_project" -f compose.yaml "$@"
}
cleanup() {
    result=$?
    trap - EXIT
    compose down --volumes --remove-orphans || result=1
    rm -rf "$test_dir"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Override ambient credentials as well as the local .env for this isolated run.
export POSTGRES_USER=stock_radar_test POSTGRES_DB=stock_radar_test
POSTGRES_PASSWORD=$(docker run --rm --network none python:3.13-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c python -c 'import secrets; print(secrets.token_hex(32))')
export POSTGRES_PASSWORD
export WEBHOOK_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export WEBHOOK_TOKEN=synthetic-webhook-token-for-isolated-tests-only
export COLLECTOR_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export API_COLLECTOR_TOKEN=synthetic-collector-token-for-isolated-tests-only
export APP_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export MONITOR_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
export MONITOR_ENABLED=false BRAPI_API_KEY=
export API_READER_TOKEN=synthetic-reader-token-for-isolated-tests-only
export MCP_ALLOWED_HOSTS=
: > "$test_dir/env"
compose config --quiet
compose build python
compose run --rm --no-deps python uv lock --check --offline
compose up --detach --wait --wait-timeout 90 postgres
compose run --rm --no-deps python python -c 'import os, socket; assert os.getuid() != 0; socket.create_connection(("postgres", 5432), timeout=5).close(); print("Non-root Python runtime and database connectivity passed.")'
compose run --rm --no-deps --entrypoint python \
    --volume "$(pwd)/tests:/checks:ro" migrations /checks/check_migrations.py
compose build tests
compose run --rm --no-deps --entrypoint python migrations -m stock_radar.db.provision
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_api.py
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_workflows.py
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_transport.py
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_webhooks.py
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_observability.py
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_monitoring.py
# Authenticate over TCP, write synthetic data, then recreate the container to
# verify persistence. Cleanup removes only this unique test project and volume.
compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
CREATE TABLE infrastructure_probe (value integer NOT NULL);
INSERT INTO infrastructure_probe VALUES (42);
SQL
compose up --detach --force-recreate --wait --wait-timeout 90 postgres
value=$(compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT value FROM infrastructure_probe"')
[ "$value" = 42 ]
compose run --rm --no-deps --volume "$(pwd)/tests:/checks:ro" tests /checks/check_webhooks.py --recover
printf 'Infrastructure checks passed, including persistence after container recreation.\n'
