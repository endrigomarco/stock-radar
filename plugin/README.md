# Stock Radar plugin

Collects the daily TradingView list of Brazilian biggest losers, with analyst ratings, from the user's own
Chrome in Claude Cowork and registers it in the Stock Radar service through MCP tools. Version 0.5.0.

Status: version 0.2.1 was installed in Cowork by the owner, who saw the four skills and the correct report
of missing MCP tools. Version 0.5.0 adds a local Python bridge to the owner's Stock Radar service. The
bridge passed synthetic checks outside Cowork. Whether Cowork starts it, and any tool call from Cowork, is
not validated yet. See `docs/plugin.md` in the repository.

## Skills

| Skill | What it does |
|---|---|
| `collect-signals` | Reads the losers table in Chrome, builds one collection payload and calls `register_collection`. Confirms the result from the receipt. |
| `check-status` | Read-only view of service availability, collection receipts, quality counts and tracking state. |
| `analyze-results` | Read-only description of stored signals, runs and recorded hits. No computed performance metrics exist yet. |
| `prepare-triggers` | View of tracking runs, plus cancellation of one run on explicit request. Tracking is prepared by the backend; this skill prepares nothing. |

Ask for the task in plain language, or type `/stock-radar:` and choose the skill.

## Requirements

- Claude desktop app with Cowork on the MacBook, and the Claude in Chrome integration.
- Chrome open with TradingView signed in. The skill never types credentials or solves captchas. When access
  is missing it stops, explains what it saw and waits for the reply `logado` before checking again.
- Tailscale connected on the same computer, with access to the owner's Stock Radar service.
- The bridge environment and the Keychain item described under Bridge setup. When either is missing, when
  the service cannot be reached or when the token is refused, the tools are absent or fail, and every skill
  reports the connector as unavailable and stops.

## Bridge

The manifest declares one local MCP server, `stock-radar`. The Claude desktop app starts
`mcp/start.sh`, which runs `mcp/bridge.py` with a dedicated Python environment. The bridge speaks MCP over
standard input and output and forwards tool discovery and tool calls to the service's own MCP endpoint
over HTTPS, with certificate validation and timeouts. It implements no tool itself: names, descriptions,
schemas, structured content and error flags come from the service unchanged. It never retries a call. A
failed connection, a refused token or a redirect to another host becomes an MCP error, never a result.

The endpoint is fixed in `mcp/bridge.py`. The token is read from the macOS Keychain when the bridge
starts and is not in the package, in arguments or in diagnostics. Diagnostics go to the error stream.

## Bridge setup

Once per computer. Nothing is installed at start or per call.

1. Check for Python 3.10 or later: `python3 --version`. If it is missing or older, install a current
   Python from python.org first. No other tool is required.
2. Extract the archive to a temporary folder, to reach the bridge files:
   `unzip -o -q stock-radar-0.5.0.zip -d /tmp/stock-radar-plugin`
3. Create the dedicated environment and install the pinned, hash-checked dependencies:
   `python3 -m venv "$HOME/Library/Application Support/stock-radar/bridge"`
   `"$HOME/Library/Application Support/stock-radar/bridge/bin/python" -m pip install --require-hashes --only-binary :all: -r /tmp/stock-radar-plugin/mcp/requirements.txt`
4. Store the reader token. The command asks for the value, so it stays out of arguments and shell history:
   `security add-generic-password -U -s stock-radar-mcp -a reader -w`
5. Check from a terminal: `sh /tmp/stock-radar-plugin/mcp/start.sh --check`. Expected on the error stream:
   `check passed`, with the number of tools. This proves the terminal path only, not Cowork.

Restart the Claude desktop app after changing the Keychain item. To remove the setup, delete the folder
`~/Library/Application Support/stock-radar` and the Keychain item `stock-radar-mcp`.

## Install

1. Take the ready archive `stock-radar-<version>.zip`. It is built on a development machine with
   `make package`; the computer that installs it needs no development tools.
2. In the Claude desktop app open Customize, Plugins, Add, Upload plugin and select the archive.
3. Open the installed plugin and confirm the four skills are listed.

Installing is not a working connection and creates no credential or schedule. A connection is proven only
by a real tool call, such as `service_status`, shown in a Cowork task. Until the tools are available, every
skill reports the connector as unavailable and stops, without simulating a collection or a stored result.

## Data

The plugin reads one public market list in the user's browser session and sends, for each row, the symbol,
displayed price, daily change, rating label and the displayed text of those cells, plus the page URL and
read times, to the user's own Stock Radar service through the bridge. The plugin stores nothing itself and
downloads nothing at run time. It contains no tokens, database credentials, captures or real observations. The price monitor's brapi key is not needed here.

The example in `skills/collect-signals/references/example-collection.json` is synthetic.
