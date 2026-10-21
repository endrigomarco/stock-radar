from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
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
from stock_radar.market_calendar import SessionBounds, TradingCalendar, load_calendar, market_date
from stock_radar.services.collections import eligible_expression
from stock_radar.services.policy import PolicyResolver, SelectionRules, selection_rules
from stock_radar.services.portfolio import PortfolioService
from stock_radar.services.tracking import EXPERIMENT_CODE, OPEN_STATUSES, TrackingService
from stock_radar.viewmodels.reports import (
    CollectionGroup,
    DailyReport,
    DailyReportQuery,
    HorizonOutput,
    MilestoneOutput,
    QuoteReading,
    RateBlock,
    SelectionRecord,
    SelectionSummary,
    SignalProgress,
    TargetRate,
)

MILESTONE_SESSIONS = (1, 2, 5, 10, 19, 20)
TARGET_PERCENTS = tuple(Decimal(value) for value in ("1", "2", "3", "-1", "-2", "-3"))
ORDER_UP = Decimal("2")
ORDER_DOWN = Decimal("-2")
ORDER_OUTCOMES = ("up_first", "down_first", "only_up", "only_down", "neither", "indeterminate", "not_assessed")
PERCENT_BASE = Decimal(100)
RETURN_STEP = Decimal("0.01")
RATE_STEP = Decimal("0.1")
ONE_DAY = timedelta(days=1)
REPORT_ISOLATION = "REPEATABLE READ"
DECISION_LINKS = {"pending": "selection_pending", "not_selected": "not_selected", "not_assessable": "not_assessable", "already_tracked": "already_tracked"}
EMPTY_PROGRESS = {
    "status": None, "pending_reason": None, "reference_price": None, "reference_at": None, "reference_session_date": None,
    "expires_at": None, "latest_quote": None, "milestones": [], "target_order": None,
}


@dataclass
class RunFacts:
    run: TrackingRun
    instrument_id: UUID
    origin_date: date
    window_last: int
    events: dict[Decimal, TriggerEvent] = field(default_factory=dict)
    levels_total: int = 0
    sessions: list[tuple[date, SessionBounds]] = field(default_factory=list)
    quotes: list[PriceQuote] = field(default_factory=list)
    completion_at: datetime | None = None

    @property
    def cancelled(self) -> bool:
        return self.run.status == "cancelled"

    @property
    def completed(self) -> bool:
        return self.run.status == "completed"


@dataclass
class BlockTally:
    runs: int = 0
    eligible: int = 0
    completed_early: int = 0
    cancelled: int = 0
    insufficient: int = 0
    calendar: int = 0
    hits: dict[Decimal, int] = field(default_factory=lambda: dict.fromkeys(TARGET_PERCENTS, 0))
    denominators: dict[Decimal, int] = field(default_factory=lambda: dict.fromkeys(TARGET_PERCENTS, 0))
    indeterminate: dict[Decimal, int] = field(default_factory=lambda: dict.fromkeys(TARGET_PERCENTS, 0))
    outside: dict[Decimal, int] = field(default_factory=lambda: dict.fromkeys(TARGET_PERCENTS, 0))

    def output(self) -> RateBlock:
        return RateBlock(
            runs=self.runs, eligible=self.eligible, completed_early=self.completed_early,
            excluded_cancelled=self.cancelled, excluded_insufficient_coverage=self.insufficient,
            excluded_calendar_unavailable=self.calendar,
            targets=[TargetRate(
                signed_percent=percent, hits=self.hits[percent], denominator=self.denominators[percent],
                rate_percent=_rate(self.hits[percent], self.denominators[percent]),
                indeterminate=self.indeterminate[percent], proven_hits_outside_sample=self.outside[percent],
            ) for percent in TARGET_PERCENTS],
        )


def _rate(hits: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(hits) * PERCENT_BASE / Decimal(denominator)).quantize(RATE_STEP, rounding=ROUND_HALF_UP)


def _return_percent(price: Decimal, reference: Decimal) -> Decimal:
    return ((price / reference - 1) * PERCENT_BASE).quantize(RETURN_STEP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SessionPolicy:
    version: ExperimentVersion | None
    rules: SelectionRules | None


@dataclass(frozen=True)
class DayInput:
    day: date
    policy: SessionPolicy
    collection_ids: list[UUID]
    observations: list
    decisions: list[tuple[CandidateDecision, CandidateSelection | None]]


class ReportService:
    def __init__(self, session: Session, now: datetime | None = None) -> None:
        self.session = session
        self.now = now

    def daily(self, request: DailyReportQuery) -> DailyReport:
        self.session.connection(execution_options={"isolation_level": REPORT_ISOLATION})
        generated_at = self.now or self.session.scalar(select(func.now()))
        dates = self._dates(request)
        page = dates[:request.limit]
        collections = self._collections(page)
        observations = self._observations(page)
        facts = self._facts({row.instrument_id for row, _, _ in observations}, generated_at)
        version = TrackingService(self.session).current_version()
        window_last = int(version.rules["window_sessions"]) - 1 if version is not None else None
        policies = {day: self._policy(day) for day in page}
        decisions = self._decisions({day: policy for day, policy in policies.items() if policy.rules is not None})
        groups = [
            self._group(DayInput(day, policies[day], collections[day], [item for item in observations if item[1].market_session_date == day], decisions.get(day, [])), facts, generated_at, request, window_last)
            for day in page
        ]
        if request.signal_offset == 0:
            portfolios = PortfolioService(self.session).build_many(
                {day: decisions.get(day, []) if policies[day].rules is not None else None for day in page}, generated_at,
            )
            groups = [group.model_copy(update={"portfolio": portfolios[group.market_session_date]}) for group in groups]
        self.session.rollback()
        return DailyReport(generated_at=generated_at, items=groups, limit=request.limit, offset=request.offset, has_more=len(dates) > request.limit)

    def _dates(self, request: DailyReportQuery) -> list[date]:
        statement = select(CollectionRun.market_session_date).distinct().order_by(CollectionRun.market_session_date.desc())
        if request.market_session_date:
            statement = statement.where(CollectionRun.market_session_date == request.market_session_date)
        return list(self.session.scalars(statement.limit(request.limit + 1).offset(request.offset)).all())

    def _collections(self, days: list[date]) -> dict[date, list[UUID]]:
        grouped: dict[date, list[UUID]] = {day: [] for day in days}
        if not days:
            return grouped
        rows = self.session.execute(
            select(CollectionRun.market_session_date, CollectionRun.id).where(CollectionRun.market_session_date.in_(days))
            .order_by(CollectionRun.received_at, CollectionRun.id)
        ).all()
        for day, collection_id in rows:
            grouped[day].append(collection_id)
        return grouped

    def _observations(self, days: list[date]) -> list[tuple[SignalObservation, CollectionRun, Instrument]]:
        if not days:
            return []
        return list(self.session.execute(
            select(SignalObservation, CollectionRun, Instrument)
            .join(CollectionRun, CollectionRun.id == SignalObservation.collection_run_id)
            .join(Instrument, Instrument.id == SignalObservation.instrument_id)
            .where(CollectionRun.market_session_date.in_(days), eligible_expression())
            .order_by(Instrument.symbol, SignalObservation.id)
        ).all())

    def _facts(self, instrument_ids: set[UUID], generated_at: datetime) -> dict[UUID, RunFacts]:
        if not instrument_ids:
            return {}
        rows = self.session.execute(
            select(TrackingRun, SignalObservation.instrument_id, CollectionRun.market_session_date, ExperimentVersion.rules)
            .join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
            .join(CollectionRun, CollectionRun.id == SignalObservation.collection_run_id)
            .join(ExperimentVersion, ExperimentVersion.id == TrackingRun.experiment_version_id)
            .join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
            .where(Experiment.code == EXPERIMENT_CODE, SignalObservation.instrument_id.in_(instrument_ids))
        ).all()
        facts = {run.id: RunFacts(run, instrument_id, origin_date, int(rules["window_sessions"]) - 1) for run, instrument_id, origin_date, rules in rows}
        self._load_events(facts, generated_at)
        self._load_sessions(facts)
        self._load_quotes(facts, generated_at)
        return facts

    def _load_events(self, facts: dict[UUID, RunFacts], generated_at: datetime) -> None:
        if not facts:
            return
        rows = self.session.execute(
            select(TriggerLevel.tracking_run_id, TriggerLevel.signed_percent, TriggerEvent)
            .outerjoin(TriggerEvent, TriggerEvent.trigger_level_id == TriggerLevel.id)
            .where(TriggerLevel.tracking_run_id.in_(facts))
        ).all()
        for run_id, percent, event in rows:
            item = facts[run_id]
            item.levels_total += 1
            if event is not None and event.created_at <= generated_at:
                item.events[percent] = event
        for item in facts.values():
            item.completion_at = _completion_time(item)

    def _load_sessions(self, facts: dict[UUID, RunFacts]) -> None:
        referenced = [item for item in facts.values() if item.run.reference_at is not None]
        if not referenced:
            return
        calendar = load_calendar(self.session, min(market_date(item.run.reference_at) for item in referenced))
        for item in referenced:
            item.sessions = _sessions(calendar, market_date(item.run.reference_at), max(MILESTONE_SESSIONS))

    def _load_quotes(self, facts: dict[UUID, RunFacts], generated_at: datetime) -> None:
        bounded = {item.run.id: _upper_bound(item, generated_at) for item in facts.values() if item.run.reference_at is not None}
        usable = [facts[run_id] for run_id, bound in bounded.items() if bound is not None]
        if not usable:
            return
        quotes = self.session.scalars(
            select(PriceQuote).where(
                PriceQuote.instrument_id.in_({item.instrument_id for item in usable}),
                PriceQuote.quoted_at >= min(item.run.reference_at for item in usable),
                PriceQuote.quoted_at <= generated_at, PriceQuote.received_at <= generated_at,
            ).order_by(PriceQuote.quoted_at)
        ).all()
        for item in usable:
            item.quotes = [
                quote for quote in quotes
                if quote.instrument_id == item.instrument_id and quote.source_id == item.run.reference_source_id
                and item.run.reference_at <= quote.quoted_at <= bounded[item.run.id]
            ]

    def _policy(self, day: date) -> SessionPolicy:
        version = PolicyResolver(self.session).for_session(day)
        return SessionPolicy(version, selection_rules(version.rules) if version is not None else None)

    def _decisions(self, policies: dict[date, SessionPolicy]) -> dict[date, list[tuple[CandidateDecision, CandidateSelection | None]]]:
        grouped: dict[date, list] = {day: [] for day in policies}
        if not policies:
            return grouped
        conditions = [(CandidateDecision.experiment_version_id == policy.version.id) & (CandidateDecision.market_session_date == day) for day, policy in policies.items()]
        rows = self.session.execute(
            select(CandidateDecision, CandidateSelection)
            .outerjoin(CandidateSelection, CandidateSelection.id == CandidateDecision.candidate_selection_id)
            .where(or_(*conditions)).order_by(CandidateDecision.id)
        ).all()
        for decision, selection in rows:
            grouped[decision.market_session_date].append((decision, selection))
        return grouped

    def _group(self, entry: DayInput, facts: dict[UUID, RunFacts], generated_at: datetime, request: DailyReportQuery, window_last: int | None) -> CollectionGroup:
        if entry.policy.rules is None:
            rows, own, late = _automatic_rows(entry.observations, facts, generated_at)
        else:
            rows, own, late = _assisted_rows(entry, facts, generated_at)
        tracked = own + late
        links = [row.tracking_link for row in rows]
        statuses = [item.run.status for item in tracked]
        prepared = [item for item in tracked if item.run.status == "prepared"]
        start = request.signal_offset
        return CollectionGroup(
            market_session_date=entry.day, selection_policy="automatic" if entry.policy.rules is None else "assisted",
            experiment_version=entry.policy.version.version if entry.policy.version is not None else None,
            collection_ids=entry.collection_ids, signals=len(rows),
            own_runs=len(tracked), reused_confirmed=links.count("reused_confirmed") + links.count("already_tracked"), unconfirmed_links=links.count("unconfirmed"),
            with_reference=sum(1 for item in tracked if item.run.reference_at is not None),
            waiting_slot=sum(1 for item in prepared if item.run.admitted_at is None),
            waiting_quote=sum(1 for item in prepared if item.run.admitted_at is not None),
            active=statuses.count("active"), completed=statuses.count("completed"),
            expired=statuses.count("expired"), cancelled=statuses.count("cancelled"),
            horizons=[_horizon(sessions, own, generated_at, window_last) for sessions in MILESTONE_SESSIONS],
            target_order=_order_counts(own, generated_at),
            late_horizons=[_horizon(sessions, late, generated_at, window_last) for sessions in MILESTONE_SESSIONS] if late else [],
            late_target_order=_order_counts(late, generated_at) if late else {},
            selection=self._summary(entry, len(late)) if entry.policy.rules is not None else None,
            items=rows[start:start + request.signal_limit], signal_limit=request.signal_limit,
            signal_offset=start, signals_has_more=len(rows) > start + request.signal_limit,
        )

    def _summary(self, entry: DayInput, selected_late: int) -> SelectionSummary:
        decisions = [decision for decision, _ in entry.decisions]
        outcomes = [decision.outcome for decision in decisions]
        statuses = self.session.execute(
            select(CollectionRun.status, func.count(CollectionRun.id)).where(CollectionRun.market_session_date == entry.day).group_by(CollectionRun.status)
        ).all()
        selections = {selection.id: selection for _, selection in entry.decisions if selection is not None}
        return SelectionSummary(
            experiment_version=entry.policy.version.version, criteria_version=entry.policy.rules.criteria_version,
            max_new_per_session=entry.policy.rules.max_new_per_session, collection_statuses={status: count for status, count in statuses},
            eligible_observations=len(entry.observations), candidates=len(decisions), new_candidates=len(decisions) - outcomes.count("already_tracked"),
            already_tracked=outcomes.count("already_tracked"), selected=outcomes.count("selected"),
            selected_on_time=outcomes.count("selected") - selected_late, selected_late=selected_late,
            not_selected=dict(Counter(decision.reason_code for decision in decisions if decision.outcome == "not_selected")),
            not_assessable=outcomes.count("not_assessable"), pending=outcomes.count("pending"),
            selections=[
                SelectionRecord(id=item.id, decided_at=item.decided_at, late=item.late, ranking_basis=item.ranking_basis, no_selection_reason=item.no_selection_reason)
                for item in sorted(selections.values(), key=lambda selection: (selection.decided_at, selection.id))
            ],
        )


def _automatic_rows(observations: list, facts: dict[UUID, RunFacts], generated_at: datetime) -> tuple[list[SignalProgress], list[RunFacts], list[RunFacts]]:
    own_by_observation = {item.run.signal_observation_id: item for item in facts.values()}
    rows, own = [], []
    for observation, collection, instrument in observations:
        item = own_by_observation.get(observation.id)
        if item is not None:
            own.append(item)
        rows.append(_signal_row(observation, collection, instrument, item, facts, generated_at))
    return rows, own, []


def _assisted_rows(entry: DayInput, facts: dict[UUID, RunFacts], generated_at: datetime) -> tuple[list[SignalProgress], list[RunFacts], list[RunFacts]]:
    by_observation = {observation.id: (observation, collection, instrument) for observation, collection, instrument in entry.observations}
    rows, on_time, late = [], [], []
    for decision, selection in entry.decisions:
        observation, collection, instrument = by_observation[decision.signal_observation_id]
        item = facts.get(decision.tracking_run_id) if decision.outcome == "selected" else None
        if item is not None:
            (late if selection.late else on_time).append(item)
            row = _signal_row(observation, collection, instrument, item, facts, generated_at)
        else:
            origin = facts.get(decision.tracking_run_id)
            row = SignalProgress(
                **_base(observation, collection, instrument), **EMPTY_PROGRESS, tracking_link=DECISION_LINKS[decision.outcome],
                tracking_run_id=decision.tracking_run_id, origin_market_session_date=origin.origin_date if origin is not None else None,
            )
        rows.append(row.model_copy(update={
            "selection_outcome": decision.outcome, "selection_reason": decision.reason_code, "selection_rank": decision.rank,
            "selected_at": selection.decided_at if selection is not None else None, "selection_late": selection.late if selection is not None else None,
        }))
    rows.sort(key=lambda row: (row.symbol, row.observation_id))
    return rows, on_time, late


def _completion_time(item: RunFacts) -> datetime | None:
    if not item.completed or item.levels_total == 0 or len(item.events) != item.levels_total:
        return None
    if any(event.price_quote_id is None or event.occurred_at is None for event in item.events.values()):
        return None
    return max(event.occurred_at for event in item.events.values())


def _upper_bound(item: RunFacts, generated_at: datetime) -> datetime | None:
    if item.cancelled:
        return None
    limits = [generated_at]
    if item.run.expires_at is not None:
        limits.append(item.run.expires_at)
    if item.completed:
        if item.completion_at is None:
            return None
        limits.append(item.completion_at)
    return min(limits)


def _sessions(calendar: TradingCalendar, first: date, last_index: int) -> list[tuple[date, SessionBounds]]:
    sessions: list[tuple[date, SessionBounds]] = []
    day = first
    while day in calendar.days and len(sessions) <= last_index:
        bounds = calendar.days[day]
        if bounds is not None:
            sessions.append((day, bounds))
        day += ONE_DAY
    return sessions


def _last_quote(item: RunFacts, start: datetime, end: datetime) -> PriceQuote | None:
    inside = [quote for quote in item.quotes if start <= quote.quoted_at <= end]
    return inside[-1] if inside else None


def _reading(item: RunFacts, quote: PriceQuote | None) -> QuoteReading | None:
    if quote is None:
        return None
    return QuoteReading(
        price=quote.price, quoted_at=quote.quoted_at, received_at=quote.received_at,
        return_percent=_return_percent(quote.price, item.run.reference_price),
    )


def _completion_session(item: RunFacts) -> int | None:
    if item.completion_at is None:
        return None
    for index, (_, bounds) in enumerate(item.sessions):
        if bounds[0] <= item.completion_at <= bounds[1]:
            return index
    return None


def _has_minimum_coverage(item: RunFacts, sessions: int, generated_at: datetime) -> bool:
    last_required = sessions
    completion_session = _completion_session(item)
    if completion_session is not None:
        last_required = min(sessions, completion_session)
    for index in range(last_required + 1):
        opens, closes = item.sessions[index][1]
        if opens > generated_at:
            continue
        if _last_quote(item, opens, closes) is None:
            return False
    return True


def _horizon(sessions: int, own: list[RunFacts], generated_at: datetime, window_last: int | None) -> HorizonOutput:
    referenced = [item for item in own if item.run.reference_at is not None]
    measurable = [item for item in referenced if sessions <= item.window_last]
    last = max([item.window_last for item in referenced] or [window_last if window_last is not None else sessions])
    window_end = sessions == last
    if sessions > last:
        return HorizonOutput(sessions=sessions, window_end=False, state="out_of_window", future_runs=0, concluded=None, partial=None)
    concluded, partial = BlockTally(), BlockTally()
    future_runs = 0
    for item in measurable:
        if len(item.sessions) <= sessions:
            partial.runs += 1
            partial.calendar += 1
            continue
        opens, closes = item.sessions[sessions][1]
        if generated_at < opens:
            future_runs += 1
            continue
        _tally(concluded if closes <= generated_at else partial, item, sessions, min(closes, generated_at), generated_at)
    return HorizonOutput(
        sessions=sessions, window_end=window_end, state="measured", future_runs=future_runs,
        concluded=concluded.output(), partial=partial.output(),
    )


def _tally(block: BlockTally, item: RunFacts, sessions: int, cut: datetime, generated_at: datetime) -> None:
    block.runs += 1
    in_sample = not item.cancelled and _has_minimum_coverage(item, sessions, generated_at)
    if item.cancelled:
        block.cancelled += 1
    elif not in_sample:
        block.insufficient += 1
    else:
        block.eligible += 1
        completion_session = _completion_session(item)
        if completion_session is not None and completion_session < sessions:
            block.completed_early += 1
    for percent in TARGET_PERCENTS:
        event = item.events.get(percent)
        timed_hit = event is not None and event.occurred_at is not None and event.occurred_at <= cut
        if not in_sample:
            block.outside[percent] += int(timed_hit)
        elif event is not None and event.occurred_at is None:
            block.indeterminate[percent] += 1
        else:
            block.denominators[percent] += 1
            block.hits[percent] += int(timed_hit)


def _target_order(item: RunFacts, generated_at: datetime) -> str:
    if item.cancelled:
        return "not_assessed"
    up, down = item.events.get(ORDER_UP), item.events.get(ORDER_DOWN)
    present = [event for event in (up, down) if event is not None]
    if any(event.occurred_at is None or event.evidence_quality == "unknown" or event.occurred_at > generated_at for event in present):
        return "indeterminate"
    if up is None and down is None:
        return "neither"
    if down is None:
        return "only_up"
    if up is None:
        return "only_down"
    if up.occurred_at == down.occurred_at:
        return "indeterminate"
    return "up_first" if up.occurred_at < down.occurred_at else "down_first"


def _order_counts(own: list[RunFacts], generated_at: datetime) -> dict[str, int]:
    outcomes = [_target_order(item, generated_at) for item in own if item.run.reference_at is not None]
    return {outcome: outcomes.count(outcome) for outcome in ORDER_OUTCOMES}


def _milestone(item: RunFacts, sessions: int, generated_at: datetime) -> MilestoneOutput:
    window_end = sessions == item.window_last

    def output(state: str, session_date: date | None = None, reason: str | None = None, quote: PriceQuote | None = None) -> MilestoneOutput:
        return MilestoneOutput(sessions=sessions, window_end=window_end, session_date=session_date, state=state, reason=reason, quote=_reading(item, quote))

    if sessions > item.window_last:
        return output("out_of_window")
    if len(item.sessions) <= sessions:
        return output("calendar_unavailable")
    day, (opens, closes) = item.sessions[sessions]
    if item.cancelled:
        return output("not_available", day, "cancelled_without_timestamp")
    if generated_at < opens:
        return output("future", day)
    quote = _last_quote(item, opens, closes)
    if generated_at < closes:
        return output("in_progress", day, None, quote)
    if quote is not None:
        return output("final", day, None, quote)
    if item.completed:
        return output("no_data", day, "run_completed" if item.completion_at is not None else "completion_time_unknown")
    return output("no_data", day, "no_quote_in_session")


def _confirmed_origin(observation: SignalObservation, facts: dict[UUID, RunFacts]) -> RunFacts | None:
    ingested_at = observation.created_at
    same = [item for item in facts.values() if item.instrument_id == observation.instrument_id and item.run.signal_observation_id != observation.id]
    candidates = [item for item in same if _was_open_at(item, ingested_at)]
    if len(candidates) != 1:
        return None
    origin = candidates[0]
    if any(other is not origin and origin.run.created_at <= other.run.created_at <= ingested_at for other in same):
        return None
    return origin


def _was_open_at(item: RunFacts, instant: datetime) -> bool:
    run = item.run
    if run.admitted_at is None or run.admitted_at >= instant or run.created_at >= instant:
        return False
    if run.status in OPEN_STATUSES:
        return True
    if run.status == "expired":
        return run.expires_at is not None and run.expires_at > instant
    if run.status == "completed" and item.events:
        return max(event.created_at for event in item.events.values()) > instant
    return False


def _signal_row(observation: SignalObservation, collection: CollectionRun, instrument: Instrument, own: RunFacts | None, facts: dict[UUID, RunFacts], generated_at: datetime) -> SignalProgress:
    base = _base(observation, collection, instrument)
    empty = EMPTY_PROGRESS
    if own is None:
        origin = _confirmed_origin(observation, facts)
        if origin is None:
            return SignalProgress(**base, **empty, tracking_link="unconfirmed", tracking_run_id=None, origin_market_session_date=None)
        return SignalProgress(**base, **empty, tracking_link="reused_confirmed", tracking_run_id=origin.run.id, origin_market_session_date=origin.origin_date)
    run = own.run
    if run.reference_at is None:
        pending = None
        if run.status == "prepared":
            pending = "waiting_slot" if run.admitted_at is None else "waiting_quote"
        return SignalProgress(**base, **{**empty, "status": run.status, "pending_reason": pending}, tracking_link="own", tracking_run_id=run.id, origin_market_session_date=collection.market_session_date)
    return SignalProgress(
        **base, tracking_link="own", tracking_run_id=run.id, origin_market_session_date=collection.market_session_date,
        status=run.status, pending_reason=None, reference_price=run.reference_price, reference_at=run.reference_at,
        reference_session_date=market_date(run.reference_at), expires_at=run.expires_at,
        latest_quote=_reading(own, own.quotes[-1] if own.quotes else None),
        milestones=[_milestone(own, sessions, generated_at) for sessions in MILESTONE_SESSIONS],
        target_order=_target_order(own, generated_at),
    )


def _base(observation: SignalObservation, collection: CollectionRun, instrument: Instrument) -> dict:
    return {
        "observation_id": observation.id, "collection_id": collection.id, "instrument_id": instrument.id,
        "exchange": instrument.exchange, "symbol": instrument.symbol, "observed_at": observation.observed_at,
    }
