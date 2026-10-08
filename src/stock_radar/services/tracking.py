from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import logging
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_radar.db.models import (
    Experiment,
    ExperimentVersion,
    Instrument,
    PriceQuote,
    SignalObservation,
    Source,
    TrackingRun,
    TriggerEvent,
    TriggerLevel,
)
from stock_radar.market_calendar import CalendarUnavailable, in_session, window_close
from stock_radar.observability.logging import emit
from stock_radar.services.errors import ServiceError
from stock_radar.viewmodels.tracking import (
    LatestQuoteQuery,
    QuoteOutput,
    QuotePage,
    TrackingRunOutput,
    TrackingRunPage,
    TrackingRunQuery,
    TriggerEventOutput,
    TriggerEventPage,
    TriggerEventQuery,
)

EXPERIMENT_CODE = "tradingview_losers_strong_buy"
QUOTE_SOURCE_CODE = "brapi"
QUOTE_SOURCE_NAME = "brapi"
POLL_INTERVAL_MINUTES = 30
FUTURE_TOLERANCE = timedelta(minutes=2)
MAX_QUOTE_AGE = timedelta(minutes=60)
OPEN_STATUSES = ("prepared", "active")
CLOSED_STATUSES = ("completed", "expired")
ADMISSION_LOCK_KEY = "stock_radar:tracking_admission"
PERCENT_BASE = Decimal(100)


@dataclass(frozen=True)
class MonitoredInstrument:
    id: UUID
    symbol: str
    currency: str


def quote_rejection(quoted_at: datetime, received_at: datetime) -> str | None:
    if quoted_at > received_at + FUTURE_TOLERANCE:
        return "quote_in_future"
    if received_at - quoted_at > MAX_QUOTE_AGE:
        return "quote_too_old"
    try:
        if not in_session(quoted_at):
            return "quote_outside_session"
    except CalendarUnavailable:
        return "calendar_unavailable"
    return None


class TrackingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def current_version(self) -> ExperimentVersion | None:
        return self.session.scalar(
            select(ExperimentVersion).join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
            .where(Experiment.code == EXPERIMENT_CODE).order_by(ExperimentVersion.version.desc()).limit(1)
        )

    def attach(self, observation_id: UUID, instrument_id: UUID, version: ExperimentVersion) -> bool:
        self._lock(f"stock_radar:tracking:{version.experiment_id}:{instrument_id}")
        existing = self.session.scalar(
            select(TrackingRun.id)
            .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
            .join(ExperimentVersion, ExperimentVersion.id == TrackingRun.experiment_version_id)
            .where(
                SignalObservation.instrument_id == instrument_id,
                ExperimentVersion.experiment_id == version.experiment_id,
                TrackingRun.status.in_(OPEN_STATUSES),
            ).limit(1)
        )
        if existing is not None:
            return False
        digest = hashlib.sha256(f"{version.id}:{observation_id}".encode()).hexdigest()
        self.session.add(TrackingRun(
            client_tracking_id=uuid4(), payload_hash=digest,
            signal_observation_id=observation_id, experiment_version_id=version.id,
        ))
        self.session.flush()
        return True

    def ensure_quote_source(self) -> UUID:
        with self.session.begin():
            self.session.execute(insert(Source).values(code=QUOTE_SOURCE_CODE, name=QUOTE_SOURCE_NAME).on_conflict_do_nothing(index_elements=[Source.code]))
            return self.session.scalar(select(Source.id).where(Source.code == QUOTE_SOURCE_CODE))

    def expire(self, now: datetime) -> list[UUID]:
        with self.session.begin():
            return list(self.session.scalars(
                update(TrackingRun)
                .where(TrackingRun.status == "active", TrackingRun.admitted_at.is_not(None), TrackingRun.expires_at <= now)
                .values(status="expired").returning(TrackingRun.id)
            ).all())

    def admit(self, capacity: int, now: datetime) -> list[UUID]:
        with self.session.begin():
            self._lock(ADMISSION_LOCK_KEY)
            occupied = set(self.session.scalars(
                select(SignalObservation.instrument_id)
                .join(TrackingRun, TrackingRun.signal_observation_id == SignalObservation.id)
                .where(TrackingRun.admitted_at.is_not(None), TrackingRun.status.in_(OPEN_STATUSES)).distinct()
            ).all())
            waiting = self.session.execute(
                select(TrackingRun, SignalObservation.instrument_id)
                .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
                .join(ExperimentVersion, ExperimentVersion.id == TrackingRun.experiment_version_id)
                .join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
                .where(
                    Experiment.code == EXPERIMENT_CODE, TrackingRun.status == "prepared",
                    TrackingRun.admitted_at.is_(None), TrackingRun.reference_price.is_(None),
                ).order_by(TrackingRun.created_at, TrackingRun.id).with_for_update(of=TrackingRun)
            ).all()
            admitted = []
            for run, instrument_id in waiting:
                if instrument_id not in occupied and len(occupied) >= capacity:
                    continue
                run.admitted_at = now
                occupied.add(instrument_id)
                admitted.append(run.id)
            return admitted

    def monitored_instruments(self, now: datetime) -> list[MonitoredInstrument]:
        rows = self.session.execute(
            select(Instrument.id, Instrument.symbol, Instrument.currency)
            .join(SignalObservation, SignalObservation.instrument_id == Instrument.id)
            .join(TrackingRun, TrackingRun.signal_observation_id == SignalObservation.id)
            .where(
                TrackingRun.admitted_at.is_not(None),
                or_(TrackingRun.status == "prepared", (TrackingRun.status == "active") & (TrackingRun.expires_at > now)),
            ).distinct().order_by(Instrument.symbol, Instrument.id)
        ).all()
        return [MonitoredInstrument(id=row.id, symbol=row.symbol, currency=row.currency) for row in rows]

    def apply_quote(self, instrument_id: UUID, source_id: UUID, price: Decimal, quoted_at: datetime, received_at: datetime) -> str:
        with self.session.begin():
            latest = self.session.scalar(select(func.max(PriceQuote.quoted_at)).where(
                PriceQuote.instrument_id == instrument_id, PriceQuote.source_id == source_id,
            ))
            if latest is not None and quoted_at <= latest:
                return "unchanged"
            quote_id = self.session.scalar(insert(PriceQuote).values(
                instrument_id=instrument_id, source_id=source_id, price=price, quoted_at=quoted_at, received_at=received_at,
            ).on_conflict_do_nothing(index_elements=[PriceQuote.instrument_id, PriceQuote.source_id, PriceQuote.quoted_at]).returning(PriceQuote.id))
            if quote_id is None:
                return "unchanged"
            runs = self.session.scalars(
                select(TrackingRun)
                .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
                .where(
                    SignalObservation.instrument_id == instrument_id,
                    TrackingRun.admitted_at.is_not(None), TrackingRun.status.in_(OPEN_STATUSES),
                ).order_by(TrackingRun.created_at, TrackingRun.id).with_for_update(of=TrackingRun)
            ).all()
            for run in runs:
                if run.status == "prepared":
                    self._activate(run, quote_id, source_id, price, quoted_at, received_at)
                else:
                    self._evaluate(run, quote_id, price, quoted_at)
        return "recorded"

    def cancel(self, tracking_run_id: UUID) -> TrackingRunOutput:
        with self.session.begin():
            run = self.session.scalar(select(TrackingRun).where(TrackingRun.id == tracking_run_id).with_for_update())
            if run is None:
                raise ServiceError("tracking_run_not_found", 404)
            if run.status in CLOSED_STATUSES:
                raise ServiceError("tracking_run_closed", 409)
            if run.status != "cancelled":
                run.status = "cancelled"
                self.session.flush()
            return self._run_rows(select_run_id=tracking_run_id)[0]

    def list_runs(self, request: TrackingRunQuery) -> TrackingRunPage:
        items = self._run_rows(request=request)
        return TrackingRunPage(items=items[:request.limit], limit=request.limit, offset=request.offset, has_more=len(items) > request.limit)

    def list_latest_quotes(self, request: LatestQuoteQuery) -> QuotePage:
        statement = (
            select(PriceQuote, Instrument.exchange, Instrument.symbol)
            .join(Instrument, Instrument.id == PriceQuote.instrument_id)
            .distinct(PriceQuote.instrument_id)
            .order_by(PriceQuote.instrument_id, PriceQuote.quoted_at.desc(), PriceQuote.id)
        )
        if request.instrument_id:
            statement = statement.where(PriceQuote.instrument_id == request.instrument_id)
        rows = self.session.execute(statement.limit(request.limit + 1).offset(request.offset)).all()
        items = [QuoteOutput(
            id=quote.id, instrument_id=quote.instrument_id, exchange=exchange, symbol=symbol, source_id=quote.source_id,
            price=quote.price, quoted_at=quote.quoted_at, received_at=quote.received_at,
        ) for quote, exchange, symbol in rows[:request.limit]]
        return QuotePage(items=items, limit=request.limit, offset=request.offset, has_more=len(rows) > request.limit)

    def list_events(self, request: TriggerEventQuery) -> TriggerEventPage:
        statement = (
            select(TriggerEvent, TriggerLevel, SignalObservation.instrument_id, Instrument.symbol)
            .join(TriggerLevel, TriggerLevel.id == TriggerEvent.trigger_level_id)
            .join(TrackingRun, TrackingRun.id == TriggerLevel.tracking_run_id)
            .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
            .join(Instrument, Instrument.id == SignalObservation.instrument_id)
            .order_by(TriggerEvent.occurred_at.desc().nullslast(), TriggerEvent.id)
        )
        if request.tracking_run_id:
            statement = statement.where(TriggerLevel.tracking_run_id == request.tracking_run_id)
        if request.instrument_id:
            statement = statement.where(SignalObservation.instrument_id == request.instrument_id)
        rows = self.session.execute(statement.limit(request.limit + 1).offset(request.offset)).all()
        items = [TriggerEventOutput(
            id=event.id, tracking_run_id=level.tracking_run_id, instrument_id=instrument_id, symbol=symbol,
            signed_percent=level.signed_percent, threshold_price=level.configured_price or level.mathematical_price,
            occurred_at=event.occurred_at, observed_price=event.observed_price, evidence_quality=event.evidence_quality,
            evidence_kind="price_quote" if event.price_quote_id else "webhook",
            price_quote_id=event.price_quote_id, webhook_receipt_id=event.webhook_receipt_id,
        ) for event, level, instrument_id, symbol in rows[:request.limit]]
        return TriggerEventPage(items=items, limit=request.limit, offset=request.offset, has_more=len(rows) > request.limit)

    def _activate(self, run: TrackingRun, quote_id: UUID, source_id: UUID, price: Decimal, quoted_at: datetime, received_at: datetime) -> None:
        if run.reference_price is not None or received_at < run.admitted_at:
            return
        origin = self.session.scalar(select(SignalObservation.observed_at).where(SignalObservation.id == run.signal_observation_id))
        if quoted_at < origin:
            return
        rules = self.session.scalar(select(ExperimentVersion.rules).where(ExperimentVersion.id == run.experiment_version_id))
        try:
            expires_at = window_close(quoted_at, int(rules["window_sessions"]))
        except CalendarUnavailable as error:
            emit("calendar_coverage_missing", logging.WARNING, tracking_run_id=str(run.id), year=error.year)
            return
        if expires_at <= quoted_at:
            return
        run.reference_price = price
        run.reference_at = quoted_at
        run.reference_source_id = source_id
        run.reference_evidence = {"price_quote_id": str(quote_id), "provider": QUOTE_SOURCE_CODE}
        run.activated_at = quoted_at
        run.expires_at = expires_at
        run.status = "active"
        run.price_coverage = "partial"
        run.coverage_evidence = {"method": "polling", "provider": QUOTE_SOURCE_CODE, "interval_minutes": POLL_INTERVAL_MINUTES}
        for percent in rules["signed_percents"]:
            signed = Decimal(percent)
            self.session.add(TriggerLevel(
                tracking_run_id=run.id, signed_percent=signed,
                mathematical_price=price * (1 + signed / PERCENT_BASE),
            ))
        self.session.flush()
        emit("tracking_activated", tracking_run_id=str(run.id), expires_at=expires_at.isoformat())

    def _evaluate(self, run: TrackingRun, quote_id: UUID, price: Decimal, quoted_at: datetime) -> None:
        if not run.activated_at < quoted_at <= run.expires_at:
            return
        levels = self.session.scalars(select(TriggerLevel).where(TriggerLevel.tracking_run_id == run.id)).all()
        reached = [
            level for level in levels
            if (level.signed_percent > 0 and price >= level.mathematical_price)
            or (level.signed_percent < 0 and price <= level.mathematical_price)
        ]
        if reached:
            self.session.execute(insert(TriggerEvent).values([{
                "trigger_level_id": level.id, "price_quote_id": quote_id, "occurred_at": quoted_at,
                "observed_price": price, "evidence_quality": "coarse",
            } for level in reached]).on_conflict_do_nothing(index_elements=[TriggerEvent.trigger_level_id]))
        recorded = self.session.scalar(
            select(func.count(TriggerEvent.id))
            .join(TriggerLevel, TriggerLevel.id == TriggerEvent.trigger_level_id)
            .where(TriggerLevel.tracking_run_id == run.id)
        )
        if levels and recorded == len(levels):
            run.status = "completed"

    def _lock(self, key: str) -> None:
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))

    def _run_rows(self, request: TrackingRunQuery | None = None, select_run_id: UUID | None = None) -> list[TrackingRunOutput]:
        levels = (
            select(
                TriggerLevel.tracking_run_id.label("tracking_run_id"),
                func.count(TriggerLevel.id).label("levels_total"),
                func.count(TriggerEvent.id).label("levels_hit"),
            ).outerjoin(TriggerEvent, TriggerEvent.trigger_level_id == TriggerLevel.id)
            .group_by(TriggerLevel.tracking_run_id).subquery()
        )
        statement = (
            select(TrackingRun, Instrument, func.coalesce(levels.c.levels_total, 0), func.coalesce(levels.c.levels_hit, 0))
            .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
            .join(Instrument, Instrument.id == SignalObservation.instrument_id)
            .outerjoin(levels, levels.c.tracking_run_id == TrackingRun.id)
            .order_by(TrackingRun.created_at.desc(), TrackingRun.id)
        )
        if select_run_id:
            statement = statement.where(TrackingRun.id == select_run_id)
        if request:
            if request.status:
                statement = statement.where(TrackingRun.status == request.status)
            if request.instrument_id:
                statement = statement.where(SignalObservation.instrument_id == request.instrument_id)
            statement = statement.limit(request.limit + 1).offset(request.offset)
        return [self._transform_output(run, instrument, total, hit) for run, instrument, total, hit in self.session.execute(statement).all()]

    @staticmethod
    def _transform_output(run: TrackingRun, instrument: Instrument, levels_total: int, levels_hit: int) -> TrackingRunOutput:
        return TrackingRunOutput(
            id=run.id, instrument_id=instrument.id, exchange=instrument.exchange, symbol=instrument.symbol,
            experiment_version_id=run.experiment_version_id, signal_observation_id=run.signal_observation_id,
            status=run.status, created_at=run.created_at, admitted_at=run.admitted_at,
            reference_price=run.reference_price, reference_at=run.reference_at, activated_at=run.activated_at,
            expires_at=run.expires_at, price_coverage=run.price_coverage, levels_total=levels_total, levels_hit=levels_hit,
        )
