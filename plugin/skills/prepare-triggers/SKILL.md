---
name: prepare-triggers
description: Explain the state of Stock Radar tracking runs and their fixed 1%, 2% and 3% levels, and cancel one specific run only when the user explicitly asks, which is an irreversible write that needs the collector credential. Tracking is prepared automatically by the backend, so this skill prepares nothing, creates no provider alerts and places no trades.
---

# Prepare Triggers

Superseded by the backend. Under the assisted policy a tracking run is created only when
`confirm_selection` accepts a selected candidate, at most three new ones per session; sessions that began
under the earlier automatic policy created or reused one run per eligible instrument at registration. A
server process sets the reference price, creates the six levels and records hits from polled quotes. No tool exists to create a run, set a reference, choose levels or create a provider alert,
and none must be simulated. Answer in the user's language and never use em dashes.

1. Look for the Stock Radar MCP tools by name, allowing a connector prefix. If they are absent or failing,
   say that the connector is unavailable and stop. Do not create substitute local records.
2. Read runs with `list_tracking_runs`, using a `query` object with optional `status` or `instrument_id`.
   Report `status`, `admitted_at`, `reference_price`, `reference_at`, `expires_at`, `levels_total` and
   `levels_hit` as returned.
3. A run with no `admitted_at` is waiting for a monitoring slot. A run with no `reference_price` has no
   reference yet. Never supply, estimate or compute a reference price or level in the conversation.
4. Use `cancel_tracking_run` only when the user explicitly asks to cancel a specific run, and report the
   returned run. It needs the collector credential and cannot be undone. It does not free a selection slot
   of that session; a new run for the stock needs a later selection.
5. Do not describe provider alerts as existing. Alert creation in TradingView is not implemented.
