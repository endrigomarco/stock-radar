from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_radar.db.models import (
    CandidateDecision,
    CandidateSelection,
    CollectionRun,
    Experiment,
    ExperimentVersion,
    Instrument,
    PriceQuote,
    SignalObservation,
    TrackingRun,
    TriggerEvent,
    TriggerLevel,
)
from stock_radar.market_calendar import TradingCalendar, load_calendar, market_date
from stock_radar.services.composition import Candidate, compose
from stock_radar.services.policy import EXPERIMENT_CODE
from stock_radar.services.portfolio_output import PortfolioInput, Position, Seed, build_output
from stock_radar.services.simulation import Observation, Reading, TradingSession
from stock_radar.services.tracking import MAX_QUOTE_AGE
from stock_radar.viewmodels.portfolio import PortfolioOutput

ONE_DAY = timedelta(days=1)
RECORDED_RISKS = {"corporate_event", "ex_dividend"}
Decisions = list[tuple[CandidateDecision, CandidateSelection | None]]


@dataclass
class RunData:
    run: TrackingRun
    instrument: Instrument
    reference_received_at: datetime | None = None
    levels: dict[UUID, tuple[Decimal, Decimal]] = field(default_factory=dict)
    quote_events: dict[UUID, Reading] = field(default_factory=dict)
    webhook_events: bool = False
    next_reference_at: datetime | None = None
    quotes: list[Reading] = field(default_factory=list)


class PortfolioService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build_many(self, entries: dict[date, Decisions | None], cut: datetime) -> dict[date, PortfolioOutput]:
        seeds = self._seeds(entries, cut)
        runs = self._runs({seed.run_id for items in seeds.values() for seed in items}, cut)
        calendar = self._calendar(runs, cut)
        return {day: self._portfolio(seeds[day], runs, calendar, cut) for day in entries}

    def _seeds(self, entries: dict[date, Decisions | None], cut: datetime) -> dict[date, list[Seed]]:
        seeds: dict[date, list[Seed]] = {day: [] for day in entries}
        for day, decisions in entries.items():
            if decisions is None:
                continue
            seeds[day] = [
                Seed(decision.tracking_run_id, decision.decided_at, selection.late if selection is not None else None, _risks(decision))
                for decision, selection in decisions
                if decision.outcome == "selected" and decision.tracking_run_id is not None and decision.decided_at is not None and decision.decided_at <= cut
            ]
        automatic = [day for day, decisions in entries.items() if decisions is None]
        if automatic:
            rows = self.session.execute(
                select(TrackingRun.id, TrackingRun.created_at, CollectionRun.market_session_date)
                .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
                .join(CollectionRun, CollectionRun.id == SignalObservation.collection_run_id)
                .join(ExperimentVersion, ExperimentVersion.id == TrackingRun.experiment_version_id)
                .join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
                .where(Experiment.code == EXPERIMENT_CODE, CollectionRun.market_session_date.in_(automatic), TrackingRun.created_at <= cut)
            ).all()
            for run_id, created_at, day in rows:
                seeds[day].append(Seed(run_id, created_at, None, ()))
        return seeds

    def _runs(self, run_ids: set[UUID], cut: datetime) -> dict[UUID, RunData]:
        if not run_ids:
            return {}
        rows = self.session.execute(
            select(TrackingRun, Instrument)
            .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
            .join(Instrument, Instrument.id == SignalObservation.instrument_id)
            .where(TrackingRun.id.in_(run_ids))
        ).all()
        runs = {run.id: RunData(run, instrument) for run, instrument in rows}
        self._load_receipts(runs)
        self._load_levels(runs)
        self._load_next_references(runs)
        self._load_quotes(runs, cut)
        return runs

    def _load_receipts(self, runs: dict[UUID, RunData]) -> None:
        referenced = [item for item in runs.values() if item.run.reference_at is not None]
        if not referenced:
            return
        quotes = self.session.execute(
            select(PriceQuote.id, PriceQuote.instrument_id, PriceQuote.source_id, PriceQuote.quoted_at, PriceQuote.received_at)
            .where(PriceQuote.instrument_id.in_({item.instrument.id for item in referenced}), PriceQuote.quoted_at.in_({item.run.reference_at for item in referenced}))
        ).all()
        by_id = {row.id: row for row in quotes}
        by_key = {(row.instrument_id, row.source_id, row.quoted_at): row for row in quotes}
        for item in referenced:
            key = (item.instrument.id, item.run.reference_source_id, item.run.reference_at)
            match = by_id.get(_quote_id(item.run.reference_evidence))
            if match is None or (match.instrument_id, match.source_id, match.quoted_at) != key:
                match = by_key.get(key)
            item.reference_received_at = match.received_at if match is not None else None

    def _load_levels(self, runs: dict[UUID, RunData]) -> None:
        rows = self.session.execute(
            select(TriggerLevel.id, TriggerLevel.tracking_run_id, TriggerLevel.signed_percent, TriggerLevel.mathematical_price,
                   TriggerEvent.id.label("event_id"), PriceQuote.price, PriceQuote.quoted_at, PriceQuote.received_at)
            .outerjoin(TriggerEvent, TriggerEvent.trigger_level_id == TriggerLevel.id)
            .outerjoin(PriceQuote, PriceQuote.id == TriggerEvent.price_quote_id)
            .where(TriggerLevel.tracking_run_id.in_(runs))
        ).all()
        for row in rows:
            item = runs[row.tracking_run_id]
            item.levels[row.id] = (row.signed_percent, row.mathematical_price)
            if row.event_id is None:
                continue
            if row.quoted_at is None:
                item.webhook_events = True
            else:
                item.quote_events[row.id] = Reading(row.price, row.quoted_at, row.received_at)

    def _load_next_references(self, runs: dict[UUID, RunData]) -> None:
        rows = self.session.execute(
            select(SignalObservation.instrument_id, TrackingRun.reference_at)
            .join(TrackingRun, TrackingRun.signal_observation_id == SignalObservation.id)
            .where(SignalObservation.instrument_id.in_({item.instrument.id for item in runs.values()}), TrackingRun.reference_at.is_not(None))
        ).all()
        for item in runs.values():
            if item.run.reference_at is None:
                continue
            later = [reference_at for instrument_id, reference_at in rows if instrument_id == item.instrument.id and reference_at > item.run.reference_at]
            item.next_reference_at = min(later) if later else None

    def _load_quotes(self, runs: dict[UUID, RunData], cut: datetime) -> None:
        referenced = [item for item in runs.values() if item.run.reference_at is not None]
        if not referenced:
            return
        quotes = self.session.scalars(
            select(PriceQuote).where(
                PriceQuote.instrument_id.in_({item.instrument.id for item in referenced}),
                PriceQuote.quoted_at > min(item.run.reference_at for item in referenced),
                PriceQuote.quoted_at <= cut, PriceQuote.received_at <= cut,
            ).order_by(PriceQuote.quoted_at, PriceQuote.id)
        ).all()
        for item in referenced:
            run = item.run
            item.quotes = [
                Reading(quote.price, quote.quoted_at, quote.received_at) for quote in quotes
                if quote.instrument_id == item.instrument.id and quote.source_id == run.reference_source_id
                and run.reference_at < quote.quoted_at <= run.expires_at
                and (item.next_reference_at is None or quote.quoted_at < item.next_reference_at)
            ]

    def _calendar(self, runs: dict[UUID, RunData], cut: datetime) -> TradingCalendar:
        references = [item.run.reference_at for item in runs.values() if item.run.reference_at is not None and item.run.reference_at <= cut]
        if not references:
            return TradingCalendar({})
        return load_calendar(self.session, market_date(min(references)), market_date(cut))

    def _portfolio(self, seeds: list[Seed], runs: dict[UUID, RunData], calendar: TradingCalendar, cut: datetime) -> PortfolioOutput:
        known = [seed for seed in seeds if seed.run_id in runs]
        observations = {seed.run_id: observe(runs[seed.run_id], calendar, cut) for seed in known}
        composition = compose(
            [_candidate(seed, observations[seed.run_id]) for seed in known], cut, MAX_QUOTE_AGE,
        )
        positions = [
            Position(seed=seed, run=runs[seed.run_id].run, instrument=runs[seed.run_id].instrument,
                     observation=observations[seed.run_id], pending_reason=_pending_reason(runs[seed.run_id].run, observations[seed.run_id], cut))
            for seed in known
        ]
        return build_output(PortfolioInput(cut=cut, composition=composition, positions=positions, calendar=calendar))


def observe(item: RunData, calendar: TradingCalendar, cut: datetime) -> Observation:
    run = item.run
    reference = _known_reference(item, cut)
    if reference is None:
        return Observation(None, (), "pending", None, None, (), True)
    readings = tuple(item.quotes)
    if run.status == "cancelled":
        return _evidenced(item, reference, readings, "cancelled", calendar, cut)
    if run.status == "completed" and item.webhook_events:
        return _evidenced(item, reference, readings, "completion_unknown", calendar, cut)
    if run.status == "completed":
        completion = _completion(item, readings, cut)
        if completion is not None:
            return _bounded(reference, readings, "completed", completion, run.expires_at, calendar)
    if item.next_reference_at is not None and item.next_reference_at <= min(cut, run.expires_at):
        return _evidenced(item, reference, readings, "overlapping_run", calendar, cut)
    if run.expires_at <= cut:
        return _bounded(reference, readings, "window_closed", run.expires_at, run.expires_at, calendar)
    return _bounded(reference, readings, "open", cut, run.expires_at, calendar)


def _known_reference(item: RunData, cut: datetime) -> Reading | None:
    run = item.run
    if run.reference_at is None or run.reference_at > cut:
        return None
    if item.reference_received_at is not None and item.reference_received_at > cut:
        return None
    return Reading(run.reference_price, run.reference_at, item.reference_received_at)


def _evidenced(item: RunData, reference: Reading, readings: tuple[Reading, ...], end: str, calendar: TradingCalendar, cut: datetime) -> Observation:
    proven = [event.quoted_at for event in item.quote_events.values() if event.received_at <= cut and event.quoted_at <= cut]
    until = max([reference.quoted_at, *proven])
    return _bounded(reference, readings, end, until, item.run.expires_at, calendar)


def _bounded(reference: Reading, readings: tuple[Reading, ...], end: str, until: datetime, expires_at: datetime, calendar: TradingCalendar) -> Observation:
    sessions, complete = _sessions(calendar, market_date(reference.quoted_at), market_date(until))
    kept = tuple(reading for reading in readings if reading.quoted_at <= until)
    return Observation(reference, kept, end, until, expires_at, sessions, complete)


def _completion(item: RunData, readings: tuple[Reading, ...], cut: datetime) -> datetime | None:
    if not item.levels:
        return None
    candidates = []
    pending = list(item.levels.values())
    for reading in readings:
        pending = [(percent, price) for percent, price in pending if not _reaches(percent, price, reading.price)]
        if not pending:
            candidates.append(reading.quoted_at)
            break
    events = [event for event in item.quote_events.values() if event.received_at <= cut and event.quoted_at <= cut]
    if len(events) == len(item.levels):
        candidates.append(max(event.quoted_at for event in events))
    return min(candidates) if candidates else None


def _reaches(percent: Decimal, level: Decimal, price: Decimal) -> bool:
    return price >= level if percent > 0 else price <= level


def _sessions(calendar: TradingCalendar, first: date, last: date) -> tuple[tuple[TradingSession, ...], bool]:
    sessions = []
    complete = True
    day = first
    while day <= last:
        if day not in calendar.days:
            complete = False
        elif calendar.days[day] is not None:
            opens, closes = calendar.days[day]
            sessions.append(TradingSession(day, opens, closes))
        day += ONE_DAY
    return tuple(sessions), complete


def _candidate(seed: Seed, observation: Observation) -> Candidate:
    reference = observation.reference
    if reference is None:
        return Candidate(seed.run_id, seed.decided_at, None)
    return Candidate(seed.run_id, seed.decided_at, reference.quoted_at, reference.received_at is not None)


def _pending_reason(run: TrackingRun, observation: Observation, cut: datetime) -> str | None:
    if observation.reference is not None:
        return None
    if run.status == "cancelled" and run.reference_at is None:
        return "cancelled_without_entry"
    if run.admitted_at is not None and run.admitted_at <= cut:
        return "waiting_quote"
    return "waiting_slot"


def _quote_id(evidence: dict | None) -> UUID | None:
    try:
        return UUID(str((evidence or {})["price_quote_id"]))
    except (KeyError, ValueError):
        return None


def _risks(decision: CandidateDecision) -> tuple[str, ...]:
    risks = (decision.details or {}).get("risks", [])
    return tuple(sorted({risk.get("code") for risk in risks if isinstance(risk, dict) and risk.get("code") in RECORDED_RISKS}))
