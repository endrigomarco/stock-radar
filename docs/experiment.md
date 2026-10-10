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
  and reuses the `prepared` or `active` run; it never resets reference, window or levels. A run is created only
  together with its origin observation, so a consumed observation cannot create another run.
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
