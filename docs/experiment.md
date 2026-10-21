# Experiment rules

## Established scope

Universe: Brazilian stocks observed on TradingView's biggest losers list.
Selection: daily price change below zero and analyst rating Strong Buy (`Viés de alta forte`).
Store source labels as well as normalized values. Missing, neutral and technical ratings do not qualify.
Thresholds: +1%, +2%, +3%, -1%, -2%, -3%, each relative to one immutable reference price per tracking run.

## Active rules for the polling pilot

These rules are implemented for experiment `tradingview_losers_strong_buy`, version 1, and replace the earlier
proposal of separate daily tracking runs.

- One open tracking run per instrument and experiment, across versions. A new eligible observation is stored
  and reuses the `prepared` or `active` run; it never resets reference, window or levels. Under version 1 a run
  is created only together with its origin observation; under version 2 it is created by a confirmed
  selection (see below). Either way an observation that already originated a run cannot create another.
- At most `MONITOR_MAX_INSTRUMENTS` distinct instruments (default 30) are monitored. Other runs wait and are
  admitted oldest first when a slot frees. Runs created by the same collection share a creation time and are
  ordered arbitrarily among themselves.
- Reference: the first accepted brapi quote received after admission whose market time is inside a valid B3
  session and not earlier than the origin observation. Until then the run stays `prepared` with no reference.
  The reference never changes afterwards.
- Window: 20 B3 sessions including the activation session, read from the experiment version. It ends at the
  close of the 20th session, counted in the `trading_days` table. If that table has no row for any day up to the
  20th session the run is not activated. The expiry is stored at activation and is not recalculated when the
  calendar is corrected later. For 2027 and 2028 the table holds national holidays only; see
  [integrations](integrations.md) for how that can shorten a window.
- A level is reached when the quote price is greater than or equal to a positive threshold, or less than or
  equal to a negative one. Thresholds are `reference * (1 + percent / 100)` in Decimal. Only our reference is
  used; provider change percentages and daily highs or lows are ignored.
- Only the first observed hit of each level is recorded. One quote may reach several levels.
- A run ends as `completed` when all six levels were hit, `expired` after its window, or `cancelled`.

A quote may activate a run or produce a hit only when its market time is inside a session of the versioned
calendar, is at most 2 minutes ahead of the receipt time and is at most 60 minutes old at receipt. The free
brapi plan refreshes about every 30 minutes, hence the 60 minute limit. Quotes failing these rules are rejected
before persistence and logged, so a defective timestamp cannot block later quotes. Hits additionally require
a market time after activation and not after the window close. The window is always evaluated with the quote's
market time, never the receipt time. A quote whose market time is not newer than the last accepted one for
the instrument is ignored. Equal prices with a newer market time are valid observations.

Polling stops strictly at the session close. No extra collection runs after the close and there is no
reconciliation, so the last minutes of every session, the closing call and anything the provider publishes
late, including on the final session of a window, can be missed. Every polled run has `price_coverage` set to
`partial`. No detected hit is not proof that the price never touched a level between polls.

## Assisted selection, version 2

Version 2 of `tradingview_losers_strong_buy` keeps every rule above and adds `candidate_selection`, criteria
`selection-v1`. It governs a session when the session's first collection was registered under it; sessions
whose first collection came earlier stay under version 1 entirely, including the day of the transition, so a
session never gets two policies or extra slots. Version 1 history is not reclassified.

- Initial filter unchanged: negative daily change and analyst consensus Strong Buy. Every eligible row is
  stored as a candidate of its session, including those never selected.
- At most three new tracking runs per session, counted over every collection and confirmation of that
  session. The session is the B3 day the list describes, derived by the service from the observation time
  and `trading_days` in America/Sao_Paulo. A stock with an open run reuses it and uses no slot.
- The assistant researches and ranks; the service validates limits, identity, states and justifications and
  creates the runs. With enough candidates and basic data the normal result fills the remaining slots. A
  candidate is excluded only for a concrete impediment with a dated source: an official trading halt, or a
  proven reverse split, split or share bonus whose ex-date is likely inside the 20 sessions after the
  decision (`price_comparison_invalid`). The real window starts at the reference, which can wait for a
  monitoring slot, so this is assessed with the information available at decision time and recorded as such.
  Tender offers, judicial recovery, negative news, upcoming results and ex-dividend drops are risks that
  lower a candidate in the order, never exclusions by themselves.
- Missing complementary information is neutral and never excludes. The baseline order uses the turnover
  estimate at the observed price only when it is comparable for every pending candidate; otherwise a stable
  hash of session date and symbol, with no financial meaning. There is no score and no minimum confidence;
  nothing is presented as a probability of gain.
- Decisions are final for the session. Cancelling a selected run does not free its slot. A later collection
  of the session can fill only the slots still free. An analysis interrupted before sending its confirmation
  decides nothing. When the confirmation was sent but no receipt arrived, the outcome is unknown: the same
  request is retried with the same identifier, or the session is read before any new decision.
- Reference: the rules above, plus the quote's market time must not be earlier than the decision instant,
  the server time read after the confirmation was validated. Market information after that instant cannot
  enter the reference.
- Late selections are accepted: a confirmation at or after the opening of the following session is stored
  with `late` true. It cannot be presented as a choice made on the collection date; reports show the
  collection date, the selection time and the reference separately and keep late and on-time rates apart.

Candidates not selected are not tracked. Storing them makes the choice auditable but measures nothing about
their later prices, so no comparison between selected and discarded candidates is possible. Do not adjust
the criteria after seeing results; a change of criteria needs a new version.

## Simulated portfolios

Implemented in the daily report as `simulation_version` `exit-v1` and validated with synthetic data only.
The question it answers: had 100,000.00 been invested in the stocks of each collection date with fixed exit
triggers, which positions would have left, when the evidence was recorded and what the result would be. It is
a theoretical exercise rebuilt on every read from stored records; nothing is persisted, no order exists and
neither exit price proves an execution. Brokerage, taxes, dividends, execution modelling and corporate action
adjustments are excluded. Quotes are polled about every 30 minutes; this is not real time.

**Participants and capital.** Each collection date is an independent portfolio of 100,000.00. Under the
assisted policy only `selected` decisions take part; pending, not selected, not assessable and already tracked
candidates do not. Under the automatic policy the runs created from that date's observations take part;
reused runs are not counted again. The capital is split equally, truncated to the cent; the residual cents
stay in cash. The share of a participant without an entry stays in cash and is never redistributed.

**Composition frozen at the first entry.** At a cut, decisions decided up to the cut are ordered by decision
time (the run creation time under the automatic policy); decisions with the same time are treated as one
group. A group joins while its decision time is earlier than the first entry so far, the smallest market
time of a known reference among the members already included; a group decided at or after it is listed as
outside the portfolio, with no capital and no reallocation. A reference is known only when its quote was
quoted and received by the cut. The composition is `final` when a first entry is known and no reference that
is still unknown could exclude an included group: every group that follows a member without a known
reference was decided at least `MAX_QUOTE_AGE` (60 minutes, the service's quote age limit) before the cut.
A reference recorded on the run whose quote cannot be found, by the quote id in its evidence or by instrument,
source and market time, has no known receipt time and none is substituted: it never counts as a known first
entry, and any group decided at or after its market time keeps the composition provisional.
Otherwise it is `provisional` and every amount of the date is labelled provisional. A final composition does
not change with later receipts. Example, with confirmations on 14 October 18:05 for AAAA3 and CCCC3 and on 15
October 10:45 for BBBB4, AAAA3 quoted at 10:30 and received at 11:05, CCCC3 quoted at 10:20 and received at
11:15: at 10:50 no reference is known and the composition is provisional with the three; at 11:10 the first
entry is 10:30, BBBB4 is outside and the composition is final, because the only included group was decided
the day before; at 11:20 it is unchanged.

**Strategies.** A exits at +1% or -3%, B at +2% or -5%, C at +3% or -6%; HOLD never exits early. Each
strategy is independent. Thresholds are `reference * (1 + percent / 100)`; a quote reaches a target when its
price is greater than or equal to it and a stop when it is less than or equal to it, using only quotes with a
market time after the reference. The first reached trigger closes the position for that strategy; the
realized result stays fixed and the proceeds stay in cash, with no reinvestment or reentry. Two exit prices
are reported: the trigger price (idealized, the main result) and the first recorded quote that reached it.
Every trigger shows the quote's market time and the time the service received it.

**Precision.** Calculations run in a local Decimal context of 34 significant digits. A position value is
`allocation * price / reference`, rounded half up to the cent; the displayed quantity is rounded to eight
decimals for display and never used. Totals are sums of rounded components: cash is the residual plus pending
shares plus exit values, equity is cash plus open values, the result is equity minus 100,000.00 and equals
realized plus unrealized; the service checks these identities and fails the request if they diverge.

**Proven observation horizon.** A price quote belongs to the instrument and source, not to a run, and the
monitor can record a quote after a run was cancelled during the provider call. A run therefore uses only
quotes of its reference source with market and receipt times up to the cut, market time after the reference,
up to its expiry and before the reference of a later run of the same instrument, and only up to its horizon:

| Run | Horizon |
|---|---|
| Active or expired | The cut or the window close. The final status proves it was never cancelled |
| Completed | The market time of the quote at which the recorded quotes reached all six levels, or of the latest of the six quote linked hits, whichever is earlier. Before that the run is open at the cut |
| Cancelled, completed with a webhook hit, or overlapping a later run | The latest market time among the run's hits linked to a quote and received by the cut, otherwise the reference. Such a hit exists only if the run was open when that quote was processed, and quotes are processed in market time order |

Webhook hits never prove that a run was open. No cancellation time is inferred. An exit on a quote inside the
horizon is kept even if the run was cancelled later; a strategy without an exit inside a horizon that ended
early is `unproven` (or `observation_ended` after completion) with its last proven valuation and date. A
window that closed without an exit is `window_closed`, valued at the last quote up to the expiry, not a sale.
Runs without a known reference, waiting or cancelled before entry, are `pending_entry` with their share in
cash, never a zero return. A participant whose reference has no known receipt time is neither pending nor
entered: every strategy is `unproven` with no value, its share counts as affected capital instead of cash, the
totals are incomplete and `reference_receipt_unknown` is listed.

**Coverage and completeness.** Each strategy is checked over its own interval, from the reference to its exit
or to its horizon: a session without a recorded quote marks minimum coverage as missing for that strategy
only, so a gap after an exit does not affect that exit. The result is still computed on the recorded quotes.
When any position of a strategy is `unproven` or `observation_ended`, its equity and result are not
determinable: the report gives the known components and the affected capital, never a subtotal as equity.
Equity by session is not computed as of the report cut. Each point uses only what was available at its own
instant `valued_at`, the session close or the cut if earlier: a reference, an exit or a quote counts only when
both its market time and its receipt time are at or before that instant. A quote quoted before the close and
received after it is used from the next point on; until then the position is pending, or valued at the last
earlier available quote of that session that precedes the exit quote. An exit, once available at a point,
keeps its result at every later point. A session where an open position has no available quote, or after a
position's observation ended, or with a reference of unknown receipt time, has no value.

**Corporate actions.** There is no adjustment data. A large price move is shown as observed and never excluded
for its size. Risks recorded at selection (`corporate_event`, `ex_dividend`) are listed for information; an
explicit invalid comparison is never selected under the current rules.

**Example**, generated by the synthetic fixture in `tests/check_portfolio.py`: three participants with
33,333.33 each and 0.01 in cash; AAAA3 entered at 10.00 and later quoted 10.14, 10.22 and 10.25; BBBB4 entered
at 20.00 and was quoted 19.10 and 19.30; CCCC3 is waiting for entry.

| Strategy (trigger price) | Realized | Unrealized | Cash | Open | Equity | Result |
|---|---|---|---|---|---|---|
| A +1%/-3% | -666.67 | 0.00 | 99,333.33 | 0.00 | 99,333.33 | -666.67 (-0.67%) |
| B +2%/-5% | 666.67 | -1,166.67 | 67,333.34 | 32,166.66 | 99,500.00 | -500.00 (-0.50%) |
| C +3%/-6% | 0.00 | -333.34 | 33,333.34 | 66,333.32 | 99,666.66 | -333.34 (-0.33%) |
| HOLD | 0.00 | -333.34 | 33,333.34 | 66,333.32 | 99,666.66 | -333.34 (-0.33%) |

At the first recorded quote: A -1,033.33 (-1.03%), B -433.34 (-0.43%), C and HOLD unchanged.

Historical limits: runs completed before this version stop being observed at completion, so HOLD is truncated
there; cancelled runs without a later quote linked hit stay unproven from that hit or the reference; the last
minutes of each session are not polled.

## Earlier proposals for manual alerts

The following text predates the polling pilot and applies only to a possible manual-alert variant. Collection
after the regular session and checkpoints at 1 and 5 sessions were discussed, not validated. Manually
creating alerts after opening leaves a gap: do not backdate coverage to the opening unless an independent
price history covers that interval. For a manual pilot, an explicitly timestamped activation price may
be more reproducible; this changes the experiment and needs its own version.

Use exchange sessions and holidays, not calendar-day addition. Store UTC instants and derive session
dates in `America/Sao_Paulo`. Keep observed, source-published, received and activated times distinct.
An observed consensus tomorrow is not proof of a newly published recommendation tomorrow.

## Price and event semantics

Compute threshold = reference * (1 + signed percentage / 100) with decimal arithmetic. Preserve the
mathematical threshold and, where applicable, the configured tradable level with its rounding policy.
A crossing is not an execution at the level. Gaps may cross several thresholds at once.
Record each threshold's first supported occurrence; one hit does not stop the other five levels.
Order by trustworthy market/event evidence, not network arrival. Ties, coarse timestamps or two-sided
hits in one candle without finer evidence are indeterminate.

Reuse the open tracking run of an instrument instead of creating daily runs. Successive runs of one asset,
created after an earlier run ended, are still correlated; report both run count and distinct asset count.
Corporate actions can make raw changes misleading. Identify affected runs and exclude or mark them
unresolved until a documented adjustment policy and supporting data exist.

## Separate coverage dimensions

Collection completeness means the intended source list was traversed at that observation time. Alert
coverage means the required alerts were configured and active for a defined interval. Price coverage means
market events are available with enough detail to support the requested metric. None implies the others.
Store and report them separately. If regular trading hours are selected, apply that choice consistently
to reference acquisition, alert settings, expiry and reconciliation; the session policy is still pending.

## Metrics

Report threshold hit frequency within the window, time to first hit, and which side occurred first.
For every metric return numerator, eligible denominator, pending count, expired-without-hit count,
ambiguous count and incomplete-data count. A mature run with verified full coverage and no hit can be
a non-hit for hit frequency; it is a separate no-hit outcome for first-side comparisons.

With webhooks alone, label results as **observed notifications**. Do not classify silence as a verified
non-hit or report an unbiased hit rate over all runs. Coverage must be established by reconciliation or
an independent price source. Maximum favorable/adverse excursion and fixed-horizon returns require
price history beyond the six alerts; return unavailable until that history exists.

Comparisons by drop size or rating use predeclared cohorts and the same windows and quality rules.
Do not select filters after seeing results and present them as a validated strategy. Separate facts,
exploratory findings and hypotheses. Threshold performance is not net trading profit.
