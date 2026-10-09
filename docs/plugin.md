# Claude plugin

The plugin root is `plugin/`, not the repository root. Only that directory is packaged. Its manifest is
`plugin/.claude-plugin/plugin.json`; skills are under `plugin/skills/`. Development documents stay outside.

## Current state

Version 0.3.0, prepared on 2026-10-09 for collection by Claude Cowork on the MacBook Pro.

| State | Scope |
|---|---|
| Prepared in the repository | Manifest with a bundled local bridge, four skills with their references, `make package`, the disposable sandbox procedure |
| Checked on the development machine | Manifest and archive checks; the pinned proxy driven over stdio against the sandbox, outside any Claude client and with the token taken from the environment instead of the Keychain: 11 tools listed, `service_status` answered, `register_source` refused with `forbidden` under the reader token |
| Tested by the owner in Cowork on the MacBook Pro | Reported on 2026-10-09 for version 0.2.1: the plugin installed and was enabled, the interface listed its nine files and four skills, and `check-status` reported that the MCP tools were absent without claiming backend access or changed records |
| Not validated | Any MCP connection from Cowork, the bridge started by the desktop app, the Keychain read in the launcher, a synthetic collection from Cowork, Chrome reading of the real table, scheduling, any VPS operation |

Installation and the behaviour without a connection are validated by the owner's test. Connectivity is not.
A local check is not evidence that the bridge works in Cowork.

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

## Connection: local bridge to a sandbox

Implemented in the package, not yet validated in Cowork.

The service speaks Streamable HTTP only and a plugin can only declare a local server as a command, so the
manifest declares one stdio server, `stock-radar`, that starts `plugin/mcp/bridge.sh`. The launcher:

- reads one token from the macOS Keychain item `stock-radar-sandbox-mcp` (account `stock-radar`) at start;
- exports it as an `Authorization` value in the environment of the proxy only;
- runs `mcp-remote@0.14.3` through `npx`, with the fixed target `http://127.0.0.1:18001/mcp`, the
  `http-only` transport and a header argument that holds a placeholder, not the token.

Nothing secret is in the package, in Git, in process arguments or in the proxy log, which prints header
names only. The proxy does log the JSON-RPC method of each message and the `initialize` body to its error
stream. The target is fixed in the launcher; there is no option to point it elsewhere.

Loopback always means the machine where the process runs. The bridge is started by the Claude desktop app
on the MacBook Pro, so it reaches only a service listening on that MacBook. A stack started on the
development machine or on the VPS is not reachable through it.

Requirements on the MacBook Pro: Docker with Compose v2.20 or later, Make, Git, and Node.js 18 or later
with `npx` on the PATH that the desktop app uses. The first start downloads the pinned proxy from the npm
registry; later starts use the npm cache.

Because the token is read once at start, every change of the Keychain item needs a restart of the Claude
desktop app before it takes effect. The reader token is the resting state. The collector token is stored
only for the synthetic write test and replaced afterwards.

Failure diagnosis, without weakening any control:

| Symptom | Meaning |
|---|---|
| Launcher exits with `Keychain item ... was not found` | The item was not created on this machine |
| Launcher exits with `npx was not found in PATH` | Node.js is missing or not visible to the desktop app |
| Proxy prints `Dynamic Client Registration rejected (HTTP 404)` and exits | The service answered 401: the stored token does not match the running sandbox. The proxy then probes the same loopback service for OAuth, finds none and stops. No browser opens and no external sign-in happens |
| Proxy cannot connect | The sandbox is not running on `127.0.0.1:18001` |
| HTTP 421 | The request carried a non-loopback Host header; the SDK check is working as intended |

Host and Origin checks of the MCP SDK are unchanged. Do not disable them and do not add OAuth to work
around a failure.

Synced plugins also load in Claude Code on machines signed in to the same account. On a machine without
the Keychain item the launcher exits at once and the server is shown as failed, which is harmless.

### Sandbox

`make sandbox-up` creates `.env.sandbox` (ignored by Git, mode 0600) with new random credentials, checks
that port 18001 is free, migrates and provisions only the sandbox database and starts the API and
PostgreSQL in the Compose project `stock-radar-sandbox`. The monitor is not started, `MONITOR_ENABLED` is
false and no provider key is set. The habitual stacks use other project names, volumes and ports and are
not touched.

| Command | Effect |
|---|---|
| `make sandbox-up` | Create credentials if absent, migrate, provision and start the sandbox |
| `make sandbox-token ROLE=reader` | Store the sandbox reader token in the Keychain item, without printing it |
| `make sandbox-token ROLE=collector` | Store the sandbox collector token in the same item |
| `make sandbox-down` | Stop the containers and keep the sandbox volume |
| `make sandbox-destroy` | Remove the sandbox containers, volumes, `.env.sandbox` and the Keychain item |

`make sandbox-token` reads the token from `.env.sandbox` and hands it to `security -i` on standard input,
so it never appears in process arguments, shell history or output. It then reads the item back and fails
if the stored value differs. The token must be stored on the machine that runs the bridge.

Every sandbox command passes `--project-name stock-radar-sandbox` or the equivalent Make variable and
overrides `COMPOSE_PROJECT_NAME`, `API_PORT`, `MONITOR_ENABLED` and `BRAPI_API_KEY` in its own environment.
A value inherited from the terminal, or given on the `make` command line, cannot redirect `sandbox-up`,
`sandbox-down` or `sandbox-destroy` to another project, port or provider key.

### Test sequence on the MacBook Pro

Proposed sequence. Steps run by the owner; record the real results in [testing](testing.md).

1. Check the requirements: `docker compose version`, `node --version`, `npx --version`, `make --version`.
2. `git pull`, after the changes were committed and pushed with the owner's authorization.
3. `lsof -nP -iTCP:18001 -sTCP:LISTEN` prints nothing, then `make sandbox-up`.
4. `make sandbox-token ROLE=reader`, then `sh plugin/mcp/bridge.sh` in a terminal. Expected:
   `Proxy established successfully`. Stop it with Ctrl+C. This checks the Keychain read, `npx` and the
   sandbox before Cowork is involved. An `EACCES` error from npm points to a damaged npm cache, not to the
   plugin.
5. `make package`, then upload `dist/stock-radar-0.3.0.zip` in Customize, Plugins, replacing 0.2.1.
6. Quit and reopen the Claude desktop app.
7. In a new Cowork task ask for a real call of `service_status`, then for `register_source` with a
   synthetic code. Expected: a tool call block with the version and capabilities, then `forbidden`.
   A written answer without a tool call block proves nothing.
8. Only after step 7 passes: `make sandbox-token ROLE=collector`, restart the app, call `register_source`
   with a synthetic code and name, build one payload from
   `skills/collect-signals/references/example-collection.json` with the returned source `id` and a
   `client_collection_id` generated once, call `register_collection`, read it with `get_collection` and send
   the identical payload again, expecting `duplicate: true`.
9. Always, also after a failure: `make sandbox-token ROLE=reader`, restart the app and confirm that
   `register_source` is refused again.
10. `make sandbox-destroy` when the sandbox is no longer needed.

The example file must not be sent as it is: its `source_id` and `client_collection_id` are placeholders.

### What is not established

- Whether a Cowork task on this account receives tools from a local server. The
  [support by app](https://claude.com/docs/plugins/platform-support) table says a local server loads when
  the Cowork session runs on the user's computer;
  [Cowork on web, desktop and mobile](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile)
  says plugins with local MCP servers work through the desktop app, also for sessions in the cloud; the
  [architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)
  says local MCP servers do not run in sessions in the cloud. Step 7 is the test. One failed attempt is not
  proof of incompatibility.
- Whether the desktop app resolves `npx` and substitutes `${CLAUDE_PLUGIN_ROOT}` for this plugin.
- Anything about the VPS. The loopback publication is a property of `compose.yaml` on whatever host runs
  it. This repository records no VPS deployment and none was verified; see [operations](operations.md).
- Scheduled runs. Interactive success would say nothing about them.

A remote connector is not used. Whether added as a custom connector or declared as an `http` entry, it is
contacted from Anthropic's cloud, and the
[custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
requires a publicly reachable server. Fixed request headers for static credentials are documented there as
a beta for a limited set of organizations. Public ingress and OAuth stay out of scope.

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

1. Run the test sequence above on the MacBook Pro and record the result of each step.
2. Confirm the names under which the Stock Radar tools appear in a Cowork task.
3. Decide whether `prepare-triggers` and `plugin/references/` are removed from the package.
4. Decide the target after the sandbox: the bridge has a fixed sandbox address by design.
5. Run `collect-signals` interactively once: confirm which column holds the analyst rating, how the full
   list is traversed, the exchange prefix shown for symbols, whether the page states a total and a date, and
   that a session clock and UUID generator are available.
6. Exercise the access pause by starting signed out, then replying `logado`.
7. Resolve the TradingView usage conditions recorded in [integrations](integrations.md) before unattended use.
8. Create the daily scheduled task and observe where it runs and what happens when the Mac is asleep.
