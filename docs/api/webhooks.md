# Webhook receipt and idempotency

## Implemented local interface

`POST /webhooks/tradingview` receives a typed JSON notification. `Authorization: Bearer <WEBHOOK_TOKEN>`
is a dedicated internal receiver credential, separate from reader and collector tokens. The source with
code `tradingview` must be registered first; a missing source returns 503 without accepting a receipt.
`GET /v1/webhook-receipts/{receipt_id}` requires reader or collector access and exposes status, timestamps,
attempt count and a safe error code. It does not expose the stored message or database credentials.

This is a functioning local receiver and processor, tested with synthetic mappings. It is not a validated
live TradingView integration. Alert provisioning remains pending and external webhooks are deferred while
quote polling is piloted. Receiving a webhook does not create an alert or a tracking run. A trigger event is
supported by exactly one piece of evidence, a webhook receipt or a polled price quote. When a webhook reports
an earlier supported occurrence for a level first observed by polling, the processor replaces the quote
evidence with the receipt in the same statement. Levels created by polling have no alert source, so a webhook
cannot map to them until an alert is configured deliberately.

## Message contract

```json
{
  "schema_version": 1,
  "alert_mapping_id": "71ba2a4b-9be0-4b53-a774-c15b74ac171b",
  "tracking_run_id": "224f136a-1e7d-43e6-a230-d72f8a14c62a",
  "signed_percent": "1",
  "source_event_at": "2026-10-07T18:00:00Z",
  "observed_price": "101.00",
  "provider_event_id": null
}
```

The example is synthetic. Configure real placeholders or constants only after checking their meaning
in the sender. Do not fabricate a provider event ID. Mapping and run IDs are UUIDs. Thresholds are nonzero,
greater than -100 and bounded to database precision. Prices are optional positive finite Decimal values.
Timestamps require an offset, normalize to UTC and cannot be more than five minutes in the future for a
new receipt. Older events are accepted for delayed delivery, then validated against the persisted activation
window. Unknown fields are rejected; only the validated fields above are stored. Tokens, headers, URLs and
arbitrary provider text are never stored in the receipt. JSON content type is required; bodies are bounded
to 1 MiB by the shared request boundary.

## Delivery identity

When `provider_event_id` exists, the key is a namespaced SHA-256 of that ID, scoped by source in the database.
The same identity with different canonical content returns 409 and leaves the original record unchanged.
Without an ID, the key is a namespaced SHA-256 of the entire validated message. Object keys are sorted,
timestamps normalized to UTC, and Decimal spelling normalized, so `101` and `101.00` produce the same identity.
Arrival time is never part of the key. Omitted optional fields and their defaults are equivalent.

The database's unique `(source_id, deduplication_key)` handles concurrent deliveries. Identical retries return
the original receipt ID with `duplicate: true`. Distinct event timestamps or prices remain distinct receipts.
Without a true event ID, two occurrences with exactly the same canonical message cannot be distinguished.
Use a genuine stable event identity if the sender supplies one; never generate a fresh UUID on each retry.
HTTP attempts are not stored as separate logical events.

## Durable receipt and processing

A 202 response means the receipt transaction committed, including on duplicate requests. It does not mean a
threshold was validated. The response includes `id`, `status`, `received_at`, `source_event_at`,
`processing_attempts`, `last_error_code` and `duplicate`. New receipts normally report `pending`, because
processing starts after the response. Query the receipt to inspect its subsequent state.

Database failure before commit returns 503 without a success acknowledgement. The dedicated database pool
has short connection, pool, statement and lock timeouts. These bound individual waits, not the total request
duration; production latency and the sender's timeout still need measurement at the ingress.

A background task processes the committed receipt in a second transaction. Receipt row locking serializes
repeated processing. The processor validates source, mapping, run and signed threshold, an activated run
(`active` or `completed` for delayed delivery), alert activation, and event time within the intersection of
the run and alert windows. The beginning is inclusive and expiry exclusive. If a triggering price is supplied,
it must cross the stored configured threshold, or mathematical threshold when no configured price exists.
A missing price remains missing; a notification alone does not establish continuous price coverage.

- `pending`: committed, awaiting processing or retry after a database failure.
- `unmapped`: unknown alert mapping, preserved for later reconciliation.
- `failed`: known mapping with inconsistent source/run/threshold, inactive alert, invalid window or price.
- `processed`: validated notification considered for the first occurrence of its level.

Trigger-event updates and receipt status commit together. Database failures roll them back, leaving a
recoverable receipt. The unique trigger-level key prevents double counting even when distinct receipts
report the same level. An earlier event arriving later replaces the selected first occurrence atomically;
its previous supporting receipt remains stored. Equal timestamps retain the existing selected receipt,
and do not establish an order between simultaneous events. Receipt history remains the evidence record.
No coverage flags, performance statistics or trading actions are inferred from notifications.

After a crash, database outage or mapping correction, run `make webhooks-process`. It retries at most 100
pending/unmapped/failed receipts, using the same processor. `ARGS_WEBHOOKS="--limit 500"` changes the batch
size within 1 to 1000. Oldest attempts are considered first, with pending work first. Processed receipts
are skipped; concurrent runs remain safe. An unexpected processing failure is logged with receipt, correlation and error IDs, and sanitized stack
locations. The command exits unsuccessfully when such failures occur. There is no scheduled worker or automatic full replay on startup.

## Authentication and live integration boundary

The internal Bearer credential is for local tests and an authenticated ingress. TradingView is not assumed
to send a custom Authorization header. Before deployment, the HTTPS gateway must authenticate the actual
sender, strip incoming Authorization and inject the internal receiver token only after successful verification.
The backend must remain inaccessible except through the trusted gateway or local loopback. Do not put the
token into an alert body or URL, and do not trust a client-supplied certificate-verification header.
No gateway, certificate verification, provider signature or public deployment is implemented in this increment.

TradingView documents HTTPS client-certificate verification, a three-second timeout and up to three retries
for 5xx responses except 504. These are provider statements, not proof of this account's configuration:
[authentication](https://www.tradingview.com/support/solutions/43000680459-webhook-authentication/),
[webhook setup](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/),
[resubmission](https://www.tradingview.com/support/solutions/43000735201-webhook-resubmission/).

Real-time entitlement, quotas, two-factor authentication, activation, expiration and event placeholders
still need account validation. A dropped notification is not a verified non-hit. See
[integration findings](../integrations.md) and [experiment rules](../experiment.md).

Webhook receipt and processing logs can be located with `make errors ID=RECEIPT_UUID`. Background failures
cannot change an already acknowledged response. See [observability](../observability.md) for error boundaries.
