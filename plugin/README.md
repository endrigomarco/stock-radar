# Stock Radar plugin

Collects the daily TradingView list of Brazilian biggest losers, with analyst ratings, from the user's own
Chrome in Claude Cowork and registers it in the Stock Radar service through MCP tools. Version 0.3.0.

Status: version 0.2.1 was installed in Cowork by the owner, who saw the four skills and the correct report
of missing MCP tools. Version 0.3.0 adds a local bridge to a disposable sandbox; that bridge has been
checked outside Cowork only. No MCP call from Cowork and no collection against TradingView has been
validated. See `docs/plugin.md` in the repository for the evidence and the open items.

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
- macOS with Node.js 18 or later, so that `npx` can start the pinned proxy `mcp-remote@0.14.3`. The first
  start downloads it from the npm registry.
- The Stock Radar sandbox running on the same computer at `http://127.0.0.1:18001`, started from the
  repository with `make sandbox-up`. The bundled server `stock-radar` runs `mcp/bridge.sh`, which connects
  to that fixed address only.
- A macOS Keychain item named `stock-radar-sandbox-mcp` holding one sandbox token, created with
  `make sandbox-token ROLE=reader`. The package contains no credential. Restart the Claude desktop app
  after every change of that item.
- When the sandbox, Node.js or the Keychain item is missing, the tools are absent and every skill reports
  the connector as unavailable and stops.

## Install

1. From the repository root run `make package`. It writes `dist/stock-radar-<version>.zip` with
   `.claude-plugin/plugin.json` at the root of the archive. It needs no `.env`, Docker or running service.
2. In the Claude desktop app open Customize, Plugins, Add, Upload plugin and select the archive.
3. Open the installed plugin and confirm the four skills are listed.

Installing is not a working connection and creates no credential or schedule. Until the Stock Radar MCP
tools are available in the task, every skill reports the connector as unavailable and stops, without
simulating a collection or a stored result. A connection is proven only by a real tool call, such as
`service_status`, shown in the task.

## Data

The plugin reads one public market list in the user's browser session and sends, for each row, the symbol,
displayed price, daily change, rating label and the displayed text of those cells, plus the page URL and
read times, to the user's own Stock Radar service on the same computer. The bridge downloads the proxy
package from the npm registry and sends nothing else to third parties. The plugin stores nothing itself. It
contains no tokens, database credentials, captures or real observations. The price monitor's brapi key is not needed here.

The example in `skills/collect-signals/references/example-collection.json` is synthetic.
