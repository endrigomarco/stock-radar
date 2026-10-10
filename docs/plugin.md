# Claude plugin

The plugin root is `plugin/`, not the repository root. Only that directory is packaged. Its manifest is
`plugin/.claude-plugin/plugin.json`; skills are under `plugin/skills/`. Development documents stay outside.

## Current state

Version 0.6.0, prepared on 2026-10-09 for Claude Cowork on the MacBook Pro.

| State | Scope |
|---|---|
| Implemented | Manifest with one local MCP server, the Python bridge in `plugin/mcp/`, four skills with their references, `make package` |
| Tested with synthetic data | The bridge over stdio against a synthetic MCP server: discovery, successful calls, tool errors, refused token, closed port, redirect to another origin, clean diagnostics; in Docker and natively on macOS with Python 3.13 |
| Tested by the owner | Reported on 2026-10-09: version 0.2.1 installed in Cowork with its four skills, and `check-status` reported the MCP tools as absent; from a terminal on the MacBook Pro an authenticated `initialize` to the VPS endpoint over Tailscale returned 200 |
| Not validated | Cowork starting the bridge, tool discovery and any tool call from Cowork, the Keychain read on the MacBook, Python 3.10 to 3.12, Chrome reading of the real table, scheduling |

A terminal test is not evidence about Cowork. Connectivity from Cowork is not validated.

Architecture approved by the owner: Cowork, MCP over stdio, a Python process of the plugin on the MacBook
Pro, HTTPS over Tailscale, the MCP endpoint of the API on the VPS. The backend and PostgreSQL stay on the
VPS. The MacBook needs Python and the bridge dependencies only; no Docker, Node.js, database or local API.

## Skills

| Skill | Role | Tools it expects |
|---|---|---|
| collect-signals | Examine the whole list and register only Strong Buy analyst rows with a negative daily change | `service_status`, `list_sources`, `register_source`, `register_collection`, `get_collection` |
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

- Cowork loads skills, commands, agents, hooks and connectors from a plugin. This plugin uses skills and one
  local MCP server.
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

## Connection: Python bridge

Implemented and checked with synthetic data. Not validated in Cowork.

`plugin/mcp/bridge.py` uses the official MCP Python SDK, pinned to the version the backend uses. It runs a
low-level MCP server on standard input and output and, for every `tools/list` and `tools/call`, opens a
Streamable HTTP client session to the service, forwards the request and returns the service's answer
object unchanged. It has no tools, schemas or business rules of its own and advertises the tools capability
only. Tool arguments are validated by the service, not by the bridge.

| Property | Behaviour |
|---|---|
| Endpoint | Fixed constant in `bridge.py`, required to be `https` without embedded credentials |
| TLS | Certificate validation on; no option to disable it |
| Timeouts | 10 seconds to connect, 60 seconds to read |
| Redirects | The SDK follows a redirect only within the same origin; a redirect elsewhere fails the call and the credential is not sent there |
| Retries | None. One forwarded request per call, so a write is never repeated by the bridge |
| Credential | Reader token read from the Keychain item `stock-radar-mcp`, account `reader`, once at start |
| Failures | Refused token, unreachable service, timeout or redirect become an MCP error with code -32001, never a tool result |
| Tool errors | A result with `isError` from the service is passed through as it is |
| Output | Standard output carries MCP only. Diagnostics go to the error stream and name the kind of failure and the HTTP status, never a token, a header or tool data |

The manifest starts `/bin/sh ${CLAUDE_PLUGIN_ROOT}/mcp/start.sh`. The launcher runs the bridge with the
interpreter at `~/Library/Application Support/stock-radar/bridge/bin/python`, resolved from `$HOME`, so the
package holds no personal path and does not depend on the PATH of the desktop app. When that environment is
missing the launcher says so on the error stream and exits; nothing is installed at start or per call.

Dependencies are in `plugin/mcp/requirements.txt`: `mcp==2.3.0` and its transitive packages, pinned with
hashes. Regenerate it only with
`make uv ARGS="pip compile --universal --python-version 3.10 --generate-hashes --no-header --no-annotate plugin/mcp/requirements.in -o plugin/mcp/requirements.txt"`.
The SDK requires Python 3.10 or later.

The service must list the Host that the bridge presents in `MCP_ALLOWED_HOSTS`; see [MCP](api/mcp.md).
The bridge sends no Origin header.

Because the token is read once at start, a changed Keychain item takes effect after the Claude desktop app
is restarted. Only the reader token is used in this step. With it the service refuses every write with
`forbidden`, so no source, collection or cancellation can be registered in production through the bridge.

### First real test on the MacBook Pro

Steps run by the owner. Record the real results in [testing](testing.md).

1. Prepare the bridge once, as described under Bridge setup in `plugin/README.md`: Python 3.10 or later,
   the dedicated environment, the Keychain item created with the prompting form of `security`, and the
   terminal check `sh /tmp/stock-radar-plugin/mcp/start.sh --check`.
2. In the Claude desktop app open Customize, Plugins, replace the installed `stock-radar` with
   `stock-radar-0.6.0.zip`, then quit and reopen the app.
3. In a new Cowork task ask for a real call of `service_status`.

| Outcome | Criterion |
|---|---|
| Passed | A tool call block for `service_status` with the service version and capabilities |
| Missing setup | The environment, the Keychain item or Tailscale is absent on the MacBook: fix and repeat |
| Attempt failed | Setup complete and the terminal check passes, but the task has no Stock Radar tools. Record whether the task ran in the cloud or on the computer and the app version |
| Inconclusive | A written answer without a tool call block, or an unrelated error |

A failed attempt is recorded as evidence and as a limitation. It does not authorize another architecture
or public exposure of the VPS. Do not register a source or a collection and do not cancel anything in
production in this step.

### What is not established

- Whether a Cowork task on this account receives tools from a local server. The
  [support by app](https://claude.com/docs/plugins/platform-support) table says a local server loads when
  the Cowork session runs on the user's computer;
  [Cowork on web, desktop and mobile](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile)
  says plugins with local MCP servers work through the desktop app, also for sessions in the cloud; the
  [architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)
  says local MCP servers do not run in sessions in the cloud. The owner reported that a shell command of a
  Cowork task ran in the cloud and did not reach the tailnet address, which is consistent with all three.
- Whether the desktop app substitutes `${CLAUDE_PLUGIN_ROOT}` and passes `HOME` for this plugin.
- The state of the VPS beyond the owner's report. Nothing on the VPS was accessed from this repository.
- Scheduled runs. Interactive success would say nothing about them.

A remote connector is not used: it is contacted from Anthropic's cloud and the
[custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
requires a publicly reachable server. Public ingress and OAuth stay out of scope.

### Retired: Node bridge and sandbox

Version 0.3.0 declared a local stdio server that read a token from the macOS Keychain and started
`mcp-remote@0.14.3` through `npx` against a disposable backend on `127.0.0.1:18001`, managed by
`scripts/sandbox.sh` and `make sandbox-*` targets. It worked when driven by hand on the development
machine and was never validated in Cowork. It was removed in 0.4.0 because it made the MacBook depend on
Docker, Node.js and a local database. The records of those checks stay in [testing](testing.md). The Python
bridge above replaces it and uses none of those components.

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

1. Run the first real test above and record the outcome.
2. Confirm the names under which the Stock Radar tools appear in a Cowork task.
3. Decide how the collector token is used for writes, then, with a test service or an explicit decision
   about production, register one synthetic collection, confirm the receipt and repeat it to see
   `duplicate: true`. The packaged example must not be sent as it is: its `source_id` and
   `client_collection_id` are placeholders.
4. Decide whether `prepare-triggers` and `plugin/references/` are removed from the package.
5. Run `collect-signals` interactively once: confirm which column holds the analyst rating, how the full
   list is traversed, the exchange prefix shown for symbols, whether the page states a total and a date, and
   that a session clock and UUID generator are available.
6. Exercise the access pause by starting signed out, then replying `logado`.
7. Resolve the TradingView usage conditions recorded in [integrations](integrations.md) before unattended use.
8. Create the daily scheduled task and observe where it runs and what happens when the Mac is asleep.
