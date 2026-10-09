#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
SANDBOX_ENV_FILE=.env.sandbox
SANDBOX_PROJECT=stock-radar-sandbox
SANDBOX_PORT=18001
KEYCHAIN_SERVICE=stock-radar-sandbox-mcp
KEYCHAIN_ACCOUNT=stock-radar

unset MAKEFLAGS MFLAGS MAKEOVERRIDES COMPOSE_FILE COMPOSE_PROFILES COMPOSE_ENV_FILES
export COMPOSE_PROJECT_NAME="$SANDBOX_PROJECT"
export API_PORT="$SANDBOX_PORT"
export MONITOR_ENABLED=false
export BRAPI_API_KEY=

usage() {
    echo "Usage: sh scripts/sandbox.sh up|down|destroy|status|keychain reader|keychain collector" >&2
    exit 2
}

compose() {
    docker compose --project-name "$SANDBOX_PROJECT" --env-file "$SANDBOX_ENV_FILE" "$@"
}

sandbox_make() {
    make "$1" ENV_FILE="$SANDBOX_ENV_FILE" COMPOSE_PROJECT_NAME="$SANDBOX_PROJECT"
}

random_secret() {
    openssl rand -hex 32
}

require_env_file() {
    if [ ! -f "$SANDBOX_ENV_FILE" ]; then
        echo "$SANDBOX_ENV_FILE does not exist. Run: make sandbox-up" >&2
        exit 1
    fi
}

create_env_file() {
    if [ -f "$SANDBOX_ENV_FILE" ]; then
        return
    fi
    (
        umask 077
        {
            echo "COMPOSE_PROJECT_NAME=$SANDBOX_PROJECT"
            echo "POSTGRES_USER=stock_radar_sandbox"
            echo "POSTGRES_DB=stock_radar_sandbox"
            echo "POSTGRES_PASSWORD=$(random_secret)"
            echo "APP_POSTGRES_PASSWORD=$(random_secret)"
            echo "COLLECTOR_POSTGRES_PASSWORD=$(random_secret)"
            echo "WEBHOOK_POSTGRES_PASSWORD=$(random_secret)"
            echo "MONITOR_POSTGRES_PASSWORD=$(random_secret)"
            echo "API_READER_TOKEN=$(random_secret)"
            echo "API_COLLECTOR_TOKEN=$(random_secret)"
            echo "WEBHOOK_TOKEN=$(random_secret)"
            echo "API_PORT=$SANDBOX_PORT"
            echo "MONITOR_ENABLED=false"
            echo "MONITOR_MAX_INSTRUMENTS=1"
            echo "BRAPI_API_KEY="
        } > "$SANDBOX_ENV_FILE"
    )
    echo "Created $SANDBOX_ENV_FILE with new random credentials."
}

api_is_running() {
    [ -n "$(compose ps --quiet --status running api 2>/dev/null)" ]
}

check_port() {
    if api_is_running; then
        return
    fi
    if lsof -nP -iTCP:"$SANDBOX_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "Port $SANDBOX_PORT is already in use by another process. Nothing was started." >&2
        lsof -nP -iTCP:"$SANDBOX_PORT" -sTCP:LISTEN >&2
        exit 1
    fi
}

sandbox_up() {
    create_env_file
    check_port
    sandbox_make db-migrate
    sandbox_make db-access
    sandbox_make up
    echo "Sandbox API listens on http://127.0.0.1:$SANDBOX_PORT. The monitor is not started."
}

sandbox_down() {
    require_env_file
    compose down
}

sandbox_destroy() {
    if [ -f "$SANDBOX_ENV_FILE" ]; then
        compose down --volumes --remove-orphans
        rm -f "$SANDBOX_ENV_FILE"
    fi
    if security delete-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" >/dev/null 2>&1; then
        echo "Removed Keychain item $KEYCHAIN_SERVICE."
    fi
    echo "Sandbox containers, volumes, credentials file and Keychain item are removed."
}

sandbox_status() {
    require_env_file
    compose ps --all
}

store_token() {
    require_env_file
    case "$1" in
        reader) variable=API_READER_TOKEN ;;
        collector) variable=API_COLLECTOR_TOKEN ;;
        *) usage ;;
    esac
    token=$(sed -n "s/^$variable=//p" "$SANDBOX_ENV_FILE" | head -n 1)
    if [ -z "$token" ]; then
        echo "$variable is missing from $SANDBOX_ENV_FILE." >&2
        exit 1
    fi
    case "$token" in
        *[!0-9A-Za-z]*)
            echo "$variable has unexpected characters. Recreate the sandbox credentials." >&2
            exit 1
            ;;
    esac
    security -i >/dev/null <<KEYCHAIN_COMMANDS
add-generic-password -U -s $KEYCHAIN_SERVICE -a $KEYCHAIN_ACCOUNT -w $token
KEYCHAIN_COMMANDS
    stored=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" -w 2>/dev/null || true)
    if [ "$stored" != "$token" ]; then
        echo "Keychain item $KEYCHAIN_SERVICE could not be written or read back." >&2
        exit 1
    fi
    unset stored token
    echo "Keychain item $KEYCHAIN_SERVICE now holds the sandbox $1 token. Restart the Claude desktop app."
}

case "${1:-}" in
    up) sandbox_up ;;
    down) sandbox_down ;;
    destroy) sandbox_destroy ;;
    status) sandbox_status ;;
    keychain) store_token "${2:-}" ;;
    *) usage ;;
esac
