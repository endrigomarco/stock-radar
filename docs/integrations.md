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

## Claude Cowork and plugin

The [Cowork overview](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork)
describes browser/files and plugin capabilities. Availability and scheduling behavior must be checked in
the user's actual environment, especially for workflows requiring the local MacBook and browser.

The [plugin manifest reference](https://code.claude.com/docs/en/plugins-reference) defines the
`.claude-plugin/plugin.json` layout and skill directories. This supports the repository structure, not a
claim of Cowork installation compatibility. Verify discovery, packaged references and remote MCP
authentication in Cowork. No account connection or daily schedule exists yet.

## Pilot evidence to capture

- Source/account context and completeness of the analyst-rating table.
- Authorized destination and a synthetic ingestion/read-back receipt.
- Actual MCP tools, version and authentication capabilities.
- Reference-price source, activation time and manual alert mappings.
- Webhook event times, receipt times, repeat delivery and failed-delivery behavior.
- Server restart recovery and a backup restore using synthetic data.

Track each item as untested, passed with scope/evidence, failed, or blocked. Do not promote a local fixture
or manifest check to a live integration pass.
