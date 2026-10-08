from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TrackingRunQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    status: Literal["prepared", "active", "completed", "cancelled", "expired"] | None = None
    instrument_id: UUID | None = None


class TrackingRunOutput(BaseModel):
    id: UUID
    instrument_id: UUID
    exchange: str
    symbol: str
    experiment_version_id: UUID
    signal_observation_id: UUID
    status: str
    created_at: datetime
    admitted_at: datetime | None
    reference_price: Decimal | None
    reference_at: datetime | None
    activated_at: datetime | None
    expires_at: datetime | None
    price_coverage: str
    levels_total: int
    levels_hit: int


class TrackingRunPage(BaseModel):
    items: list[TrackingRunOutput]
    limit: int
    offset: int
    has_more: bool


class LatestQuoteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    instrument_id: UUID | None = None


class QuoteOutput(BaseModel):
    id: UUID
    instrument_id: UUID
    exchange: str
    symbol: str
    source_id: UUID
    price: Decimal
    quoted_at: datetime
    received_at: datetime


class QuotePage(BaseModel):
    items: list[QuoteOutput]
    limit: int
    offset: int
    has_more: bool


class TriggerEventQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    tracking_run_id: UUID | None = None
    instrument_id: UUID | None = None


class TriggerEventOutput(BaseModel):
    id: UUID
    tracking_run_id: UUID
    instrument_id: UUID
    symbol: str
    signed_percent: Decimal
    threshold_price: Decimal
    occurred_at: datetime | None
    observed_price: Decimal | None
    evidence_quality: str
    evidence_kind: Literal["price_quote", "webhook"]
    price_quote_id: UUID | None
    webhook_receipt_id: UUID | None


class TriggerEventPage(BaseModel):
    items: list[TriggerEventOutput]
    limit: int
    offset: int
    has_more: bool
