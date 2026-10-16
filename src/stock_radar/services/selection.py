from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from stock_radar.brapi import SYMBOL_PATTERN
from stock_radar.db.models import CandidateDecision, CandidateSelection, CollectionRun, ExperimentVersion, Instrument, SignalObservation
from stock_radar.market_calendar import CalendarUnavailable, next_session_open, session_close
from stock_radar.services.errors import ServiceError
from stock_radar.services.policy import SELECTION_KEY, PolicyResolver, SelectionRules, selection_rules
from stock_radar.services.tracking import FUTURE_TOLERANCE, TrackingService
from stock_radar.viewmodels.selection import (
    CandidateOutput,
    CandidateQuery,
    CandidateSession,
    CollectionReference,
    DecisionInput,
    SelectedRun,
    SelectionInput,
    SelectionOutput,
)

CLAIMED_OUTCOMES = ("selected", "already_tracked")
READ_ISOLATION = "REPEATABLE READ"
WINDOW_LIMITATION = "Tracking window not known at decision time; assessed against the 20 sessions following the decision."
SERVICE_RATIONALE = {
    "already_tracked": "An open tracking run already exists for this instrument; no selection slot is used.",
    "not_monitorable": "The quote client rejects this ticker format, so the monitor could never quote it.",
    "daily_cap_reached": "All selection slots of this session were already used when this candidate was registered.",
}


@dataclass(frozen=True)
class RegisteredObservation:
    observation_id: UUID
    instrument_id: UUID
    symbol: str


@dataclass(frozen=True)
class CandidateRow:
    decision: CandidateDecision
    instrument: Instrument
    observation: SignalObservation
    collection: CollectionRun
    late: bool | None


def estimated_turnover(observation: SignalObservation) -> tuple[Decimal | None, str | None]:
    if observation.observed_price is not None and observation.volume is not None:
        return observation.observed_price * observation.volume, None
    if observation.observed_price is None and observation.volume is None:
        return None, "price_and_volume_missing"
    return None, "price_missing" if observation.observed_price is None else "volume_missing"


def tiebreak_key(market_session_date: date, symbol: str) -> str:
    return hashlib.sha256(f"{market_session_date.isoformat()}:{symbol}".encode()).hexdigest()


def baseline_order(market_session_date: date, rows: list[CandidateRow]) -> tuple[dict[UUID, int], bool]:
    pending = [row for row in rows if row.decision.outcome == "pending"]
    turnovers = {row.decision.id: estimated_turnover(row.observation)[0] for row in pending}
    comparable = bool(pending) and all(value is not None for value in turnovers.values()) and len({row.collection.id for row in pending}) == 1

    def key(row: CandidateRow) -> tuple:
        tiebreak = tiebreak_key(market_session_date, row.instrument.symbol)
        return (-turnovers[row.decision.id], tiebreak) if comparable else (tiebreak,)

    return {row.decision.id: index for index, row in enumerate(sorted(pending, key=key), start=1)}, comparable


class CandidateRegistry:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, version: ExperimentVersion, rules: SelectionRules, market_session_date: date, observations: list[RegisteredObservation]) -> None:
        tracking = TrackingService(self.session)
        selected = self.session.scalar(select(func.count(CandidateDecision.id)).where(
            CandidateDecision.experiment_version_id == version.id, CandidateDecision.market_session_date == market_session_date,
            CandidateDecision.outcome == "selected",
        ))
        for item in observations:
            existing = self.session.scalar(select(CandidateDecision.id).where(
                CandidateDecision.experiment_version_id == version.id, CandidateDecision.market_session_date == market_session_date,
                CandidateDecision.instrument_id == item.instrument_id,
            ))
            if existing is not None:
                continue
            outcome, reason, run_id = self._initial(tracking, version, item, selected >= rules.max_new_per_session)
            self.session.execute(insert(CandidateDecision).values(
                experiment_version_id=version.id, market_session_date=market_session_date, instrument_id=item.instrument_id,
                signal_observation_id=item.observation_id, outcome=outcome, reason_code=reason, tracking_run_id=run_id,
                rationale=SERVICE_RATIONALE.get(reason or outcome), details={"decided_by": "service"} if outcome != "pending" else {},
                decided_at=None if outcome == "pending" else func.now(),
            ))

    @staticmethod
    def _initial(tracking: TrackingService, version: ExperimentVersion, item: RegisteredObservation, full: bool) -> tuple[str, str | None, UUID | None]:
        open_run = tracking.open_run_id(item.instrument_id, version.experiment_id)
        if open_run is not None:
            return "already_tracked", None, open_run
        if not SYMBOL_PATTERN.fullmatch(item.symbol):
            return "not_selected", "not_monitorable", None
        if full:
            return "not_selected", "daily_cap_reached", None
        return "pending", None, None


class SelectionService:
    def __init__(self, session: Session, clock: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self.clock = clock or (lambda: self.session.scalar(select(func.clock_timestamp())))

    def candidates(self, query: CandidateQuery) -> CandidateSession:
        self.session.connection(execution_options={"isolation_level": READ_ISOLATION})
        day = query.market_session_date or self._latest_assisted_session()
        version, rules = self._assisted(day)
        rows = self._rows(version, day)
        baseline, comparable = baseline_order(day, rows)
        close = self._calendar(session_close, day)
        next_open = self._calendar(next_session_open, day)
        now = self.session.scalar(select(func.now()))
        tracking = TrackingService(self.session)
        items = [self._candidate(row, baseline, close, tracking, version) for row in rows]
        used = sum(1 for row in rows if row.decision.outcome == "selected")
        response = CandidateSession(
            market_session_date=day, experiment_version=version.version, criteria_version=rules.criteria_version,
            max_new_per_session=rules.max_new_per_session, slots_used=used, slots_remaining=max(rules.max_new_per_session - used, 0),
            next_session_opens_at=next_open, late_if_confirmed_now=now >= next_open, liquidity_comparable=comparable,
            baseline_rule="estimated_turnover_then_tiebreak" if comparable else "tiebreak_only",
            collections=self._collections(day), pending=sum(1 for row in rows if row.decision.outcome == "pending"), candidates=items,
        )
        self.session.rollback()
        return response

    def confirm(self, request: SelectionInput) -> SelectionOutput:
        digest = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        day = request.market_session_date
        with self.session.begin():
            PolicyResolver(self.session).lock_session(day)
            existing = self.session.scalar(select(CandidateSelection).where(CandidateSelection.client_selection_id == request.client_selection_id))
            if existing is not None:
                if existing.payload_hash != digest:
                    raise ServiceError("selection_identity_conflict", 409)
                return self._output(existing, duplicate=True)
            version, rules = self._assisted(day)
            if request.criteria_version != rules.criteria_version:
                raise ServiceError("criteria_version_mismatch", 409)
            rows = {row.decision.id: row for row in self._rows(version, day, lock=True)}
            pending = {decision_id: row for decision_id, row in rows.items() if row.decision.outcome == "pending"}
            self._check_pending_set(request, rows, pending)
            used = sum(1 for row in rows.values() if row.decision.outcome == "selected")
            self._check_capacity(request, rules.max_new_per_session - used)
            open_runs = self._claimed_runs(request, pending, version)
            decided_at = self.clock()
            self._check_evidence_times(request, decided_at)
            selection = CandidateSelection(
                client_selection_id=request.client_selection_id, payload_hash=digest, experiment_version_id=version.id,
                market_session_date=day, criteria_version=request.criteria_version, ranking_basis=request.ranking_basis,
                summary=request.summary, no_selection_reason=request.no_selection_reason, plugin_version=request.plugin_version,
                decided_at=decided_at, late=decided_at >= self._calendar(next_session_open, day),
            )
            self.session.add(selection)
            self.session.flush()
            self._apply(request, pending, selection, version, open_runs, used)
            return self._output(selection)

    def _check_pending_set(self, request: SelectionInput, rows: dict[UUID, CandidateRow], pending: dict[UUID, CandidateRow]) -> None:
        sent = {item.decision_id for item in request.decisions}
        if not pending:
            raise ServiceError("nothing_pending", 409)
        if sent - set(rows):
            raise ServiceError("decision_not_in_session", 422)
        if sent - set(pending):
            raise ServiceError("candidate_already_decided", 409)
        if set(pending) - sent:
            raise ServiceError("pending_set_changed", 409)

    @staticmethod
    def _check_capacity(request: SelectionInput, remaining: int) -> None:
        selected = sum(1 for item in request.decisions if item.outcome == "selected")
        if selected > remaining:
            raise ServiceError("selection_exceeds_slots", 409)
        if selected < remaining and any(item.reason_code == "outranked" for item in request.decisions):
            raise ServiceError("selection_underfilled", 409)

    def _claimed_runs(self, request: SelectionInput, pending: dict[UUID, CandidateRow], version: ExperimentVersion) -> dict[UUID, UUID | None]:
        tracking = TrackingService(self.session)
        claimed = sorted((item for item in request.decisions if item.outcome in CLAIMED_OUTCOMES), key=lambda item: str(pending[item.decision_id].instrument.id))
        open_runs = {}
        for item in claimed:
            instrument_id = pending[item.decision_id].instrument.id
            tracking.lock_instrument(version.experiment_id, instrument_id)
            open_runs[item.decision_id] = tracking.open_run_id(instrument_id, version.experiment_id)
        if any(open_runs[item.decision_id] is not None for item in claimed if item.outcome == "selected"):
            raise ServiceError("candidate_already_tracked", 409)
        if any(open_runs[item.decision_id] is None for item in claimed if item.outcome == "already_tracked"):
            raise ServiceError("already_tracked_not_confirmed", 409)
        return open_runs

    @staticmethod
    def _check_evidence_times(request: SelectionInput, decided_at: datetime) -> None:
        for item in request.decisions:
            if any(evidence.consulted_at > decided_at + FUTURE_TOLERANCE for evidence in item.evidence):
                raise ServiceError("evidence_after_decision", 422)

    def _apply(self, request: SelectionInput, pending: dict[UUID, CandidateRow], selection: CandidateSelection, version: ExperimentVersion, open_runs: dict[UUID, UUID | None], used: int) -> None:
        tracking = TrackingService(self.session)
        baseline, _ = baseline_order(selection.market_session_date, list(pending.values()))
        slot = used
        for item in sorted(request.decisions, key=lambda decision: (decision.outcome != "selected", decision.rank or 0)):
            decision = pending[item.decision_id].decision
            run_id = open_runs.get(item.decision_id)
            if item.outcome == "selected":
                run_id = tracking.start_selected(decision.signal_observation_id, version, selection.decided_at)
                slot += 1
            decision.slot = slot if item.outcome == "selected" else None
            decision.tracking_run_id = run_id if item.outcome in CLAIMED_OUTCOMES else None
            decision.outcome, decision.reason_code, decision.rank = item.outcome, item.reason_code, item.rank
            decision.baseline_rank, decision.rationale, decision.details = baseline.get(item.decision_id), item.rationale, self._details(item, request)
            decision.candidate_selection_id, decision.decided_at = selection.id, selection.decided_at
        self.session.flush()

    @staticmethod
    def _details(item: DecisionInput, request: SelectionInput) -> dict:
        details = {
            "evidence": [evidence.model_dump(mode="json") for evidence in item.evidence],
            "unavailable": list(item.unavailable), "risks": [risk.model_dump(mode="json") for risk in item.risks],
            "ranking_basis": request.ranking_basis,
        }
        if item.event_date is not None:
            details["event_date"] = item.event_date.isoformat()
            details["window_limitation"] = WINDOW_LIMITATION
        return details

    def _output(self, selection: CandidateSelection, duplicate: bool = False) -> SelectionOutput:
        version = self.session.get(ExperimentVersion, selection.experiment_version_id)
        rules = selection_rules(version.rules)
        rows = self.session.execute(
            select(CandidateDecision, Instrument.symbol).join(Instrument, Instrument.id == CandidateDecision.instrument_id)
            .where(CandidateDecision.candidate_selection_id == selection.id).order_by(CandidateDecision.slot, Instrument.symbol)
        ).all()
        outcomes = [decision.outcome for decision, _ in rows]
        used = self.session.scalar(select(func.count(CandidateDecision.id)).where(
            CandidateDecision.experiment_version_id == version.id, CandidateDecision.market_session_date == selection.market_session_date,
            CandidateDecision.outcome == "selected",
        ))
        return SelectionOutput(
            id=selection.id, client_selection_id=selection.client_selection_id, market_session_date=selection.market_session_date,
            experiment_version=version.version, criteria_version=selection.criteria_version, decided_at=selection.decided_at, late=selection.late,
            selected=[SelectedRun(decision_id=decision.id, symbol=symbol, slot=decision.slot, tracking_run_id=decision.tracking_run_id) for decision, symbol in rows if decision.outcome == "selected"],
            not_selected=outcomes.count("not_selected"), not_assessable=outcomes.count("not_assessable"), already_tracked=outcomes.count("already_tracked"),
            slots_remaining=max(rules.max_new_per_session - used, 0), duplicate=duplicate,
        )

    def _latest_assisted_session(self) -> date:
        day = self.session.scalar(
            select(func.max(CollectionRun.market_session_date))
            .join(ExperimentVersion, ExperimentVersion.id == CollectionRun.experiment_version_id)
            .where(ExperimentVersion.rules.has_key(SELECTION_KEY))
        )
        if day is None:
            raise ServiceError("selection_session_not_found", 404)
        return day

    def _assisted(self, day: date) -> tuple[ExperimentVersion, SelectionRules]:
        if self.session.scalar(select(func.count(CollectionRun.id)).where(CollectionRun.market_session_date == day)) == 0:
            raise ServiceError("selection_session_not_found", 404)
        version = PolicyResolver(self.session).for_session(day)
        rules = selection_rules(version.rules) if version is not None else None
        if rules is None:
            raise ServiceError("session_not_assisted", 409)
        return version, rules

    def _rows(self, version: ExperimentVersion, day: date, lock: bool = False) -> list[CandidateRow]:
        statement = (
            select(CandidateDecision, Instrument, SignalObservation, CollectionRun, CandidateSelection.late)
            .join(Instrument, Instrument.id == CandidateDecision.instrument_id)
            .join(SignalObservation, SignalObservation.id == CandidateDecision.signal_observation_id)
            .join(CollectionRun, CollectionRun.id == SignalObservation.collection_run_id)
            .outerjoin(CandidateSelection, CandidateSelection.id == CandidateDecision.candidate_selection_id)
            .where(CandidateDecision.experiment_version_id == version.id, CandidateDecision.market_session_date == day)
            .order_by(Instrument.symbol, CandidateDecision.id)
        )
        if lock:
            statement = statement.with_for_update(of=CandidateDecision)
        return [CandidateRow(*row) for row in self.session.execute(statement).all()]

    def _collections(self, day: date) -> list[CollectionReference]:
        rows = self.session.execute(
            select(CollectionRun, func.count(SignalObservation.id))
            .outerjoin(SignalObservation, SignalObservation.collection_run_id == CollectionRun.id)
            .where(CollectionRun.market_session_date == day).group_by(CollectionRun.id)
            .order_by(CollectionRun.received_at, CollectionRun.id)
        ).all()
        return [CollectionReference(id=item.id, status=item.status, observed_at=item.observed_at, received_at=item.received_at, observation_count=count) for item, count in rows]

    def _calendar(self, function, day: date):
        try:
            return function(self.session, day)
        except CalendarUnavailable:
            raise ServiceError("market_calendar_unavailable", 422) from None

    @staticmethod
    def _candidate(row: CandidateRow, baseline: dict[UUID, int], close: datetime | None, tracking: TrackingService, version: ExperimentVersion) -> CandidateOutput:
        decision, observation = row.decision, row.observation
        turnover, unavailable = estimated_turnover(observation)
        partial = None if turnover is None or close is None else row.collection.observed_at < close
        open_run = tracking.open_run_id(row.instrument.id, version.experiment_id) if decision.outcome == "pending" else None
        return CandidateOutput(
            decision_id=decision.id, instrument_id=row.instrument.id, exchange=row.instrument.exchange, symbol=row.instrument.symbol,
            signal_observation_id=observation.id, collection_id=row.collection.id, observed_at=observation.observed_at,
            observed_price=observation.observed_price, daily_change_percent=observation.daily_change_percent,
            original_rating=observation.original_rating, volume=observation.volume, sector=observation.sector,
            estimated_turnover_at_observed_price=turnover, turnover_partial_session=partial, turnover_unavailable_reason=unavailable,
            open_tracking_run_id=open_run, baseline_rank=baseline.get(decision.id), outcome=decision.outcome,
            reason_code=decision.reason_code, rank=decision.rank, slot=decision.slot, tracking_run_id=decision.tracking_run_id,
            rationale=decision.rationale, details=decision.details, decided_at=decision.decided_at, selection_late=row.late,
        )
