from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TrackingLink = Literal["own", "reused_confirmed", "unconfirmed", "already_tracked", "selection_pending", "not_selected", "not_assessable"]
SelectionOutcome = Literal["pending", "selected", "not_selected", "not_assessable", "already_tracked"]
MilestoneState = Literal["future", "in_progress", "final", "no_data", "out_of_window", "not_available", "calendar_unavailable"]
TargetOrder = Literal["up_first", "down_first", "only_up", "only_down", "neither", "indeterminate", "not_assessed"]


class DailyReportQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=30)
    offset: int = Field(default=0, ge=0, le=10000)
    market_session_date: date | None = None
    signal_limit: int = Field(default=100, ge=1, le=100)
    signal_offset: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def signal_page_needs_one_date(self) -> "DailyReportQuery":
        if self.signal_offset and self.market_session_date is None:
            raise ValueError("signal_offset requires market_session_date")
        return self


class QuoteReading(BaseModel):
    price: Decimal
    quoted_at: datetime
    received_at: datetime
    return_percent: Decimal


class MilestoneOutput(BaseModel):
    sessions: int
    window_end: bool
    session_date: date | None
    state: MilestoneState
    reason: str | None
    quote: QuoteReading | None


class SignalProgress(BaseModel):
    observation_id: UUID
    collection_id: UUID
    instrument_id: UUID
    exchange: str
    symbol: str
    observed_at: datetime
    tracking_link: TrackingLink
    tracking_run_id: UUID | None
    origin_market_session_date: date | None
    status: str | None
    pending_reason: Literal["waiting_slot", "waiting_quote"] | None
    reference_price: Decimal | None
    reference_at: datetime | None
    reference_session_date: date | None
    expires_at: datetime | None
    latest_quote: QuoteReading | None
    milestones: list[MilestoneOutput]
    target_order: TargetOrder | None
    selection_outcome: SelectionOutcome | None = None
    selection_reason: str | None = None
    selection_rank: int | None = None
    selected_at: datetime | None = None
    selection_late: bool | None = None


class TargetRate(BaseModel):
    signed_percent: Decimal
    hits: int
    denominator: int
    rate_percent: Decimal | None
    indeterminate: int
    proven_hits_outside_sample: int


class RateBlock(BaseModel):
    runs: int
    eligible: int
    completed_early: int
    excluded_cancelled: int
    excluded_insufficient_coverage: int
    excluded_calendar_unavailable: int
    targets: list[TargetRate]


class HorizonOutput(BaseModel):
    sessions: int
    window_end: bool
    state: Literal["measured", "out_of_window"]
    future_runs: int
    concluded: RateBlock | None
    partial: RateBlock | None


class SelectionRecord(BaseModel):
    id: UUID
    decided_at: datetime
    late: bool
    ranking_basis: str
    no_selection_reason: str | None


class SelectionSummary(BaseModel):
    experiment_version: int
    criteria_version: str
    max_new_per_session: int
    collection_statuses: dict[str, int]
    eligible_observations: int
    candidates: int
    new_candidates: int
    already_tracked: int
    selected: int
    selected_on_time: int
    selected_late: int
    not_selected: dict[str, int]
    not_assessable: int
    pending: int
    selections: list[SelectionRecord]


class CollectionGroup(BaseModel):
    market_session_date: date
    selection_policy: Literal["automatic", "assisted"]
    experiment_version: int | None
    collection_ids: list[UUID]
    signals: int
    own_runs: int
    reused_confirmed: int
    unconfirmed_links: int
    with_reference: int
    waiting_slot: int
    waiting_quote: int
    active: int
    completed: int
    expired: int
    cancelled: int
    horizons: list[HorizonOutput]
    target_order: dict[str, int]
    late_horizons: list[HorizonOutput]
    late_target_order: dict[str, int]
    selection: SelectionSummary | None
    items: list[SignalProgress]
    signal_limit: int
    signal_offset: int
    signals_has_more: bool


class DailyReport(BaseModel):
    generated_at: datetime
    reference_session: str = "D+0 is the session of reference_at; D+N is the Nth following session of trading_days"
    coverage_rule: str = "minimum_daily_quote: at least one accepted quote per required session; not complete coverage"
    quote_semantics: str = "periodic polled quotes; never a closing, highest or lowest price"
    items: list[CollectionGroup]
    limit: int
    offset: int
    has_more: bool
