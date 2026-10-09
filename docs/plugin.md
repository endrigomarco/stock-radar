# Claude plugin

The plugin root is `plugin/`, not the repository root. Only that directory is packaged. Its manifest is
`plugin/.claude-plugin/plugin.json`; skills are under `plugin/skills/`. Development documents stay outside.

## Current state

Version 0.4.0, prepared on 2026-10-09 for Claude Cowork on the MacBook Pro.

| State | Scope |
|---|---|
| Prepared in the repository | Manifest, four skills with their references, `make package` |
| Checked statically | Manifest without local servers, archive contents, plugin validator |
| Tested by the owner in Cowork on the MacBook Pro | Reported on 2026-10-09 for version 0.2.1: the plugin installed and was enabled, the interface listed its nine files and four skills, and `check-status` reported that the MCP tools were absent without claiming backend access or changed records |
| Not validated | Any MCP connection from Cowork, a synthetic collection from Cowork, Chrome reading of the real table, scheduling, any VPS operation |

Installation and the behaviour without a connection are validated by the owner's test. Connectivity is not.

Architecture decision by the owner: the backend and PostgreSQL run on the VPS. The MacBook Pro runs the
Claude desktop app, Cowork and this plugin only. Using the plugin must not require Docker, Node.js, a local
database or any start script on the MacBook. Docker remains the runtime for development and for the VPS.

## Skills

| Skill | Role | Tools it expects |
|---|---|---|
| collect-signals | Browser observations and one additive collection | `service_status`, `list_sources`, `register_source`, `register_collection`, `get_collection` |
| check-status | Read service, receipts, quality counts and tracking state | `service_status`, `data_quality_report`, `get_collection`, tracking list tools |
| analyze-results | Describe stored signals, runs and hits | `list_signals`, tracking list tools |
| prepare-triggers | Read tracking runs; cancel one on explicit request | `list_tracking_runs`, `cancel_tracking_run` |

The backend creates or reuses tracking runs when an eligible observation is registered, and the monitor on
the server sets references and records hits. No skill prepares levels, supplies a reference or creates
provider alerts. `prepare-triggers` prepares nothing: it reads tracking runs and is the only skill that may
call `cancel_tracking_run`, on explicit request; removing it is a pending decision. There are no computed performance metrics, so `analyze-results`
is limited to the list tools.

Each skill keeps the rules it needs inside its own folder, following the documented layout
`skills/<name>/SKILL.md` with `references/` beside it. `plugin/references/runtime-contract.md` is a summary
that no skill depends on, because reading files outside a skill folder is not documented for Cowork.
`collect-signals/references/collection-contract.md` mirrors `src/stock_radar/viewmodels/collections.py`;
update it with any contract change. Do not make skills depend on `docs/`.

## Packaging

Format checked against the official documentation on 2026-10-09:
[plugins overview](https://claude.com/docs/plugins/overview),
[plugin structure and testing](https://claude.com/docs/plugins/build),
[support by app](https://claude.com/docs/plugins/platform-support),
[custom skills](https://claude.com/docs/skills/how-to).

- Cowork loads skills, commands, agents, hooks and connectors from a plugin. This plugin uses skills only.
- Upload accepts a folder archived as `.zip` or `.plugin` holding one `.claude-plugin/plugin.json`, either
  at the archive root or inside a single top-level folder. Limits are 200 MB and 5,000 files.
- A top-level `bin/` directory blocks installation in Cowork. `${user_config.*}` values are not prompted
  for in Cowork. Neither is used.

Build the archive from the repository root with `make package`, which runs `scripts/package-plugin.sh`.
It reads the version from the manifest, deletes any archive of that version and writes a new
`dist/stock-radar-<version>.zip` from scratch, then lists its contents. It needs no `.env`, Docker or
running service. Only files under `plugin/` that Git tracks or would track are included, so anything matched
by `.gitignore`, such as `.env` files, keys and `.DS_Store`, is left out. `dist/` is ignored by Git, so the
archive is always built locally and never pulled.

```sh
make package
claude plugin validate ./plugin
```

Archives of earlier versions left in `dist/` are outdated and must not be uploaded.

## Installing a ready archive

The MacBook Pro needs no development tools. Build the archive on a development machine with
`make package`, copy `dist/stock-radar-0.4.0.zip` to the MacBook and, in the Claude desktop app, open
Customize, Plugins, remove or replace the installed `stock-radar` version and upload the new archive.
Then quit and reopen the app and confirm that version 0.4.0 lists the four skills.

Expected result in a new Cowork task: `check-status` reports the connector as unavailable and stops. No
tool call to Stock Radar can appear, because no connector exists.

## Connection: pending

Not implemented and not decided. This version connects Cowork to nothing.

Established facts:

- The service speaks Streamable HTTP with a static Bearer token per role and has no OAuth. `compose.yaml`
  publishes the API on the loopback of whatever host runs it. This repository records no VPS deployment
  and none was verified in this work; see [operations](operations.md).
- A remote connector, whether added as a custom connector or declared as an `http` entry in a plugin, is
  contacted from Anthropic's cloud in every client, Cowork included. The
  [custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
  requires a server reachable from the public internet and says servers behind a VPN do not connect. Fixed
  request headers for static credentials are documented there as a beta for a limited set of organizations.
- Reported by the owner on 2026-10-09, not verified from this repository: the API runs on the VPS in the
  Compose project `stock-radar-production`, published on `127.0.0.1:8001`, and Tailscale Serve forwards
  HTTPS on port 8444 of the server's tailnet name to it. From the MacBook Pro `/health/live` returned 200,
  `/health/ready` and `/mcp` returned 401 without a token, `/health/ready` returned 200 with the reader
  token, and an authenticated MCP `initialize` returned 421 `Invalid Host header`.
- That 421 is the Host check of the MCP SDK. The API now accepts exact extra Host values through
  `MCP_ALLOWED_HOSTS`; see [MCP](api/mcp.md). The setting is implemented and tested locally with synthetic
  hosts. It has not been applied to the VPS.
- A tailnet address is reachable from the owner's devices. It does not show that a process running in
  Anthropic's cloud can reach the VPS.
- A plugin can also declare a local server that the desktop app starts on the MacBook. That path was
  implemented once and retired, see below, because it required supporting software on the MacBook.

No connection path is chosen. A public connector, OAuth, an additional tunnel or another bridge must not be
introduced without a decision by the owner. Until a connector exists, every skill reports the connector as
unavailable and stops, without simulating a collection or a stored result.

### Retired: local bridge and sandbox

Version 0.3.0 declared a local stdio server that read a token from the macOS Keychain and started
`mcp-remote@0.14.3` through `npx` against a disposable backend on `127.0.0.1:18001`, managed by
`scripts/sandbox.sh` and `make sandbox-*` targets. It worked when driven by hand on the development
machine and was never validated in Cowork. It was removed in 0.4.0 because it made the MacBook depend on
Docker, Node.js and a local database. The records of those checks stay in [testing](testing.md).

### Optional cleanup of sandbox leftovers

Only for a machine where the sandbox was started. Nothing here is run automatically, and nothing here
touches the main installation, whose Compose projects have other names. Do not uninstall Docker, Node.js
or Tailscale for this. Inspect first, then remove only what the listing shows.

```sh
docker ps -a --filter label=com.docker.compose.project=stock-radar-sandbox
docker volume ls --filter label=com.docker.compose.project=stock-radar-sandbox
docker network ls --filter label=com.docker.compose.project=stock-radar-sandbox
```

```sh
docker ps -aq --filter label=com.docker.compose.project=stock-radar-sandbox | xargs docker rm -f
docker volume ls -q --filter label=com.docker.compose.project=stock-radar-sandbox | xargs docker volume rm
docker network ls -q --filter label=com.docker.compose.project=stock-radar-sandbox | xargs docker network rm
rm -f .env.sandbox
security delete-generic-password -s stock-radar-sandbox-mcp -a stock-radar
```

When a listing was empty, the matching removal command does nothing or reports a missing argument. The last command
removes only the Keychain item `stock-radar-sandbox-mcp` and fails harmlessly when it does not exist.
The proxy may also have left a copy in the npm cache and an empty `~/.mcp-auth` folder; both are shared
with other uses of npm and may be left alone.

## Scheduling: not configured

The owner will create a daily scheduled task in Cowork that asks for the `collect-signals` skill.
[Scheduled tasks](https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork)
are documented as running remotely by default, with tasks that need local files or apps running locally.
The documentation does not say whether a scheduled run can drive Chrome on the MacBook. Treat this as
unverified: assume the Mac must be awake, with the desktop app and Chrome open and TradingView signed in.

When login is missing the skill stops and asks for the reply `logado`. That is a conversational pause. A
scheduled run that receives no reply ends without registering anything; nothing polls or waits in the
background. Do not label a previous session's list as today's.

## Pending items to connect and test in Cowork

1. Replace version 0.3.0 with the 0.4.0 archive and confirm the four skills and the unavailable report.
2. Decide and implement the connection from Cowork to the service on the VPS. Nothing is chosen.
3. Confirm the names under which the Stock Radar tools appear in a Cowork task.
4. With a test service, register one synthetic collection, confirm the receipt and repeat it to see
   `duplicate: true`. The packaged example must not be sent as it is: its `source_id` and
   `client_collection_id` are placeholders.
5. Decide whether `prepare-triggers` and `plugin/references/` are removed from the package.
6. Run `collect-signals` interactively once: confirm which column holds the analyst rating, how the full
   list is traversed, the exchange prefix shown for symbols, whether the page states a total and a date, and
   that a session clock and UUID generator are available.
7. Exercise the access pause by starting signed out, then replying `logado`.
8. Resolve the TradingView usage conditions recorded in [integrations](integrations.md) before unattended use.
9. Create the daily scheduled task and observe where it runs and what happens when the Mac is asleep.
