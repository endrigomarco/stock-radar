from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QualityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=30, ge=1, le=31)
    source_id: UUID | None = None


class QualityOutput(BaseModel):
    as_of: datetime
    since: datetime
    source_id: UUID | None
    collections: int
    partial_collections: int
    failed_collections: int
    observations: int
    incomplete_observations: int
    scheduling_assessed: bool = False
    price_coverage_assessed: bool = False


class StatusOutput(BaseModel):
    version: str = "0.1.0"
    database_available: bool = True
    last_complete_collection_at: datetime | None
    capabilities: list[str] = ["sources", "collections", "signals", "data_quality", "webhook_receipts", "tracking_runs", "price_quotes", "trigger_events"]
