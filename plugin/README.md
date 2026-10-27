# Stock Radar plugin

Reads the whole daily TradingView list of Brazilian biggest losers in the user's own Chrome in Claude
Cowork and registers in the Stock Radar service, through MCP tools, only the stocks whose analyst rating
is `Viés de alta forte` and whose daily change is negative, as candidates. Other rows are counted and not
stored. The `select-candidates` skill then researches the candidates and confirms at most three new ones per
session for tracking, with recorded justifications. The daily report opens with a simulated portfolio per
collection date. Version 0.10.0.

Status: version 0.2.1 was installed in Cowork by the owner, who saw the four skills and the correct report
of missing MCP tools. Version 0.5.0 adds a local Python bridge to the owner's Stock Radar service. The
bridge passed synthetic checks outside Cowork. Whether Cowork starts it, and any tool call from Cowork, is
not validated yet. See `docs/plugin.md` in the repository.

## Skills

| Skill | What it does |
|---|---|
| `collect-signals` | Examines the whole losers table in Chrome, keeps the Strong Buy analyst rows with a negative daily change, builds one collection payload and calls `register_collection`. Confirms the result from the receipt. |
| `select-candidates` | Reads the pending candidates of a session, researches public context in Chrome, ranks them and calls `confirm_selection`. Records justifications, risks and unavailable information. No trading, no probabilities. |
| `check-status` | Read-only view of service availability, collection receipts, quality counts and tracking state. |
| `analyze-results` | Read-only description of stored signals, runs and recorded hits. No computed performance metrics exist yet. |
| `daily-report` | Read-only end of day report computed by the service. It starts with the simulated 100,000 BRL portfolio of each collection date under nine exit strategies (A to I) and holding, in a compact table per date, with results, cash, equity, triggers and limits; the technical milestones and hit rates follow on request. No orders, not real time. |
| `prepare-triggers` | View of tracking runs, plus cancellation of one run on explicit request. Tracking is prepared by the backend; this skill prepares nothing. |

Ask for the task in plain language, or type `/stock-radar:` and choose the skill.

## Requirements

- Claude desktop app with Cowork on the MacBook, and the Claude in Chrome integration.
- The identifier of the Chrome on the MacBook Pro given explicitly in the request or the scheduled task
  text. The skills never choose a browser by name, order or because it is the only one connected, work
  only in tabs they create and close only those. The Chrome profile may be shared; no exclusive use of
  the browser is enforced.
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
   `unzip -o -q stock-radar-0.10.0.zip -d /tmp/stock-radar-plugin`
3. Create the dedicated environment and install the pinned, hash-checked dependencies:
   `python3 -m venv "$HOME/Library/Application Support/stock-radar/bridge"`
   `"$HOME/Library/Application Support/stock-radar/bridge/bin/python" -m pip install --require-hashes --only-binary :all: -r /tmp/stock-radar-plugin/mcp/requirements.txt`
4. Store the reader token. The command asks for the value, so it stays out of arguments and shell history:
   `security add-generic-password -U -s stock-radar-mcp -a reader -w`
5. Check from a terminal: `sh /tmp/stock-radar-plugin/mcp/start.sh --check`. Expected on the error stream:
   `check passed`, with the number of tools. This proves the terminal path only, not Cowork.

Registering a collection and confirming a selection are writes and need a token with collector access.
The account name of the Keychain item does not establish which token it holds or what it may do; only a
real call shows it. Restart the Claude desktop app after changing the Keychain item. To remove the setup, delete the folder
`~/Library/Application Support/stock-radar` and the Keychain item `stock-radar-mcp`.

## Install

1. Take the ready archive `stock-radar-<version>.zip`. It is built on a development machine with
   `make package`; the computer that installs it needs no development tools.
2. In the Claude desktop app open Customize, Plugins, Add, Upload plugin and select the archive.
3. Open the installed plugin and confirm the six skills are listed.

Installing is not a working connection and creates no credential or schedule. A connection is proven only
by a real tool call, such as `service_status`, shown in a Cowork task. Until the tools are available, every
skill reports the connector as unavailable and stops, without simulating a collection or a stored result.

## Data

The plugin reads one public market list in the user's browser session and sends, for each qualified row, the symbol,
displayed price, daily change, rating label, volume and sector when shown, and the displayed text of those
cells, plus the page URL and read times, to the user's own Stock Radar service through the bridge. For the
selection it opens public pages such as company notices and news and sends their URL, publisher, dates and a
short summary with each decision. The plugin stores nothing itself and
downloads nothing at run time. It contains no tokens, database credentials, captures or real observations. The price monitor's brapi key is not needed here.

The examples in `skills/collect-signals/references/example-collection.json` and
`skills/select-candidates/references/example-selection.json` are synthetic.
