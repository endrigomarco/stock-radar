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
