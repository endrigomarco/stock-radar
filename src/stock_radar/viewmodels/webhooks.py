from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class WebhookInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1] = 1
    provider_event_id: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    alert_mapping_id: UUID
    tracking_run_id: UUID
    signed_percent: Decimal = Field(gt=-100, max_digits=12, decimal_places=6, allow_inf_nan=False)
    source_event_at: AwareDatetime
    observed_price: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8, allow_inf_nan=False)

    @field_validator("signed_percent")
    @classmethod
    def nonzero_threshold(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("Threshold cannot be zero")
        return value

    @field_validator("source_event_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class WebhookOutput(BaseModel):
    id: UUID
    status: Literal["pending", "processed", "unmapped", "failed"]
    received_at: datetime
    source_event_at: datetime | None
    processing_attempts: int
    last_error_code: str | None
    duplicate: bool = False
