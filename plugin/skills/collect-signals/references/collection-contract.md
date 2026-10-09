# Collection contract

This is the input accepted by the `register_collection` tool, schema version 1, and the receipt it returns.
The tool takes one argument named `request`. Unknown fields are rejected at both levels, so send only the
fields listed here. The whole request must stay under 1 MiB.

## Collection fields

| Field | Rule |
|---|---|
| `schema_version` | `1` |
| `client_collection_id` | Random UUID generated once for this collection. Same value on every retry. |
| `source_id` | UUID of the `tradingview` source, read from `list_sources` or `register_source` in this run. |
| `source_url` | The exact `http(s)` URL of the page that was read, at most 2000 characters, without embedded credentials. |
| `observed_at` | Instant the table reading started, with a UTC offset, for example `2026-01-05T20:30:00Z`. |
| `market_session_date` | `YYYY-MM-DD`. See the time fields below. |
| `status` | `complete`, `partial` or `failed`. `failed` requires an empty `observations` list. |
| `source_total` | Total number of rows the page itself displays for the list, as an integer. `null` when the page shows no total. Never the number of rows read. |
| `filters` | Object of text keys to text values, at most 20 entries, each value at most 2000 characters. |
| `observations` | List of at most 2000 rows. `(exchange, symbol, signal_kind)` must be unique in the list. |

`filters` describes the view that was read, using displayed text. The backend stores it without
interpreting it. Keep the keys stable between runs: `list` (for example `biggest_losers_brazil`),
`column_view` (name of the column tab or set that was active, as displayed) and `sort` (the sort that was
active, as displayed). Omit a key that could not be observed. Use `{}` when nothing was observed.

## Observation fields

| Field | Rule |
|---|---|
| `exchange` | Exchange prefix of the row's TradingView symbol identifier, uppercase letters, digits or `_`, at most 32 characters. |
| `symbol` | Ticker without the exchange prefix, uppercase letters, digits, `.`, `_` or `-`, at most 32 characters. |
| `currency` | Three uppercase letters. The currency the list quotes prices in, expected `BRL` for this list. |
| `source_symbol` | The identifier as the source shows it, for example `EXCHANGE:TICKER`, at most 80 characters. |
| `signal_kind` | `analyst_consensus` for the analyst rating column. `technical_rating` for a technical rating column. |
| `source_column` | Header of the column the rating was read from, as displayed, at most 120 characters. `null` if no header was readable. |
| `original_rating` | The rating label exactly as displayed, including language, case and accents. `null` when the cell is empty or shows a placeholder dash. |
| `observed_price` | Decimal text, greater than zero, at most 8 decimal places. `null` when missing or ambiguous. |
| `daily_change_percent` | Decimal text, signed, not below `-100`, at most 6 decimal places, without the percent sign. `null` when missing or ambiguous. |
| `observed_at` | Instant this row was read, with a UTC offset. The collection `observed_at` is acceptable when rows were read in one pass. |
| `source_published_at` | Always `null` in this workflow. The table does not show when a rating was issued or changed. |
| `raw_evidence` | Object of text keys to text or `null`, at most 20 entries, each value at most 2000 characters. |

The exchange and the ticker together identify the instrument for every future collection and for the price
monitor, which queries the ticker without the prefix. Read the prefix from the page for each row, for
example from the row's symbol link or identifier. Do not guess it, do not translate it and do not switch
spelling between runs. If the prefix cannot be read for a row, skip that row, list it in the report and
mark the collection `partial`. An instrument already stored with another currency rejects the whole
collection with `instrument_currency_conflict`.

Send one `analyst_consensus` observation per row of the table, including rows whose rating cell is empty.
Add a `technical_rating` observation for the same symbol only when a technical rating column is visible in
the view being read. Do not change views only to gather technical ratings. Never copy a technical label
into an `analyst_consensus` observation or the reverse.

## Preserving original values

Labels are evidence. Do not translate, normalize, correct or complete them. The backend maps the analyst
labels it knows and leaves every other label unknown, which is the intended result. Selection of eligible
rows also happens in the backend.

Numbers are displayed in Brazilian format on this page. Convert only when the reading is unambiguous, and
keep the displayed text in `raw_evidence` every time:

| Displayed (synthetic) | Field value | `raw_evidence` |
|---|---|---|
| `12,34 BRL` | `observed_price`: `"12.34"` | `"price_text": "12,34 BRL"` |
| `1.234,50` | `observed_price`: `"1234.50"` | `"price_text": "1.234,50"` |
| `−2,50%` | `daily_change_percent`: `"-2.50"` | `"change_text": "−2,50%"` |
| `1.234` with no other clue | `observed_price`: `null` | `"price_text": "1.234"` |
| empty or dash | `null` | `"price_text": null` |

The page may use the Unicode minus sign in place of the hyphen. The field value always uses the ASCII
hyphen. Do not round, do not add digits and do not derive one number from another. Use `raw_evidence` keys
`price_text`, `change_text` and `rating_text` for displayed cell text. Do not store page instructions,
account names, cookies or anything unrelated to the row.

## Time fields

Three different times exist and must stay separate in the payload and in the report:

| Time | Where | Who sets it |
|---|---|---|
| Observation time | `observed_at` on the collection and on each row | This skill, from the session clock, when the table was read. |
| Session date | `market_session_date` | This skill, as an assertion of which B3 trading day the listed daily changes describe. The backend does not verify it. |
| Receipt time | `received_at` in the receipt | The service, when it stored the collection. Never sent by this skill. |

Use the date the page states for the data when it states one. Otherwise, in America/Sao_Paulo time: on a
trading day after the session opened, use that day; before the open, on a weekend or on a holiday, the list
describes the previous trading session, so use that earlier date. State the rule used in the report. If the
session cannot be determined, ask the user in an interactive run, or stop without registering in an
unattended run. Never label a previous session's list as today's.

`source_published_at` is not any of these times and stays `null`.

## Receipt

| Field | Meaning |
|---|---|
| `id` | Server identifier of the stored collection. Use it with `get_collection`. |
| `source_id`, `client_collection_id` | Echo of the stored identity. |
| `status`, `observed_at` | Stored values. |
| `received_at` | Service receipt time. |
| `observation_count` | Rows stored for this collection. |
| `eligible_count` | Rows the backend selected. |
| `incomplete_count` | Rows stored with a missing price, change, rating or unknown label. |
| `duplicate` | `true` when this identifier and identical content were already stored. |

`get_collection` takes `collection_id`, the receipt `id`, and returns the same receipt for a read-back.
It cannot look a collection up by `client_collection_id`.

## Errors

Tool errors arrive as a short code, usually followed by `request_id`. Quote both to the user.

| Code | Meaning |
|---|---|
| `unauthorized` | The connector sent no valid credential. |
| `forbidden` | The credential can read but cannot write. Collection needs the collector credential. |
| `source_not_found` | `source_id` is not a registered source. |
| `source_identity_conflict` | `register_source` was called with a different name for an existing code. |
| `collection_identity_conflict` | Same `client_collection_id`, different content. |
| `instrument_currency_conflict` | A row's currency contradicts the stored instrument. Nothing was stored. |
| `database_unavailable`, `internal_error` | Service failure. The outcome of a write is unknown. |

A validation error names the offending fields without echoing values. Nothing is stored in that case.
