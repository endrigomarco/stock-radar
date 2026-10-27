# Selection contract

Mirrors `src/stock_radar/viewmodels/selection.py`. Unknown fields are rejected. The whole request must stay
under 1 MiB.

## list_selection_candidates

Argument `query`: `{}` for the latest session collected under assisted selection, or
`{"market_session_date": "YYYY-MM-DD"}`.

| Field | Meaning |
|---|---|
| `market_session_date` | Session the collected list described |
| `experiment_version`, `criteria_version` | Policy version and the criteria version to echo in the request |
| `max_new_per_session`, `slots_used`, `slots_remaining` | Limit of new tracking runs for the session and its use across all collections and confirmations |
| `next_session_opens_at`, `late_if_confirmed_now` | A confirmation at or after the next session opens is recorded as late; it is accepted |
| `liquidity_comparable`, `baseline_rule` | Whether the turnover estimate is comparable for every pending candidate (same collection, price and volume present) and which rule ordered `baseline_rank` |
| `collections` | Every collection of the session with `status`, observation and receipt times |
| `pending` | Number of candidates that still need a decision |
| `candidates` | One item per candidate, below |

Candidate fields: `decision_id`, `exchange`, `symbol`, `instrument_id`, `signal_observation_id`,
`collection_id`, `observed_at`, `observed_price`, `daily_change_percent`, `original_rating`, `volume`,
`sector`, `estimated_turnover_at_observed_price` (observed price times displayed volume, an estimate, not
the traded value and not a daily average), `turnover_partial_session` (true when read before the session
closed), `turnover_unavailable_reason`, `open_tracking_run_id` (pending candidates with an open run right
now), `baseline_rank`, `outcome`, `reason_code`, `rank`, `slot`, `tracking_run_id`, `rationale`, `details`,
`decided_at` and `selection_late`.

Outcomes: `pending`, `selected`, `not_selected`, `not_assessable`, `already_tracked`. The service decides
`already_tracked` (an open run existed at registration), `not_selected` with `not_monitorable` (the quote
client rejects the ticker format) and `not_selected` with `daily_cap_reached` (no slot left at
registration).

## confirm_selection

Argument `request`:

| Field | Rule |
|---|---|
| `client_selection_id` | Random UUID generated once. Same value on every retry of the same text |
| `market_session_date` | The session read |
| `criteria_version` | Exactly the value returned by the read |
| `ranking_basis` | `full`, or `limited` when most research failed |
| `summary` | 1 to 4000 characters |
| `no_selection_reason` | Required when no candidate is selected, at most 2000 characters |
| `plugin_version` | `0.10.0` |
| `decisions` | Exactly one per pending candidate |

Decision fields:

| Field | Rule |
|---|---|
| `decision_id` | From the read |
| `outcome` | `selected`, `not_selected`, `not_assessable` or `already_tracked` (only when the service confirms an open run) |
| `reason_code` | `not_selected`: `outranked`, `trading_halted`, `price_comparison_invalid`, `other_concrete_impediment`. `not_assessable`: `essential_data_missing`, `identity_unresolved`. None for the other outcomes |
| `rank` | Required exactly for `selected` and `outranked`; contiguous from 1 across the request; selected hold the best ranks |
| `rationale` | 1 to 2000 characters |
| `event_date` | Required exactly for `price_comparison_invalid`: the ex-date of the corporate event |
| `evidence` | Up to 10: `kind` (`news`, `filing`, `results`, `recommendation`, `sector_move`, `corporate_event`, `market_data`, `other`), `publisher`, optional `origin` (the original institution), optional `url`, optional `title`, `published_at` or null, `consulted_at`, `summary`, `stance` (`favorable`, `unfavorable`, `neutral`). `trading_halted` and `price_comparison_invalid` need at least one item with `published_at` |
| `unavailable` | Up to 8 of `drop_cause`, `upcoming_events`, `recommendation_details`, `sector`, `volume`, `price`, `spread`, `other` |
| `risks` | Up to 10: `code` (`upcoming_results`, `tender_offer`, `judicial_recovery`, `negative_news`, `ex_dividend`, `corporate_event`, `low_liquidity_estimate`, `other`) and `text` |

Times carry a UTC offset. `published_at` cannot be after `consulted_at`, and `consulted_at` cannot be more
than two minutes after the service accepts the decision.

## Receipt

`id`, `client_selection_id`, `market_session_date`, `experiment_version`, `criteria_version`, `decided_at`
(server time after validation; new runs never take a reference quoted before it), `late`, `selected`
(symbol, `slot`, `tracking_run_id`), counts of `not_selected`, `not_assessable`, `already_tracked`,
`slots_remaining` (current) and `duplicate`.

## Errors

| Code | Meaning |
|---|---|
| `selection_session_not_found` | No collection for that session |
| `session_not_assisted` | The session follows the automatic policy |
| `nothing_pending` | Every candidate already has a decision |
| `pending_set_changed` | The request does not cover exactly the current pending candidates |
| `candidate_already_decided` | A decision in the request is already final |
| `decision_not_in_session` | A `decision_id` does not belong to that session |
| `selection_exceeds_slots` | More selected than `slots_remaining` |
| `selection_underfilled` | A slot left empty while a candidate was only `outranked` |
| `candidate_already_tracked` | A selected candidate has an open run now. Nothing stored |
| `already_tracked_not_confirmed` | `already_tracked` sent for a candidate without an open run |
| `criteria_version_mismatch` | `criteria_version` differs from the session policy |
| `evidence_after_decision` | An evidence item was consulted after the decision |
| `selection_identity_conflict` | Same identifier, different content |
| `market_calendar_unavailable` | The trading calendar does not cover the dates involved |
| `forbidden` | The credential can read but cannot write |
| `database_unavailable`, `internal_error` | Service failure; the outcome of a write is unknown, retry the same text |
