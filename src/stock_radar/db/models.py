from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Source(IdentityMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (CheckConstraint("length(trim(code)) > 0", name="code_not_blank"),)

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str | None] = mapped_column(Text)


class Instrument(IdentityMixin, Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol"),
        CheckConstraint("length(trim(exchange)) > 0 AND length(trim(symbol)) > 0", name="identity_not_blank"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    exchange: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    name: Mapped[str | None] = mapped_column(String(200))


class CollectionRun(IdentityMixin, Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        UniqueConstraint("source_id", "client_collection_id"),
        CheckConstraint("status IN ('complete', 'partial', 'failed')", name="status_valid"),
        CheckConstraint("source_total IS NULL OR source_total >= 0", name="source_total_nonnegative"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index("ix_collection_runs_source_observed", "source_id", "observed_at"),
    )

    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    client_collection_id: Mapped[UUID] = mapped_column(Uuid)
    payload_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    market_session_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    source_total: Mapped[int | None] = mapped_column(Integer)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class SignalObservation(IdentityMixin, Base):
    __tablename__ = "signal_observations"
    __table_args__ = (
        UniqueConstraint("collection_run_id", "instrument_id", "signal_kind"),
        CheckConstraint("observed_price IS NULL OR observed_price > 0", name="price_positive"),
        CheckConstraint("daily_change_percent IS NULL OR daily_change_percent >= -100", name="change_valid"),
        CheckConstraint("parse_status IN ('valid', 'partial', 'invalid')", name="parse_status_valid"),
        CheckConstraint("length(trim(signal_kind)) > 0", name="signal_kind_not_blank"),
    )

    collection_run_id: Mapped[UUID] = mapped_column(ForeignKey("collection_runs.id", ondelete="RESTRICT"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    signal_kind: Mapped[str] = mapped_column(String(64))
    source_symbol: Mapped[str] = mapped_column(String(80))
    source_column: Mapped[str | None] = mapped_column(String(120))
    original_rating: Mapped[str | None] = mapped_column(Text)
    normalized_rating: Mapped[str | None] = mapped_column(String(64))
    normalization_version: Mapped[str] = mapped_column(String(64))
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    daily_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_status: Mapped[str] = mapped_column(String(16))
    raw_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    quality_details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Experiment(IdentityMixin, Base):
    __tablename__ = "experiments"
    __table_args__ = (CheckConstraint("length(trim(code)) > 0", name="code_not_blank"),)

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)


class ExperimentVersion(IdentityMixin, Base):
    __tablename__ = "experiment_versions"
    __table_args__ = (
        UniqueConstraint("experiment_id", "version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(trim(analysis_kind)) > 0", name="analysis_kind_not_blank"),
        CheckConstraint("jsonb_typeof(rules) = 'object'", name="rules_object"),
    )

    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    analysis_kind: Mapped[str] = mapped_column(String(64))
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TrackingRun(IdentityMixin, Base):
    __tablename__ = "tracking_runs"
    __table_args__ = (
        CheckConstraint("reference_price > 0", name="reference_positive"),
        CheckConstraint("status IN ('prepared', 'active', 'completed', 'cancelled')", name="status_valid"),
        CheckConstraint("price_coverage IN ('unknown', 'partial', 'verified')", name="price_coverage_valid"),
        CheckConstraint("expires_at > reference_at", name="expiry_after_reference"),
        CheckConstraint("activated_at IS NULL OR (activated_at >= reference_at AND activated_at < expires_at)", name="activation_window"),
        CheckConstraint("status != 'active' OR activated_at IS NOT NULL", name="active_requires_activation"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
    )

    client_tracking_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    signal_observation_id: Mapped[UUID] = mapped_column(ForeignKey("signal_observations.id", ondelete="RESTRICT"), index=True)
    experiment_version_id: Mapped[UUID] = mapped_column(ForeignKey("experiment_versions.id", ondelete="RESTRICT"), index=True)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    reference_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference_source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    reference_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="prepared")
    price_coverage: Mapped[str] = mapped_column(String(16), server_default="unknown")
    coverage_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class TriggerLevel(IdentityMixin, Base):
    __tablename__ = "trigger_levels"
    __table_args__ = (
        UniqueConstraint("tracking_run_id", "signed_percent"),
        CheckConstraint("signed_percent > -100 AND signed_percent != 0", name="percent_valid"),
        CheckConstraint("mathematical_price > 0 AND (configured_price IS NULL OR configured_price > 0)", name="prices_positive"),
        CheckConstraint("alert_coverage IN ('unknown', 'partial', 'verified')", name="alert_coverage_valid"),
        CheckConstraint("alert_expires_at IS NULL OR (alert_active_at IS NOT NULL AND alert_expires_at > alert_active_at)", name="alert_window"),
    )

    tracking_run_id: Mapped[UUID] = mapped_column(ForeignKey("tracking_runs.id", ondelete="RESTRICT"))
    signed_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    mathematical_price: Mapped[Decimal] = mapped_column(Numeric(38, 16))
    configured_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    rounding_policy: Mapped[str | None] = mapped_column(String(64))
    alert_mapping_id: Mapped[UUID] = mapped_column(Uuid, unique=True, server_default=func.gen_random_uuid())
    alert_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    alert_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_coverage: Mapped[str] = mapped_column(String(16), server_default="unknown")
    alert_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class WebhookReceipt(IdentityMixin, Base):
    __tablename__ = "webhook_receipts"
    __table_args__ = (
        UniqueConstraint("source_id", "deduplication_key"),
        CheckConstraint("length(trim(deduplication_key)) > 0", name="deduplication_key_not_blank"),
        CheckConstraint("status IN ('pending', 'processed', 'unmapped', 'failed')", name="status_valid"),
        CheckConstraint("processing_attempts >= 0", name="attempts_nonnegative"),
        Index("ix_webhook_receipts_status_received", "status", "received_at"),
    )

    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    deduplication_key: Mapped[str] = mapped_column(String(200))
    provider_event_id: Mapped[str | None] = mapped_column(String(200))
    reported_alert_mapping_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sanitized_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    processing_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))


class TriggerEvent(IdentityMixin, Base):
    __tablename__ = "trigger_events"
    __table_args__ = (
        UniqueConstraint("trigger_level_id"),
        CheckConstraint("observed_price IS NULL OR observed_price > 0", name="price_positive"),
        CheckConstraint("evidence_quality IN ('timestamped', 'coarse', 'unknown')", name="evidence_quality_valid"),
    )

    trigger_level_id: Mapped[UUID] = mapped_column(ForeignKey("trigger_levels.id", ondelete="RESTRICT"))
    webhook_receipt_id: Mapped[UUID] = mapped_column(ForeignKey("webhook_receipts.id", ondelete="RESTRICT"), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    evidence_quality: Mapped[str] = mapped_column(String(16), server_default="unknown")
