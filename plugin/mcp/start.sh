#!/bin/sh
set -eu
BRIDGE_PYTHON="$HOME/Library/Application Support/stock-radar/bridge/bin/python"
if [ ! -x "$BRIDGE_PYTHON" ]; then
    echo "stock-radar-bridge: the Python environment at $BRIDGE_PYTHON is missing. Prepare it once as described in the plugin README." >&2
    exit 1
fi
exec "$BRIDGE_PYTHON" -I -B "$(dirname "$0")/bridge.py" "$@"
