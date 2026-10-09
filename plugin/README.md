# Stock Radar plugin

Collects the daily TradingView list of Brazilian biggest losers, with analyst ratings, from the user's own
Chrome in Claude Cowork and registers it in the Stock Radar service through MCP tools. Version 0.4.0.

Status: version 0.2.1 was installed in Cowork by the owner, who saw the four skills and the correct report
of missing MCP tools. This version starts no local process and needs nothing installed on the computer
besides the Claude desktop app and Chrome. The Stock Radar service runs on the owner's server and the
connection from Cowork to it is not implemented yet. See `docs/plugin.md` in the repository.

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
- A Stock Radar connector that exposes the service's MCP tools. This package bundles no connector, address
  or credential, and none is configured yet. Until one exists, the tools are absent and every skill reports
  the connector as unavailable and stops.

## Install

1. Take the ready archive `stock-radar-<version>.zip`. It is built on a development machine with
   `make package`; the computer that installs it needs no development tools.
2. In the Claude desktop app open Customize, Plugins, Add, Upload plugin and select the archive.
3. Open the installed plugin and confirm the four skills are listed.

Installing is not a working connection and creates no credential or schedule. Until the Stock Radar MCP
tools are available in the task, every skill reports the connector as unavailable and stops, without
simulating a collection or a stored result. A connection is proven only by a real tool call, such as
`service_status`, shown in the task.

## Data

The plugin reads one public market list in the user's browser session and sends, for each row, the symbol,
displayed price, daily change, rating label and the displayed text of those cells, plus the page URL and
read times, to the user's own Stock Radar service, once a connector exists. The plugin stores nothing itself,
downloads nothing and starts no program. It contains no tokens, database credentials, captures or real
observations. The price monitor's brapi key is not needed here.

The example in `skills/collect-signals/references/example-collection.json` is synthetic.
