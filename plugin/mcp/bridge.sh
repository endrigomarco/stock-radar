#!/bin/sh
set -eu
TARGET_URL=http://127.0.0.1:18001/mcp
KEYCHAIN_SERVICE=stock-radar-sandbox-mcp
KEYCHAIN_ACCOUNT=stock-radar
PROXY_PACKAGE=mcp-remote@0.14.3

if ! command -v npx >/dev/null 2>&1; then
    echo "stock-radar bridge: npx was not found in PATH. Install Node.js 18 or later." >&2
    exit 127
fi
if ! token=$(/usr/bin/security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" -w 2>/dev/null) || [ -z "$token" ]; then
    echo "stock-radar bridge: Keychain item $KEYCHAIN_SERVICE was not found or could not be read." >&2
    exit 1
fi
STOCK_RADAR_AUTHORIZATION="Bearer $token"
export STOCK_RADAR_AUTHORIZATION
unset token
exec npx -y "$PROXY_PACKAGE" "$TARGET_URL" --transport http-only --header 'Authorization:${STOCK_RADAR_AUTHORIZATION}'
