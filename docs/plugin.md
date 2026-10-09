# Claude plugin

The plugin root is `plugin/`, not the repository root. Only that directory is packaged. Its manifest is
`plugin/.claude-plugin/plugin.json`; skills are under `plugin/skills/`. Development documents stay outside.

## Current state

Version 0.2.1, prepared on 2026-10-09 for collection by Claude Cowork on the MacBook Pro.

| State | Scope |
|---|---|
| Prepared locally | Manifest, `collect-signals` with its references, corrected read-only skills, installable archive |
| Checked statically | Manifest and frontmatter parsing, archive layout, internal links, synthetic example against `CollectionInput` |
| Not validated | Installation in Cowork, skill discovery, Chrome reading of the real table, any MCP connection from Cowork, scheduling |

A static check is not evidence that the plugin installs or works in Cowork. No collection was run, nothing
was written to any service and no schedule exists.

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

Version 0.2.1 differs from 0.2.0 only in the corrected `prepare-triggers` description. An older
`dist/stock-radar-0.2.0.zip` left on a machine is outdated and must not be uploaded.

## Installation sequence

Proposed sequence. No step below has been performed.

1. The changes are committed and pushed after the owner's authorization. Until then the MacBook Pro has
   nothing new to pull.
2. On the MacBook Pro: `git pull`, then `make package`.
3. Claude desktop app, Customize, Plugins, Add, Upload plugin, select `dist/stock-radar-0.2.1.zip`.
4. First test: confirm the plugin is listed as `stock-radar` version 0.2.1 and that the four skills appear,
   then ask for `check-status` in a new Cowork task.

The first test covers installation and skill discovery only. Installing does not connect anything and
creates no schedule. With no Stock Radar MCP tools in the task, the expected answer from every skill is that
the connector is unavailable. A skill that describes a collection, a receipt or stored data in that state
is a defect to record, not a success. The MCP connection is a later increment.

## Connection: unresolved

The package contains no `.mcp.json`, address or credential, because no working path from Cowork to the
service has been established. Facts as of 2026-10-09:

- The API and MCP endpoint on the VPS listen on loopback only. Authentication is a static Bearer token per
  role. There is no OAuth. The MCP SDK's localhost Host and Origin checks are enabled.
- A remote connector, whether added as a custom connector or declared as an `http` entry in a plugin's
  `.mcp.json`, is contacted from Anthropic's cloud in every client, Cowork included. The
  [custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
  states that the server must be reachable from the public internet and that servers behind a VPN do not
  connect. A Tailscale-only address therefore cannot be used as a remote connector, even though the MacBook
  is on the tailnet.
- The same guide describes fixed request headers for static credentials on a custom connector. The plugin
  documentation describes OAuth sign-in for bundled remote connectors and forbids secrets in `.mcp.json`.
- A local MCP server, a command the app starts, is documented as loading in Cowork sessions that run on the
  user's computer. Whether such a process can reach the tailnet from that session has not been tested.

Candidate paths, none chosen and none implemented:

| Path | What it needs before it can be tested |
|---|---|
| Remote custom connector | Public HTTPS ingress on the VPS for `/mcp` only, explicit Host and Origin allowlist, rate limiting, optional allowlist of Anthropic's addresses, and a decision between a fixed Authorization header and OAuth |
| Local bridge on the MacBook | A stdio-to-HTTP bridge program, a private route to the VPS loopback or a tailnet listener, the collector token stored on the Mac outside the package, and confirmation that Cowork starts local servers for the task |

Both change the VPS or add a component, so they belong to the next step and need a decision by the owner.
Until then `collect-signals` stops at its first step and reports the connector as unavailable.

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

1. Upload the archive built by `make package` and confirm the skills appear under the `stock-radar` plugin
   and report the connector as unavailable.
2. Decide whether `prepare-triggers` and `plugin/references/` are removed from the package.
3. Choose a connection path above, implement it and store the collector token outside the package and Git.
4. Confirm the names under which the Stock Radar tools appear in a Cowork task.
5. With a test service, register one synthetic collection, confirm the receipt and repeat it to see
   `duplicate: true`.
6. Run `collect-signals` interactively once: confirm which column holds the analyst rating, how the full
   list is traversed, the exchange prefix shown for symbols, whether the page states a total and a date, and
   that a session clock and UUID generator are available.
7. Exercise the access pause by starting signed out, then replying `logado`.
8. Resolve the TradingView usage conditions recorded in [integrations](integrations.md) before unattended use.
9. Create the daily scheduled task and observe where it runs and what happens when the Mac is asleep.
