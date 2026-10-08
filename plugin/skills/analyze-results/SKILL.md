---
name: analyze-results
description: "Analyze persisted Stock Radar signals and trigger outcomes through read-only MCP tools. Use for cohort comparisons, hit frequencies and tracking histories, not for collecting new signals."
---

# Analyze Results

1. Read [the runtime contract](../../references/runtime-contract.md). Discover read-only analysis and quality tools and verify the service is available. Do not use database credentials or arbitrary SQL as a fallback.
2. Resolve the requested period, experiment version, metric and cohort filters. State reasonable query assumptions; do not mix different reference/window definitions without disclosure.
3. Request server-computed metrics and a coverage report. Use paginated evidence only when needed for explanation. Do not calculate global rates from a truncated list.
4. Present numerator/denominator, distinct instruments, pending and expired cases, ambiguity, missing data, as-of time and evidence IDs. Distinguish observed notifications from validated market outcomes.
5. Explain comparisons as descriptive evidence. Correlated daily runs are not independent trials. Separate source facts, exploratory findings and proposed hypotheses. If price-path data are absent, say that excursion or fixed-horizon return is unavailable. Do not write or alter experiments during analysis.
