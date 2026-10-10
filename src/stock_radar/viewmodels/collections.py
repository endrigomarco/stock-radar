from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

ShortText = Annotated[str, Field(max_length=2000)]


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9_]+$")
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source_symbol: str = Field(min_length=1, max_length=80)
    signal_kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    source_column: str | None = Field(default=None, max_length=120)
    original_rating: str | None = Field(default=None, max_length=2000)
    observed_price: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8, allow_inf_nan=False)
    daily_change_percent: Decimal | None = Field(default=None, ge=-100, max_digits=12, decimal_places=6, allow_inf_nan=False)
    observed_at: AwareDatetime
    source_published_at: AwareDatetime | None = None
    raw_evidence: dict[str, ShortText | None] = Field(default_factory=dict, max_length=20)

    @field_validator("observed_at", "source_published_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(timezone.utc) if value else None


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    client_collection_id: UUID
    source_id: UUID
    source_url: HttpUrl = Field(max_length=2000)
    observed_at: AwareDatetime
    market_session_date: date
    status: Literal["complete", "partial", "failed"]
    source_total: int | None = Field(default=None, ge=0, le=2147483647)
    rows_examined: int = Field(ge=0, le=2147483647)
    filters: dict[str, ShortText] = Field(default_factory=dict, max_length=20)
    observations: list[ObservationInput] = Field(max_length=2000)

    @field_validator("source_url")
    @classmethod
    def no_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("URL credentials are not allowed")
        return value

    @field_validator("observed_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_rows(self) -> "CollectionInput":
        identities = [(row.exchange, row.symbol, row.signal_kind) for row in self.observations]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate observations in collection")
        if self.status == "failed" and self.observations:
            raise ValueError("Failed collections cannot contain accepted observations")
        if len(self.observations) > self.rows_examined:
            raise ValueError("Observations cannot exceed the rows examined")
        if self.status == "complete" and self.source_total is not None and self.rows_examined != self.source_total:
            raise ValueError("A complete collection must examine every row of the displayed total")
        return self


class CollectionOutput(BaseModel):
    id: UUID
    source_id: UUID
    client_collection_id: UUID
    status: str
    observed_at: datetime
    received_at: datetime
    source_total: int | None
    rows_examined: int | None
    observation_count: int
    eligible_count: int
    incomplete_count: int
    duplicate: bool = False


class SignalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    collection_id: UUID | None = None
    source_id: UUID | None = None
    instrument_id: UUID | None = None
    eligible_only: bool = False


class SignalOutput(BaseModel):
    id: UUID
    collection_id: UUID
    instrument_id: UUID
    signal_kind: str
    source_symbol: str
    original_rating: str | None
    normalized_rating: str | None
    observed_price: Decimal | None
    daily_change_percent: Decimal | None
    observed_at: datetime
    parse_status: str
    eligible: bool


class SignalPage(BaseModel):
    items: list[SignalOutput]
    limit: int
    offset: int
    has_more: bool
