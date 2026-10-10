# Integration findings

Documentation reviewed on 2026-10-07. These are documentary findings, not live integration results.
Do not assume the user's subscription, browser permissions, VPS configuration or provider access.

## TradingView collection

The target is the [Brazilian biggest-losers page](https://br.tradingview.com/markets/stocks-brazil/market-movers-losers/).
The [analyst rating](https://www.tradingview.com/support/solutions/43000747299-analyst-rating/) is broker
consensus aggregated by FactSet; it is distinct from a technical-indicator rating.

TradingView documents restrictions on [automated collection](https://www.tradingview.com/support/solutions/43000674726-why-is-my-account-banned-due-to-suspicious-activity/),
including browser-driven extraction. A Cowork browser workflow does not remove those restrictions.
Collection and downstream storage/analysis conditions need resolution before live operation; no workaround
or bypass is included in this scaffold. Check the current [terms](https://www.tradingview.com/policies/).

The official [CSV export guide](https://www.tradingview.com/support/solutions/43000474432-how-to-export-screener-data/)
describes configuring columns and exporting, but this project has not verified that the required rating
is present in an actual export. The user's chosen direction is browser collection, not an assumed CSV fix.

## TradingView alerts

[Webhook configuration](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)
documents HTTP delivery when an alert fires, JSON messages, two-factor authentication and a three-second
request timeout. Plan eligibility, quota, data delay and supported sender authentication need account-level
validation. An HTTPS receiver does not create alerts or grant real-time B3 data entitlement.

No official public alert-creation API has been confirmed. Manual configuration is the initial proposal.
Do not assume external API headers or HMAC signatures are supported. Test real sender behavior before
choosing authentication. Review delivery failures and duplication, not just one successful notification.

## brapi quotes

Documentation read on 2026-10-08; no quote request was made by this project. The user reported HTTP 200 for
PETR4 and WEGE3 in the free dashboard. Requests from the Docker container remain unverified.

The [quote endpoint](https://brapi.dev/docs/acoes) is `GET /api/quote/{ticker}` with
`Authorization: Bearer <token>`. The client reads `symbol`, `currency`, `regularMarketPrice` and
`regularMarketTime` (ISO 8601 UTC) from the single result and ignores every other field. The documentation
also allows a `token` query parameter; this project never uses it, so the key stays out of URLs.
The [free plan](https://brapi.dev/pricing) lists one ticker per request, 15,000 requests per month, data
refreshed every 30 minutes and one simultaneous request. Thirty instruments polled in 14 slots per session
use roughly 8,800 requests in a month of 21 sessions. Calls are sequential with a 10 second timeout,
redirects are refused and responses above 1 MiB are rejected. Plan limits and delays can change; verify them
in the account before live use.

Symbols are sent as stored, without the exchange prefix, and must be 1 to 12 uppercase letters or digits.
An instrument brapi does not know fails on every cycle and keeps its slot until its run is cancelled.

## B3 calendar and hours

The monitor and the 20 session window read the same PostgreSQL table, `trading_days`, filled by migration
`d2f6a9c4b810` with one row for every calendar day of 2026, 2027 and 2028. A closed day is a row with
`is_open` false. A date with no row has no coverage. Nothing consults a calendar service, a web page or a
model at runtime, and the migration reads no external source. Each row records its `origin`, a
`source_reference` and the date of consultation, 2026-10-09.

| Year | `origin` | What the rows hold |
|---|---|---|
| 2026 | `existing_configuration` | The calendar previously coded in `src/stock_radar/market_calendar.py`, unchanged |
| 2027, 2028 | `national_holidays` | Weekends and national holidays closed, every other day open |

2026. No equities session on 1 January, 16 and 17 February, 3 and 21 April, 1 May, 4 June, 7 September,
12 October, 2 and 20 November, 24, 25 and 31 December; trading starts at 13:00 on 18 February. These dates
match B3 Oficio Circular 003/2026-VNC of 2026-01-08 and its errata 041/2026-VNC of 2026-06-30, and the
[trading calendar](https://www.b3.com.br/pt_br/solucoes/plataformas/puma-trading-system/para-participantes-e-traders/calendario-de-negociacao/feriados/).
The hours are the configured 10:00 to 17:00 America/Sao_Paulo for the whole year. That is not the official
grid for every date: B3 Oficio Circular 005/2026-PRE states 10:00 to 17:00, including the closing call, from
2026-03-09, linked to United States daylight saving time; before that date the official close was later, and
the grid after the November 2026 change had not been published on the consultation date. The rows are
therefore labelled as the preserved configuration, not as a reproduction of B3. A later official close only
shortens observation: polling stops at 17:00 and quotes timed after it are rejected with a warning.

2027 and 2028. No B3 calendar for these years was found on 2026-10-09: the calendar page ended at 2026 and
no circular was located. That is the result of a search, not proof that none exists. As authorized by the
owner, the rows use national holidays only: 1 January, 21 April, 1 May, 7 September, 12 October,
2 November, 15 November, 20 November and 25 December, from Lei 662/1949 as amended by Lei 10.607/2002,
Lei 6.802/1980 and Lei 14.759/2023. The texts of these laws could not be opened during implementation and
the list was not re-read. Hours are the standard 10:00 to 17:00.

This basis can differ from the sessions B3 actually holds. Optional days and municipal holidays are not
included, so Carnival Monday and Tuesday, Good Friday, Corpus Christi, 24 December and 31 December count as
sessions in 2027 and 2028, and Ash Wednesday has no late opening. On such a day, if B3 is closed, the
monitor polls and receives no quote from a current session, so nothing is recorded. A run whose window
crosses such a day reaches its 20th counted session earlier than it would by real sessions, and expires
earlier. The same applies to a hours change that B3 announces later.

Correction. When B3 publishes a calendar, or a difference is found, a later migration updates the affected
rows and sets `origin` to `b3_official`. There is no automatic update. `expires_at` of a run that is already
active is never recalculated, so a correction changes only future activations; review the active runs whose
window crosses a corrected date when writing that migration.

## Claude Cowork and plugin

The [Cowork overview](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork)
describes browser/files and plugin capabilities. Availability and scheduling behavior must be checked in
the user's actual environment, especially for workflows requiring the local MacBook and browser.

The [plugin manifest reference](https://code.claude.com/docs/en/plugins-reference) defines the
`.claude-plugin/plugin.json` layout and skill directories. This supports the repository structure, not a
claim of Cowork installation compatibility. Verify discovery, packaged references and remote MCP
authentication in Cowork. No account connection or daily schedule exists yet.

Documentation read on 2026-10-09, without any installation or connection attempt. The
[plugins overview](https://claude.com/docs/plugins/overview) and
[support by app](https://claude.com/docs/plugins/platform-support) state that Cowork loads skills, accepts an
uploaded `.zip` or `.plugin` archive, refuses a plugin with a top-level `bin/` directory and does not prompt
for `${user_config.*}` values. The
[custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
states that remote connectors are contacted from Anthropic's cloud in every client, so the server must be
publicly reachable and a VPN-only address does not connect. Tailscale on the MacBook therefore does not make
the VPS reachable as a remote connector. Local MCP servers are documented as loading in Cowork sessions that
run on the user's computer. Since 2026-10-06 new Cowork tasks on Pro and Max plans run in the cloud, and the
official pages disagree on whether a local server is then available through the open desktop app, so this
must be observed, not assumed. The owner reported that a shell command run by a Cowork task executed in the
cloud and could not reach the tailnet address, so only a process started on the MacBook can use Tailscale.
The plugin therefore bundles a Python bridge as a local server; whether Cowork starts it is not validated.
[Scheduled tasks](https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork)
run remotely unless they need local files or apps; driving Chrome from a scheduled run is not documented.
The consequences and the open decision are in [plugin](plugin.md).

## Pilot evidence to capture

- Source/account context and completeness of the analyst-rating table.
- Authorized destination and a synthetic ingestion/read-back receipt.
- Actual MCP tools, version and authentication capabilities.
- Reference-price source, activation time and manual alert mappings.
- Webhook event times, receipt times, repeat delivery and failed-delivery behavior.
- Server restart recovery and a backup restore using synthetic data.

Track each item as untested, passed with scope/evidence, failed, or blocked. Do not promote a local fixture
or manifest check to a live integration pass.
