# Product overview

## User and value

A single owner uses Claude Cowork to collect observations and ask questions about a continuously stored
history on an existing VPS. Stock Radar tests market signals prospectively and preserves the evidence
behind its results. It does not execute trades or promise returns.

## MVP workflow

1. Read the Brazilian biggest-losers universe and preserve the observed list, including other ratings
   when available for comparison. Record whether the traversal was complete.
2. Select negative daily changes with analyst consensus Strong Buy.
3. Start a versioned tracking run using an explicit reference price and observation window.
4. Receive six directional threshold notifications and retain their evidence.
5. Ask Claude for results, sample sizes, unresolved cases and data-quality limitations through MCP.

The source is TradingView; the rating represents analyst consensus, not TradingView's own individual
buy recommendation. Preserve the original label and never infer the underlying broker, target price,
recommendation date or rationale when absent.

## Scope

Daily collection by the local plugin, authenticated ingestion, PostgreSQL persistence, webhook receipt,
read-only analytical MCP tools, and Claude explanations. Alert configuration is initially manual.
Daily scheduling is a later configured operation, not something a skill file starts automatically.

## Non-goals

No frontend, order execution, portfolio management, billing, multi-user SaaS, automatic broker decisions,
image-post extraction or Pine Script backtesting in the first increment. Future sources and signal kinds
reuse source identity and versioned experiments, without implementing their adapters now.

## Evidence and outcomes

Keep success definitions fixed before evaluating a cohort. A +3% hit after a -3% hit is not equivalent
to +3% first. Missing deliveries cannot establish that a price never crossed a threshold.
See [experiment](experiment.md) for metric eligibility and pending decisions.
