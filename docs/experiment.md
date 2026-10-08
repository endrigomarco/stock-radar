# Experiment rules

## Established scope

Universe: Brazilian stocks observed on TradingView's biggest losers list.
Selection: daily price change below zero and analyst rating Strong Buy (`Viés de alta forte`).
Store source labels as well as normalized values. Missing, neutral and technical ratings do not qualify.
Thresholds: +1%, +2%, +3%, -1%, -2%, -3%, each relative to one immutable reference price per tracking run.

## Proposed defaults, not yet activated

Collect after the regular session. Start monitoring at the next session's opening, with checkpoints at
1, 5 and 20 trading sessions. These were discussed as defaults, not validated operating rules.
Before implementation, choose a source for the reference trade and define activation timing. Manually
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

Keep daily tracking runs separate, but deduplicate retries of the same run creation. Overlapping runs
for one asset are correlated; report both run count and distinct asset count.
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
