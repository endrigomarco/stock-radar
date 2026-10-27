from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

PositionState = Literal["pending_entry", "open", "exited_target", "exited_stop", "window_closed", "observation_ended", "unproven"]
ObservationEnd = Literal["pending", "open", "window_closed", "completed", "cancelled", "completion_unknown", "overlapping_run"]
PendingReason = Literal["waiting_slot", "waiting_quote", "cancelled_without_entry"]


class QuoteEvidence(BaseModel):
    price: Decimal
    quoted_at: datetime
    received_at: datetime | None


class LatestQuote(BaseModel):
    symbol: str
    price: Decimal
    quoted_at: datetime
    received_at: datetime


class StrategyPosition(BaseModel):
    strategy: str
    state: PositionState
    trigger_percent: Decimal | None
    trigger_price: Decimal | None
    exit_quote: QuoteEvidence | None
    valuation: QuoteEvidence | None
    trigger_price_value: Decimal | None
    first_quote_value: Decimal | None
    trigger_price_result: Decimal | None
    first_quote_result: Decimal | None
    minimum_coverage: bool | None
    sessions_without_quote: list[date]


class PortfolioPosition(BaseModel):
    tracking_run_id: UUID
    instrument_id: UUID
    exchange: str
    symbol: str
    participation: Literal["participant", "outside_portfolio"]
    decided_at: datetime
    selection_late: bool | None
    recorded_risks: list[str]
    allocation: Decimal | None
    display_quantity: Decimal | None
    entry: QuoteEvidence | None
    pending_reason: PendingReason | None
    observation_end: ObservationEnd
    observed_until: datetime | None
    window_ends_at: datetime | None
    strategies: list[StrategyPosition]


class BasisTotals(BaseModel):
    exits_target: int
    exits_stop: int
    open: int
    window_closed: int
    pending_entry: int
    observation_ended: int
    unproven: int
    realized: Decimal
    unrealized: Decimal
    cash: Decimal
    open_value: Decimal
    complete: bool
    equity: Decimal | None
    result: Decimal | None
    result_percent: Decimal | None
    affected_capital: Decimal
    affected_positions: int
    minimum_coverage_missing_capital: Decimal
    minimum_coverage_missing_positions: int


class StrategySummary(BaseModel):
    strategy: str
    target_percent: Decimal | None
    stop_percent: Decimal | None
    added_in_version: str
    trigger_price: BasisTotals
    first_quote: BasisTotals


class TriggerRecord(BaseModel):
    symbol: str
    strategy: str
    exit_kind: Literal["target", "stop"]
    trigger_percent: Decimal
    trigger_price: Decimal
    quote: QuoteEvidence
    trigger_price_result: Decimal
    first_quote_result: Decimal


class SessionStrategyEquity(BaseModel):
    strategy: str
    trigger_price_equity: Decimal | None
    first_quote_equity: Decimal | None
    positions_without_quote: int
    positions_unobserved: int


class SessionEquity(BaseModel):
    session_date: date
    state: Literal["final", "in_progress"]
    valued_at: datetime
    strategies: list[SessionStrategyEquity]


class CompositionOutput(BaseModel):
    status: Literal["empty", "provisional", "final"]
    first_entry_at: datetime | None
    participants: int
    outside_portfolio: int
    allocation_per_participant: Decimal | None
    rounding_residual: Decimal


class PortfolioOutput(BaseModel):
    cut_at: datetime
    simulation_version: str
    initial_capital: Decimal
    provisional: bool
    latest_quote: LatestQuote | None
    composition: CompositionOutput
    strategies: list[StrategySummary]
    triggers: list[TriggerRecord]
    positions: list[PortfolioPosition]
    equity_by_session: list[SessionEquity]
    limitations: list[str]
