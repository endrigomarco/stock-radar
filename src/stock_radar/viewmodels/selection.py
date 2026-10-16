from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Outcome = Literal["pending", "selected", "not_selected", "not_assessable", "already_tracked"]
SubmittedOutcome = Literal["selected", "not_selected", "not_assessable", "already_tracked"]
NotSelectedReason = Literal["outranked", "trading_halted", "price_comparison_invalid", "other_concrete_impediment"]
NotAssessableReason = Literal["essential_data_missing", "identity_unresolved"]
ReasonCode = NotSelectedReason | NotAssessableReason
EvidenceKind = Literal["news", "filing", "results", "recommendation", "sector_move", "corporate_event", "market_data", "other"]
RiskCode = Literal["upcoming_results", "tender_offer", "judicial_recovery", "negative_news", "ex_dividend", "corporate_event", "low_liquidity_estimate", "other"]
UnavailableCode = Literal["drop_cause", "upcoming_events", "recommendation_details", "sector", "volume", "price", "spread", "other"]
NOT_SELECTED_REASONS = {"outranked", "trading_halted", "price_comparison_invalid", "other_concrete_impediment"}
NOT_ASSESSABLE_REASONS = {"essential_data_missing", "identity_unresolved"}
DATED_REASONS = {"trading_halted", "price_comparison_invalid"}
ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class CandidateQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_session_date: date | None = None


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    publisher: ShortText
    origin: ShortText | None = None
    url: HttpUrl | None = Field(default=None, max_length=2000)
    title: ShortText | None = None
    published_at: AwareDatetime | None = None
    consulted_at: AwareDatetime
    summary: str = Field(min_length=1, max_length=1000)
    stance: Literal["favorable", "unfavorable", "neutral"]

    @field_validator("published_at", "consulted_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(timezone.utc) if value else None

    @field_validator("url")
    @classmethod
    def no_url_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.username or value.password):
            raise ValueError("URL credentials are not allowed")
        return value

    @model_validator(mode="after")
    def published_before_consulted(self) -> "EvidenceInput":
        if self.published_at is not None and self.published_at > self.consulted_at:
            raise ValueError("Evidence cannot be published after it was consulted")
        return self


class RiskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: RiskCode
    text: str = Field(min_length=1, max_length=500)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    outcome: SubmittedOutcome
    reason_code: ReasonCode | None = None
    rank: int | None = Field(default=None, ge=1, le=200)
    rationale: str = Field(min_length=1, max_length=2000)
    event_date: date | None = None
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=10)
    unavailable: list[UnavailableCode] = Field(default_factory=list, max_length=8)
    risks: list[RiskInput] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def reason_matches_outcome(self) -> "DecisionInput":
        if self.outcome in ("selected", "already_tracked") and self.reason_code is not None:
            raise ValueError("Selected and already tracked decisions take no reason code")
        if self.outcome == "not_selected" and self.reason_code not in NOT_SELECTED_REASONS:
            raise ValueError("A not selected decision needs a not selected reason code")
        if self.outcome == "not_assessable" and self.reason_code not in NOT_ASSESSABLE_REASONS:
            raise ValueError("A not assessable decision needs a not assessable reason code")
        ranked = self.outcome == "selected" or self.reason_code == "outranked"
        if ranked != (self.rank is not None):
            raise ValueError("Rank is required exactly for selected and outranked decisions")
        if self.reason_code in DATED_REASONS and not any(item.published_at is not None for item in self.evidence):
            raise ValueError("This reason needs at least one dated source")
        if (self.reason_code == "price_comparison_invalid") != (self.event_date is not None):
            raise ValueError("event_date is required exactly for price_comparison_invalid")
        return self


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_selection_id: UUID
    market_session_date: date
    criteria_version: str = Field(min_length=1, max_length=64)
    ranking_basis: Literal["full", "limited"]
    summary: str = Field(min_length=1, max_length=4000)
    no_selection_reason: str | None = Field(default=None, min_length=1, max_length=2000)
    plugin_version: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[0-9A-Za-z.+-]+$")
    decisions: list[DecisionInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def consistent_decisions(self) -> "SelectionInput":
        identities = [item.decision_id for item in self.decisions]
        if len(set(identities)) != len(identities):
            raise ValueError("Each decision may appear once")
        ranks = sorted(item.rank for item in self.decisions if item.rank is not None)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Ranks must be unique and contiguous from 1")
        selected = sorted(item.rank for item in self.decisions if item.outcome == "selected")
        if selected != list(range(1, len(selected) + 1)):
            raise ValueError("Selected decisions must hold the best ranks")
        if not selected and self.no_selection_reason is None:
            raise ValueError("A selection without selected candidates needs no_selection_reason")
        return self


class CollectionReference(BaseModel):
    id: UUID
    status: str
    observed_at: datetime
    received_at: datetime
    observation_count: int


class CandidateOutput(BaseModel):
    decision_id: UUID
    instrument_id: UUID
    exchange: str
    symbol: str
    signal_observation_id: UUID
    collection_id: UUID
    observed_at: datetime
    observed_price: Decimal | None
    daily_change_percent: Decimal | None
    original_rating: str | None
    volume: Decimal | None
    sector: str | None
    estimated_turnover_at_observed_price: Decimal | None
    turnover_partial_session: bool | None
    turnover_unavailable_reason: Literal["price_missing", "volume_missing", "price_and_volume_missing"] | None
    open_tracking_run_id: UUID | None
    baseline_rank: int | None
    outcome: Outcome
    reason_code: str | None
    rank: int | None
    slot: int | None
    tracking_run_id: UUID | None
    rationale: str | None
    details: dict[str, Any]
    decided_at: datetime | None
    selection_late: bool | None


class CandidateSession(BaseModel):
    market_session_date: date
    experiment_version: int
    criteria_version: str
    max_new_per_session: int
    slots_used: int
    slots_remaining: int
    next_session_opens_at: datetime
    late_if_confirmed_now: bool
    liquidity_comparable: bool
    baseline_rule: str
    collections: list[CollectionReference]
    pending: int
    candidates: list[CandidateOutput]
    tiebreak_note: str = "sha256 of session date and symbol: a stable administrative order with no financial meaning"
    turnover_note: str = "observed price times displayed share volume: an estimate, not traded value and not a daily average"


class SelectedRun(BaseModel):
    decision_id: UUID
    symbol: str
    slot: int
    tracking_run_id: UUID


class SelectionOutput(BaseModel):
    id: UUID
    client_selection_id: UUID
    market_session_date: date
    experiment_version: int
    criteria_version: str
    decided_at: datetime
    late: bool
    selected: list[SelectedRun]
    not_selected: int
    not_assessable: int
    already_tracked: int
    slots_remaining: int
    duplicate: bool = False
