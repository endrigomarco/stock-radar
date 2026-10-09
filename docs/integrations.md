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

`src/stock_radar/market_calendar.py` holds a static calendar read from B3 on 2026-10-08: the
[trading calendar](https://www.b3.com.br/pt_br/solucoes/plataformas/puma-trading-system/para-participantes-e-traders/calendario-de-negociacao/feriados/)
and the [equities trading hours](https://www.b3.com.br/pt_br/solucoes/plataformas/puma-trading-system/para-participantes-e-traders/horario-de-negociacao/acoes/).
For 2026 there is no equities session on 1 January, 16 and 17 February, 3 and 21 April, 1 May, 4 June,
7 September, 12 October, 2 and 20 November, 24, 25 and 31 December, and trading starts at 13:00 on
18 February. A session runs from 10:00 to 17:00 America/Sao_Paulo, the end of the closing call.

Two limits apply. B3 had not published 2027 on that date, so no 2027 calendar is versioned: runs whose
20 sessions would cross into 2027 (activation from early December 2026) stay prepared, and polling stops
entirely in 2027 until the calendar is added. The hours page states no validity period and B3 usually
changes hours around the United States daylight saving transitions. The single 2026 hours entry is therefore
confirmed only for the published grid; add a dated `TradingHours` entry when B3 announces a change. Until
then a later close would only shorten observation: polling stops at 17:00 and quotes timed after it are
rejected with a warning. Nothing consults a calendar service or a model at runtime.

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
run on the user's computer; reachability of the tailnet from one is untested.
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
