from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_radar.app import create_app
from stock_radar.db.config import database_url
from stock_radar.db.models import (
    CandidateDecision,
    CandidateSelection,
    CollectionRun,
    ExperimentVersion,
    Instrument,
    PriceQuote,
    SignalObservation,
    Source,
    TrackingRun,
    TriggerEvent,
)
from stock_radar.services.composition import Candidate, compose
from stock_radar.services.reports import ReportService
from stock_radar.services.simulation import (
    QUOTE_BASIS,
    SIMULATION_VERSION,
    STRATEGIES,
    TRIGGER_BASIS,
    Observation,
    Reading,
    TradingSession,
    evaluate,
    position_value,
    session_value,
    split_capital,
    summarize,
)
from stock_radar.services.tracking import MAX_QUOTE_AGE, TrackingService
from stock_radar.settings import Settings
from stock_radar.viewmodels.reports import DailyReportQuery

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
EXCHANGE = "PORTF"
CRITERIA = "selection-v1"
RECEIPT_DELAY = timedelta(minutes=5)


def at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=SAO_PAULO).astimezone(timezone.utc)


def reading(month: int, day: int, hour: int, minute: int, price: str, delay: int = 5) -> Reading:
    quoted = at(month, day, hour, minute)
    return Reading(Decimal(price), quoted, quoted + timedelta(minutes=delay))


def observation(reference: Reading | None, readings: list[Reading], end: str = "open", until: datetime | None = None, sessions: tuple = ()) -> Observation:
    last = until or (readings[-1].quoted_at if readings else reference.quoted_at if reference else None)
    return Observation(reference, tuple(readings), end if reference else "pending", last if reference else None, at(12, 30, 17) if reference else None, sessions, True)


def by_code(code: str):
    return next(item for item in STRATEGIES if item.code == code)


def documented_example() -> dict:
    allocation, residual = split_capital(3)
    aaaa = observation(reading(10, 15, 10, 40, "10.00"), [reading(10, 15, 13, 10, "10.14"), reading(10, 19, 14, 40, "10.22"), reading(10, 20, 16, 40, "10.25")])
    bbbb = observation(reading(10, 15, 10, 40, "20.00"), [reading(10, 16, 10, 40, "19.10"), reading(10, 20, 16, 40, "19.30")])
    cccc = observation(None, [])
    table = {}
    for strategy in STRATEGIES:
        entries = [(evaluate(strategy, allocation, item), allocation) for item in (aaaa, bbbb, cccc)]
        for basis in (TRIGGER_BASIS, QUOTE_BASIS):
            totals = summarize(entries, residual, basis)
            table[(strategy.code, basis)] = tuple(str(value) for value in (totals.realized, totals.unrealized, totals.cash, totals.open_value, totals.equity, totals.result, totals.result_percent))
    return table


def check_documented_example() -> None:
    table = documented_example()
    assert table[("A", TRIGGER_BASIS)] == ("-666.67", "0.00", "99333.33", "0.00", "99333.33", "-666.67", "-0.67"), table[("A", TRIGGER_BASIS)]
    assert table[("A", QUOTE_BASIS)] == ("-1033.33", "0.00", "98966.67", "0.00", "98966.67", "-1033.33", "-1.03"), table[("A", QUOTE_BASIS)]
    assert table[("B", TRIGGER_BASIS)] == ("666.67", "-1166.67", "67333.34", "32166.66", "99500.00", "-500.00", "-0.50"), table[("B", TRIGGER_BASIS)]
    assert table[("B", QUOTE_BASIS)] == ("733.33", "-1166.67", "67400.00", "32166.66", "99566.66", "-433.34", "-0.43"), table[("B", QUOTE_BASIS)]
    assert table[("C", TRIGGER_BASIS)] == table[("C", QUOTE_BASIS)] == table[("HOLD", TRIGGER_BASIS)] == ("0.00", "-333.34", "33333.34", "66333.32", "99666.66", "-333.34", "-0.33")
    expanded = {
        "D": ("0.00", "0.00", "100000.00", "0.00", "100000.00", "0.00", "0.00"),
        "E": ("0.00", "0.00", "100000.00", "0.00", "100000.00", "0.00", "0.00"),
        "F": ("-1000.00", "833.33", "65666.67", "34166.66", "99833.33", "-166.67", "-0.17"),
        "G": ("-333.34", "0.00", "99666.66", "0.00", "99666.66", "-333.34", "-0.33"),
        "H": ("-333.33", "0.00", "99666.67", "0.00", "99666.67", "-333.33", "-0.33"),
        "I": ("-1333.33", "833.33", "65333.34", "34166.66", "99500.00", "-500.00", "-0.50"),
    }
    assert {code: table[(code, TRIGGER_BASIS)] for code in expanded} == expanded
    first_quote = {"D": "-1033.33", "E": "-766.67", "F": "-666.67", "G": "-1033.33", "H": "-766.67", "I": "-666.67"}
    assert {code: table[(code, QUOTE_BASIS)][5] for code in first_quote} == first_quote


def check_definitions() -> None:
    definitions = [(item.code, item.target_percent, item.stop_percent, item.added_in) for item in STRATEGIES]
    original, expanded = "exit-v1", "exit-v2"
    assert definitions == [
        ("A", Decimal("1"), Decimal("-3"), original), ("B", Decimal("2"), Decimal("-5"), original), ("C", Decimal("3"), Decimal("-6"), original),
        ("D", Decimal("1"), Decimal("-1"), expanded), ("E", Decimal("2"), Decimal("-2"), expanded), ("F", Decimal("3"), Decimal("-3"), expanded),
        ("G", Decimal("1"), Decimal("-2"), expanded), ("H", Decimal("2"), Decimal("-3"), expanded), ("I", Decimal("3"), Decimal("-4"), expanded),
        ("HOLD", None, None, original),
    ], definitions
    assert SIMULATION_VERSION == expanded


def check_triggers_and_independence() -> None:
    reference = reading(11, 4, 10, 10, "10.00")
    path = [reading(11, 4, 11, 10, "10.15"), reading(11, 5, 11, 55, "9.45"), reading(11, 5, 14, 10, "9.40"), reading(11, 9, 10, 10, "10.40")]
    outcomes = {strategy.code: evaluate(strategy, Decimal("50000.00"), observation(reference, path)) for strategy in STRATEGIES}
    a, b, c, hold = (outcomes[code] for code in ("A", "B", "C", "HOLD"))
    assert (a.state, a.trigger_value, a.quote_value, a.exit_reading.price) == ("exited_target", Decimal("50500.00"), Decimal("50750.00"), Decimal("10.15"))
    assert (b.state, b.trigger_value, b.quote_value, b.exit_reading.price) == ("exited_stop", Decimal("47500.00"), Decimal("47250.00"), Decimal("9.45"))
    assert (c.state, c.trigger_value, c.quote_value) == ("exited_stop", Decimal("47000.00"), Decimal("47000.00"))
    assert (hold.state, hold.trigger_value, hold.valuation.price) == ("open", Decimal("52000.00"), Decimal("10.40"))
    later = evaluate(by_code("A"), Decimal("50000.00"), observation(reference, [*path, reading(11, 10, 10, 10, "7.00"), reading(11, 12, 10, 10, "15.00")]))
    assert (later.state, later.trigger_value, later.quote_value, later.exit_reading) == (a.state, a.trigger_value, a.quote_value, a.exit_reading)
    expanded = {code: (outcomes[code].state, outcomes[code].trigger_value, outcomes[code].quote_value, outcomes[code].exit_reading.price) for code in "DEFGHI"}
    assert expanded == {
        "D": ("exited_target", Decimal("50500.00"), Decimal("50750.00"), Decimal("10.15")),
        "E": ("exited_stop", Decimal("49000.00"), Decimal("47250.00"), Decimal("9.45")),
        "F": ("exited_stop", Decimal("48500.00"), Decimal("47250.00"), Decimal("9.45")),
        "G": ("exited_target", Decimal("50500.00"), Decimal("50750.00"), Decimal("10.15")),
        "H": ("exited_stop", Decimal("48500.00"), Decimal("47250.00"), Decimal("9.45")),
        "I": ("exited_stop", Decimal("48000.00"), Decimal("47250.00"), Decimal("9.45")),
    }, expanded


def check_short_stop_then_recovery() -> None:
    reference = reading(11, 4, 10, 10, "10.00")
    item = observation(reference, [reading(11, 4, 11, 10, "9.90"), reading(11, 5, 11, 10, "10.35")])
    outcomes = {strategy.code: evaluate(strategy, Decimal("50000.00"), item) for strategy in STRATEGIES}
    d = outcomes["D"]
    assert (d.state, d.trigger_value, d.quote_value, d.exit_reading.price) == ("exited_stop", Decimal("49500.00"), Decimal("49500.00"), Decimal("9.90"))
    targets = {code: (outcomes[code].state, outcomes[code].trigger_value, outcomes[code].quote_value) for code in "ABCEFGHI"}
    assert targets == {
        "A": ("exited_target", Decimal("50500.00"), Decimal("51750.00")), "B": ("exited_target", Decimal("51000.00"), Decimal("51750.00")),
        "C": ("exited_target", Decimal("51500.00"), Decimal("51750.00")), "E": ("exited_target", Decimal("51000.00"), Decimal("51750.00")),
        "F": ("exited_target", Decimal("51500.00"), Decimal("51750.00")), "G": ("exited_target", Decimal("50500.00"), Decimal("51750.00")),
        "H": ("exited_target", Decimal("51000.00"), Decimal("51750.00")), "I": ("exited_target", Decimal("51500.00"), Decimal("51750.00")),
    }, targets
    hold = outcomes["HOLD"]
    assert (hold.state, hold.trigger_value, hold.valuation.price) == ("open", Decimal("51750.00"), Decimal("10.35"))
    alone = evaluate(by_code("G"), Decimal("50000.00"), item)
    assert (alone.state, alone.trigger_value, alone.exit_reading) == (outcomes["G"].state, outcomes["G"].trigger_value, outcomes["G"].exit_reading)


def check_four_percent_stop() -> None:
    reference = reading(11, 4, 10, 10, "10.00")
    strategy_i = by_code("I")
    above = evaluate(strategy_i, Decimal("50000.00"), observation(reference, [reading(11, 4, 11, 10, "9.61")]))
    assert (above.state, above.trigger_value) == ("open", Decimal("48050.00")), above
    exact = evaluate(strategy_i, Decimal("50000.00"), observation(reference, [reading(11, 4, 11, 10, "9.61"), reading(11, 4, 12, 10, "9.60")]))
    assert (exact.state, exact.trigger_percent, exact.trigger_price, exact.trigger_value, exact.quote_value) == ("exited_stop", Decimal("-4"), Decimal("9.6000"), Decimal("48000.00"), Decimal("48000.00")), exact
    jump = evaluate(strategy_i, Decimal("50000.00"), observation(reference, [reading(11, 4, 11, 10, "9.61"), reading(11, 4, 12, 10, "9.20"), reading(11, 5, 11, 10, "10.40")]))
    assert (jump.state, jump.trigger_value, jump.quote_value, jump.exit_reading.price) == ("exited_stop", Decimal("48000.00"), Decimal("46000.00"), Decimal("9.20")), jump


def check_coverage_by_interval() -> None:
    sessions = tuple(TradingSession(date(2026, 11, day), at(11, day, 10), at(11, day, 17)) for day in (4, 5, 6, 9))
    reference = reading(11, 4, 10, 10, "10.00")
    path = [reading(11, 4, 11, 10, "10.15"), reading(11, 5, 14, 10, "9.40"), reading(11, 9, 10, 10, "10.40")]
    item = observation(reference, path, until=at(11, 9, 17), sessions=sessions)
    a, c, hold = (evaluate(by_code(code), Decimal("50000.00"), item) for code in ("A", "C", "HOLD"))
    assert a.missing_sessions == () and c.missing_sessions == () and hold.missing_sessions == (date(2026, 11, 6),), (a, c, hold)


def check_session_availability() -> None:
    allocation = Decimal("50000.00")
    closing, next_day = TradingSession(date(2026, 11, 4), at(11, 4, 10), at(11, 4, 17)), TradingSession(date(2026, 11, 5), at(11, 5, 10), at(11, 5, 17))
    cut = at(11, 5, 17, 30)
    item = observation(reading(11, 4, 10, 10, "10.00"), [reading(11, 4, 14, 10, "10.05"), reading(11, 4, 16, 59, "10.15", delay=6)], until=cut)

    def equity(strategy, observed: Observation, session: TradingSession) -> Decimal | None:
        return session_value([(evaluate(strategy, allocation, observed), allocation, observed)], Decimal("0.00"), session, cut).trigger_equity

    a, hold = by_code("A"), by_code("HOLD")
    assert evaluate(a, allocation, item).exit_reading.received_at == at(11, 4, 17, 5)
    assert equity(a, item, closing) == equity(hold, item, closing) == Decimal("50250.00")
    assert equity(a, item, next_day) == Decimal("50500.00") and equity(hold, item, next_day) is None
    late_entry = observation(reading(11, 4, 16, 50, "10.00", delay=15), [reading(11, 5, 10, 10, "10.30")], until=cut)
    assert equity(hold, late_entry, closing) == allocation and equity(hold, late_entry, next_day) == Decimal("51500.00")
    unknown = observation(Reading(Decimal("10.00"), at(11, 4, 10, 10), None), [reading(11, 4, 14, 10, "10.05")], until=cut)
    outcome = evaluate(a, allocation, unknown)
    assert (outcome.state, outcome.trigger_value, outcome.valuation) == ("unproven", None, None)
    assert session_value([(outcome, allocation, unknown)], Decimal("0.00"), closing, cut).positions_unobserved == 1


def check_precision_and_split() -> None:
    assert split_capital(1) == (Decimal("100000.00"), Decimal("0.00"))
    assert split_capital(2) == (Decimal("50000.00"), Decimal("0.00"))
    assert split_capital(3) == (Decimal("33333.33"), Decimal("0.01"))
    exact = Fraction(3333333, 100) * Fraction(721, 100) / Fraction(713, 100) * 100
    cents = int(exact) + (1 if exact - int(exact) >= Fraction(1, 2) else 0)
    assert position_value(Decimal("33333.33"), Decimal("7.21"), Decimal("7.13")) == Decimal(cents) / 100
    assert position_value(Decimal("33333.33"), Decimal("7.13") * Decimal("1.01"), Decimal("7.13")) == Decimal("33666.66")


def check_reconciliation() -> None:
    paths = [
        observation(reading(11, 4, 10, 10, "7.13"), [reading(11, 4, 11, 10, "7.21")]),
        observation(reading(11, 4, 10, 10, "3.33"), [reading(11, 5, 11, 10, "3.17")]),
        observation(reading(11, 4, 10, 10, "19.99"), [reading(11, 5, 11, 10, "20.07")]),
    ]
    for participants in (1, 2, 3):
        allocation, residual = split_capital(participants)
        for strategy in STRATEGIES:
            entries = [(evaluate(strategy, allocation, item), allocation) for item in paths[:participants]]
            for basis in (TRIGGER_BASIS, QUOTE_BASIS):
                totals = summarize(entries, residual, basis)
                assert totals.complete and totals.equity == totals.cash + totals.open_value, totals
                assert totals.result == totals.equity - Decimal("100000.00") == totals.realized + totals.unrealized, totals
    pending = summarize([(evaluate(by_code("A"), Decimal("50000.00"), observation(None, [])), Decimal("50000.00"))] * 2, Decimal("0.00"), TRIGGER_BASIS)
    assert (pending.cash, pending.result, pending.counts["pending_entry"]) == (Decimal("100000.00"), Decimal("0.00"), 2)


def check_composition() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    decided = {first: at(10, 14, 18, 5), third: at(10, 14, 18, 5), second: at(10, 15, 10, 45)}
    arrivals = {first: (at(10, 15, 10, 30), at(10, 15, 11, 5)), third: (at(10, 15, 10, 20), at(10, 15, 11, 15))}

    def at_cut(cut: datetime):
        known = {run_id: quoted for run_id, (quoted, received) in arrivals.items() if received <= cut}
        return compose([Candidate(run_id, decided[run_id], known.get(run_id)) for run_id in decided], cut, MAX_QUOTE_AGE)

    early = at_cut(at(10, 15, 10, 50))
    assert set(early.participants) == {first, second, third} and not early.final and early.first_entry_at is None
    middle = at_cut(at(10, 15, 11, 10))
    assert set(middle.participants) == {first, third} and middle.outside == (second,) and middle.final, middle
    for later in (at(10, 15, 11, 20), at(10, 20, 17)):
        stable = at_cut(later)
        assert set(stable.participants) == set(middle.participants) and stable.outside == middle.outside and stable.final
    assert at_cut(at(10, 15, 11, 20)).first_entry_at == at(10, 15, 10, 20)

    late_x, late_y = uuid4(), uuid4()
    candidates = lambda cut: [
        Candidate(late_x, at(10, 15, 10), at(10, 15, 10, 20) if cut >= at(10, 15, 11, 10) else None),
        Candidate(late_y, at(10, 15, 10, 25), at(10, 15, 10, 40)),
    ]
    provisional = compose(candidates(at(10, 15, 10, 50)), at(10, 15, 10, 50), MAX_QUOTE_AGE)
    assert set(provisional.participants) == {late_x, late_y} and not provisional.final
    settled = compose(candidates(at(10, 15, 11, 15)), at(10, 15, 11, 15), MAX_QUOTE_AGE)
    assert settled.participants == (late_x,) and settled.outside == (late_y,) and settled.final

    tie_a, tie_b, equal = uuid4(), uuid4(), uuid4()
    tie = compose([
        Candidate(tie_a, at(10, 15, 9), at(10, 15, 10, 10)), Candidate(tie_b, at(10, 15, 9), None), Candidate(equal, at(10, 15, 10, 10), None),
    ], at(10, 15, 12), MAX_QUOTE_AGE)
    assert set(tie.participants) == {tie_a, tie_b} and tie.outside == (equal,) and tie.final

    unconfirmed, before_entry, after_entry, confirmed = uuid4(), uuid4(), uuid4(), uuid4()
    receipt_unknown = compose([
        Candidate(unconfirmed, at(10, 15, 9), at(10, 15, 10, 10), False), Candidate(before_entry, at(10, 15, 10), None),
        Candidate(after_entry, at(10, 15, 10, 30), at(10, 15, 11, 10)),
    ], at(10, 20, 17), MAX_QUOTE_AGE)
    assert len(receipt_unknown.participants) == 3 and not receipt_unknown.final and receipt_unknown.first_entry_at == at(10, 15, 11, 10)
    unaffected = compose([Candidate(confirmed, at(10, 15, 9), at(10, 15, 10, 40)), Candidate(unconfirmed, at(10, 15, 9, 30), at(10, 15, 11), False)], at(10, 20, 17), MAX_QUOTE_AGE)
    assert len(unaffected.participants) == 2 and unaffected.final


class World:
    def __init__(self, admin) -> None:
        self.admin = admin
        with Session(admin) as session:
            self.brapi = TrackingService(session).ensure_quote_source()
        with Session(admin) as session:
            current = TrackingService(session).current_version()
            versions = dict(session.execute(select(ExperimentVersion.version, ExperimentVersion.id).where(ExperimentVersion.experiment_id == current.experiment_id)).all())
            self.v1, self.v2 = versions[1], versions[2]
            session.execute(insert(Source).values(code="tradingview", name="TradingView").on_conflict_do_nothing(index_elements=[Source.code]))
            session.commit()
            self.tradingview = session.scalar(select(Source.id).where(Source.code == "tradingview"))
        self.instruments: dict[str, object] = {}
        self.slots: dict[date, int] = {}

    def collection(self, day: date, received_at: datetime, assisted: bool):
        with Session(self.admin) as session:
            collection = CollectionRun(
                client_collection_id=uuid4(), source_id=self.tradingview, payload_hash=uuid4().hex + uuid4().hex,
                source_url="https://example.invalid/synthetic-portfolio", observed_at=received_at, received_at=received_at,
                market_session_date=day, status="complete", rows_examined=10, experiment_version_id=self.v2 if assisted else None,
            )
            session.add(collection)
            session.commit()
            return collection.id, received_at

    def signal(self, collection, symbol: str):
        with Session(self.admin) as session:
            if symbol not in self.instruments:
                instrument = Instrument(exchange=EXCHANGE, symbol=symbol, currency="BRL")
                session.add(instrument)
                session.flush()
                self.instruments[symbol] = instrument.id
            item = SignalObservation(
                collection_run_id=collection[0], instrument_id=self.instruments[symbol], signal_kind="analyst_consensus",
                source_symbol=f"{EXCHANGE}:{symbol}", original_rating="Viés de alta forte", normalized_rating="strong_buy",
                normalization_version="tradingview-analyst-v1", observed_price=Decimal("10"), daily_change_percent=Decimal("-1"),
                observed_at=collection[1], parse_status="valid", created_at=collection[1],
            )
            session.add(item)
            session.commit()
            return item.id

    def run(self, observation_id, assisted: bool, created_at: datetime, admitted_at: datetime | None):
        with Session(self.admin) as session:
            run = TrackingRun(
                client_tracking_id=uuid4(), payload_hash=uuid4().hex + uuid4().hex, signal_observation_id=observation_id,
                experiment_version_id=self.v2 if assisted else self.v1, status="prepared", admitted_at=admitted_at, created_at=created_at,
            )
            session.add(run)
            session.commit()
            return run.id

    def select(self, day: date, decided_at: datetime, chosen: list[tuple], late: bool = False, risks: list[str] | None = None) -> None:
        with Session(self.admin) as session:
            selection = CandidateSelection(
                client_selection_id=uuid4(), payload_hash=uuid4().hex + uuid4().hex, experiment_version_id=self.v2, market_session_date=day,
                criteria_version=CRITERIA, ranking_basis="full", summary="Synthetic portfolio selection.", decided_at=decided_at, late=late,
            )
            session.add(selection)
            session.flush()
            for observation_id, symbol, run_id in chosen:
                self.slots[day] = self.slots.get(day, 0) + 1
                session.add(CandidateDecision(
                    experiment_version_id=self.v2, market_session_date=day, instrument_id=self.instruments[symbol],
                    signal_observation_id=observation_id, candidate_selection_id=selection.id, outcome="selected", rank=self.slots[day],
                    slot=self.slots[day], tracking_run_id=run_id, rationale="Synthetic.", decided_at=decided_at,
                    details={"risks": [{"code": code, "text": "Synthetic risk."} for code in (risks or [])]},
                ))
            session.commit()

    def quote(self, symbol: str, quoted_at: datetime, price: str, delay: timedelta = RECEIPT_DELAY) -> str:
        with Session(self.admin) as session:
            return TrackingService(session).apply_quote(self.instruments[symbol], self.brapi, Decimal(price), quoted_at, quoted_at + delay)

    def cancel(self, run_id) -> None:
        with Session(self.admin) as session:
            TrackingService(session).cancel(run_id)


def build_assisted(world: World) -> dict:
    day = date(2026, 8, 3)
    collection = world.collection(day, at(8, 3, 16, 30), assisted=True)
    observations = {symbol: world.signal(collection, symbol) for symbol in ("PFA3", "PFC3", "PFD3")}
    runs = {
        "PFA3": world.run(observations["PFA3"], True, at(8, 3, 18), at(8, 4, 10)),
        "PFC3": world.run(observations["PFC3"], True, at(8, 3, 18), None),
    }
    world.select(day, at(8, 3, 18), [(observations[symbol], symbol, runs[symbol]) for symbol in ("PFA3", "PFC3")], risks=["ex_dividend"])
    runs["PFD3"] = world.run(observations["PFD3"], True, at(8, 4, 11), at(8, 4, 11))
    world.select(day, at(8, 4, 11), [(observations["PFD3"], "PFD3", runs["PFD3"])], late=True)
    for quoted_at, price, delay in (
        (at(8, 4, 10, 10), "10.00", RECEIPT_DELAY), (at(8, 4, 11, 10), "10.15", RECEIPT_DELAY), (at(8, 5, 10, 10), "9.70", RECEIPT_DELAY),
        (at(8, 5, 11, 55), "9.45", timedelta(minutes=10)), (at(8, 5, 14, 10), "9.40", RECEIPT_DELAY), (at(8, 7, 10, 10), "10.25", RECEIPT_DELAY),
    ):
        assert world.quote("PFA3", quoted_at, price, delay) == "recorded"
    world.quote("PFD3", at(8, 4, 11, 40), "5.00")
    return runs


def build_cancellations(world: World) -> dict:
    day = date(2026, 8, 10)
    collection = world.collection(day, at(8, 10, 16, 30), assisted=True)
    observations = {symbol: world.signal(collection, symbol) for symbol in ("PGA3", "PGB3", "PGC3")}
    runs = {symbol: world.run(observations[symbol], True, at(8, 10, 18), at(8, 11, 10)) for symbol in observations}
    world.select(day, at(8, 10, 18), [(observations[symbol], symbol, runs[symbol]) for symbol in ("PGA3", "PGB3", "PGC3")])
    world.quote("PGA3", at(8, 11, 10, 10), "10.00")
    world.quote("PGA3", at(8, 11, 11, 10), "9.65")
    world.quote("PGA3", at(8, 11, 13, 10), "9.40")
    world.cancel(runs["PGA3"])
    world.quote("PGA3", at(8, 11, 14, 10), "9.00")
    world.quote("PGB3", at(8, 11, 10, 10), "20.00")
    world.quote("PGB3", at(8, 11, 11, 10), "20.10")
    world.cancel(runs["PGB3"])
    assert world.quote("PGB3", at(8, 11, 11, 40), "19.30") == "recorded"
    world.quote("PGC3", at(8, 11, 10, 10), "7.13")
    world.quote("PGC3", at(8, 11, 11, 10), "7.21")
    return runs


def build_automatic(world: World) -> dict:
    first = world.collection(date(2026, 8, 12), at(8, 12, 16, 30), assisted=False)
    runs = {symbol: world.run(world.signal(first, symbol), False, at(8, 12, 16, 30), at(8, 12, 16, 30)) for symbol in ("PHA3", "PHB3")}
    for quoted_at, price in ((at(8, 13, 10, 10), "50.00"), (at(8, 13, 11, 10), "48.00"), (at(8, 13, 15, 10), "52.00")):
        world.quote("PHA3", quoted_at, price)
    for quoted_at, price in ((at(8, 13, 10, 10), "30.00"), (at(8, 14, 10, 10), "30.15"), (at(9, 1, 10, 10), "29.85")):
        world.quote("PHB3", quoted_at, price)
    second = world.collection(date(2026, 8, 17), at(8, 17, 16, 30), assisted=False)
    world.signal(second, "PHB3")
    runs["PHA3-second"] = world.run(world.signal(second, "PHA3"), False, at(8, 17, 16, 30), at(8, 17, 16, 30))
    world.quote("PHA3", at(8, 18, 10, 10), "60.00")
    world.quote("PHA3", at(8, 18, 11, 10), "61.00")
    return runs


def build_unknown_receipt(world: World) -> dict:
    day = date(2026, 8, 24)
    collection = world.collection(day, at(8, 24, 16, 30), assisted=True)
    observations = {symbol: world.signal(collection, symbol) for symbol in ("PIA3", "PIB3")}
    runs = {"PIA3": world.run(observations["PIA3"], True, at(8, 24, 18), at(8, 25, 10))}
    world.select(day, at(8, 24, 18), [(observations["PIA3"], "PIA3", runs["PIA3"])])
    world.quote("PIA3", at(8, 25, 10, 10), "10.00")
    runs["PIB3"] = world.run(observations["PIB3"], True, at(8, 25, 10, 30), at(8, 25, 10, 30))
    world.select(day, at(8, 25, 10, 30), [(observations["PIB3"], "PIB3", runs["PIB3"])], late=True)
    world.quote("PIB3", at(8, 25, 11, 10), "20.00")
    world.quote("PIA3", at(8, 25, 11, 40), "11.00")
    with Session(world.admin) as session:
        session.execute(delete(PriceQuote).where(PriceQuote.instrument_id == world.instruments["PIA3"], PriceQuote.quoted_at == at(8, 25, 10, 10)))
        session.commit()
    return runs


def strategy(portfolio: dict, code: str, basis: str = "trigger_price") -> dict:
    return next(item for item in portfolio["strategies"] if item["strategy"] == code)[basis]


def position(portfolio: dict, symbol: str) -> dict:
    return next(item for item in portfolio["positions"] if item["symbol"] == symbol)


def held(portfolio: dict, symbol: str, code: str) -> dict:
    return next(item for item in position(portfolio, symbol)["strategies"] if item["strategy"] == code)


def amounts(totals: dict, *keys: str) -> tuple:
    return tuple(None if totals[key] is None else Decimal(totals[key]) for key in keys)


def check_assisted(portfolio_at) -> None:
    final = portfolio_at(date(2026, 8, 3), at(8, 7, 17, 30))
    assert final["composition"]["status"] == "final" and final["composition"]["participants"] == 2 and final["composition"]["outside_portfolio"] == 1
    assert Decimal(final["composition"]["allocation_per_participant"]) == Decimal("50000.00") and final["provisional"] is False
    assert position(final, "PFD3")["participation"] == "outside_portfolio" and position(final, "PFD3")["allocation"] is None
    assert position(final, "PFC3")["pending_reason"] == "waiting_slot" and held(final, "PFC3", "A")["trigger_price_result"] is None
    assert position(final, "PFA3")["recorded_risks"] == ["ex_dividend"], position(final, "PFA3")
    keys = ("realized", "unrealized", "cash", "open_value", "equity", "result", "result_percent")
    assert amounts(strategy(final, "A"), *keys) == tuple(Decimal(value) for value in ("500.00", "0.00", "100500.00", "0.00", "100500.00", "500.00", "0.50"))
    assert amounts(strategy(final, "A", "first_quote"), "result") == (Decimal("750.00"),)
    assert amounts(strategy(final, "B"), "result") == (Decimal("-2500.00"),) and amounts(strategy(final, "B", "first_quote"), "result") == (Decimal("-2750.00"),)
    assert amounts(strategy(final, "C"), "result") == amounts(strategy(final, "C", "first_quote"), "result") == (Decimal("-3000.00"),)
    hold = strategy(final, "HOLD")
    assert amounts(hold, *keys) == tuple(Decimal(value) for value in ("0.00", "1250.00", "50000.00", "51250.00", "101250.00", "1250.00", "1.25")), (hold, held(final, "PFA3", "HOLD"))
    assert (hold["minimum_coverage_missing_positions"], Decimal(hold["minimum_coverage_missing_capital"])) == (1, Decimal("50000.00"))
    assert held(final, "PFA3", "HOLD")["sessions_without_quote"] == ["2026-08-06"] and held(final, "PFA3", "A")["minimum_coverage"] is True
    assert [item["strategy"] for item in final["strategies"]] == [item.code for item in STRATEGIES]
    assert [item["added_in_version"] for item in final["strategies"]] == ["exit-v1"] * 3 + ["exit-v2"] * 6 + ["exit-v1"]
    assert all(len(item["strategies"]) == len(STRATEGIES) for item in final["positions"] if item["participation"] == "participant")
    assert all(len(item["strategies"]) == len(STRATEGIES) for item in final["equity_by_session"])
    expanded = {code: (amounts(strategy(final, code), "result")[0], amounts(strategy(final, code, "first_quote"), "result")[0]) for code in "DEFGHI"}
    assert expanded == {
        "D": (Decimal("500.00"), Decimal("750.00")), "E": (Decimal("-1000.00"), Decimal("-1500.00")), "F": (Decimal("-1500.00"), Decimal("-1500.00")),
        "G": (Decimal("500.00"), Decimal("750.00")), "H": (Decimal("-1500.00"), Decimal("-1500.00")), "I": (Decimal("-2000.00"), Decimal("-2750.00")),
    }, expanded
    triggers = [(item["strategy"], item["exit_kind"], item["trigger_price"], item["quote"]["price"], item["quote"]["quoted_at"], item["quote"]["received_at"]) for item in final["triggers"]]
    assert triggers == [
        ("A", "target", "10.10000000", "10.15000000", "2026-08-04T14:10:00Z", "2026-08-04T14:15:00Z"),
        ("D", "target", "10.10000000", "10.15000000", "2026-08-04T14:10:00Z", "2026-08-04T14:15:00Z"),
        ("G", "target", "10.10000000", "10.15000000", "2026-08-04T14:10:00Z", "2026-08-04T14:15:00Z"),
        ("E", "stop", "9.80000000", "9.70000000", "2026-08-05T13:10:00Z", "2026-08-05T13:15:00Z"),
        ("F", "stop", "9.70000000", "9.70000000", "2026-08-05T13:10:00Z", "2026-08-05T13:15:00Z"),
        ("H", "stop", "9.70000000", "9.70000000", "2026-08-05T13:10:00Z", "2026-08-05T13:15:00Z"),
        ("B", "stop", "9.50000000", "9.45000000", "2026-08-05T14:55:00Z", "2026-08-05T15:05:00Z"),
        ("I", "stop", "9.60000000", "9.45000000", "2026-08-05T14:55:00Z", "2026-08-05T15:05:00Z"),
        ("C", "stop", "9.40000000", "9.40000000", "2026-08-05T17:10:00Z", "2026-08-05T17:15:00Z"),
    ], triggers
    gap = next(item for item in final["equity_by_session"] if item["session_date"] == "2026-08-06")
    gap_values = {item["strategy"]: (item["trigger_price_equity"], item["positions_without_quote"]) for item in gap["strategies"]}
    assert gap_values["A"] == ("100500.00", 0) and gap_values["HOLD"] == (None, 1), gap_values
    assert "minimum_coverage_missing" in final["limitations"] and "outside_portfolio_selections" in final["limitations"]
    assert final["latest_quote"]["symbol"] == "PFA3" and final["latest_quote"]["price"] == "10.25000000"

    noon = portfolio_at(date(2026, 8, 3), at(8, 5, 12))
    assert held(noon, "PFA3", "A")["state"] == "exited_target" and held(noon, "PFA3", "B")["state"] == "open"
    assert held(noon, "PFA3", "B")["valuation"]["price"] == "9.70000000" and amounts(strategy(noon, "B"), "equity") == (Decimal("98500.00"),)
    assert noon["latest_quote"]["quoted_at"] == "2026-08-05T13:10:00Z"

    before = portfolio_at(date(2026, 8, 3), at(8, 4, 10, 30))
    assert before["composition"]["participants"] == 2 and before["composition"]["outside_portfolio"] == 0
    assert {item["symbol"] for item in before["positions"]} == {"PFA3", "PFC3"} and before["triggers"] == []
    assert position(before, "PFA3")["entry"]["received_at"] == "2026-08-04T13:15:00Z"
    unseen = portfolio_at(date(2026, 8, 3), at(8, 4, 10, 12))
    assert position(unseen, "PFA3")["entry"] is None and unseen["composition"]["status"] == "provisional" and unseen["provisional"] is True


def check_cancellations(portfolio_at, world: World) -> None:
    with Session(world.admin) as session:
        after_cancel = (PriceQuote.instrument_id == world.instruments["PGB3"]) & (PriceQuote.quoted_at == at(8, 11, 11, 40))
        recorded = session.scalar(select(func.count(PriceQuote.id)).where(after_cancel))
        events = session.scalar(select(func.count(TriggerEvent.id)).join(PriceQuote, PriceQuote.id == TriggerEvent.price_quote_id).where(after_cancel))
    assert (recorded, events) == (1, 0)
    portfolio = portfolio_at(date(2026, 8, 10), at(8, 12, 17, 30))
    assert portfolio["composition"]["participants"] == 3 and Decimal(portfolio["composition"]["rounding_residual"]) == Decimal("0.01")
    pga = {code: held(portfolio, "PGA3", code) for code in ("A", "B", "HOLD")}
    assert pga["A"]["state"] == "exited_stop" and pga["A"]["exit_quote"]["price"] == "9.65000000"
    assert pga["B"]["state"] == "unproven" and pga["B"]["valuation"]["price"] == "9.65000000" and pga["HOLD"]["state"] == "unproven"
    assert position(portfolio, "PGA3")["observation_end"] == "cancelled" and position(portfolio, "PGA3")["observed_until"] == "2026-08-11T14:10:00Z"
    pgb = held(portfolio, "PGB3", "A")
    assert pgb["state"] == "unproven" and pgb["exit_quote"] is None and pgb["valuation"]["price"] == "20.00000000"
    assert not any(item["symbol"] == "PGB3" for item in portfolio["triggers"])
    a = strategy(portfolio, "A")
    assert a["complete"] is False and a["equity"] is None and a["result"] is None and (a["unproven"], Decimal(a["affected_capital"])) == (1, Decimal("33333.33"))
    assert (a["exits_stop"], a["exits_target"]) == (1, 1) and Decimal(a["realized"]) == Decimal("-666.67")
    pgc = held(portfolio, "PGC3", "A")
    assert (pgc["trigger_price_value"], pgc["first_quote_value"]) == ("33666.66", "33707.34"), pgc
    assert "unproven_after_last_evidence" in portfolio["limitations"]
    assert (held(portfolio, "PGA3", "D")["state"], held(portfolio, "PGA3", "D")["exit_quote"]["price"]) == ("exited_stop", "9.65000000")
    pga_i = held(portfolio, "PGA3", "I")
    assert (pga_i["state"], pga_i["exit_quote"], pga_i["valuation"]["price"]) == ("unproven", None, "9.65000000"), pga_i
    assert strategy(portfolio, "I")["complete"] is False and strategy(portfolio, "I")["equity"] is None


def check_unknown_receipt(portfolio_at, world: World) -> None:
    with Session(world.admin) as session:
        run = session.get(TrackingRun, build_unknown_receipt(world)["PIA3"])
        assert run.reference_at == at(8, 25, 10, 10) and run.reference_evidence["price_quote_id"]
        assert session.get(PriceQuote, UUID(run.reference_evidence["price_quote_id"])) is None
    portfolio = portfolio_at(date(2026, 8, 24), at(8, 25, 17, 30))
    pia = position(portfolio, "PIA3")
    assert pia["entry"] == {"price": "10.00000000", "quoted_at": "2026-08-25T13:10:00Z", "received_at": None}, pia["entry"]
    assert pia["pending_reason"] is None and pia["participation"] == "participant"
    for item in pia["strategies"]:
        assert (item["state"], item["trigger_price_value"], item["trigger_price_result"], item["exit_quote"], item["valuation"], item["minimum_coverage"]) == ("unproven", None, None, None, None, None), item
    assert not any(item["symbol"] == "PIA3" for item in portfolio["triggers"])
    assert portfolio["composition"]["status"] == "provisional" and portfolio["composition"]["participants"] == 2
    assert portfolio["composition"]["first_entry_at"] == "2026-08-25T14:10:00Z"
    for code in (item.code for item in STRATEGIES):
        totals = strategy(portfolio, code)
        assert (totals["complete"], totals["equity"], totals["unproven"], totals["pending_entry"]) == (False, None, 1, 0), totals
        assert amounts(totals, "affected_capital", "cash", "open_value") == (Decimal("50000.00"), Decimal("0.00"), Decimal("50000.00")), totals
    assert {"reference_receipt_unknown", "composition_provisional"} <= set(portfolio["limitations"])
    assert "unproven_after_last_evidence" not in portfolio["limitations"]
    session = next(item for item in portfolio["equity_by_session"] if item["session_date"] == "2026-08-25")
    assert all(item["trigger_price_equity"] is None and item["positions_unobserved"] == 1 for item in session["strategies"]), session
    assert portfolio["latest_quote"]["symbol"] == "PIA3" and portfolio["latest_quote"]["received_at"] == "2026-08-25T14:45:00Z"


def check_automatic(portfolio_at) -> None:
    portfolio = portfolio_at(date(2026, 8, 12), at(9, 18, 17))
    assert portfolio["composition"]["participants"] == 2 and portfolio["provisional"] is False
    pha = {code: held(portfolio, "PHA3", code) for code in ("A", "B", "C", "HOLD")}
    assert (pha["A"]["state"], pha["A"]["trigger_price_value"], pha["A"]["first_quote_value"]) == ("exited_stop", "48500.00", "48000.00")
    assert (pha["B"]["state"], pha["B"]["trigger_price_value"], pha["C"]["trigger_price_value"]) == ("exited_target", "51000.00", "51500.00")
    assert pha["HOLD"]["state"] == "observation_ended" and pha["HOLD"]["valuation"] == {"price": "52.00000000", "quoted_at": "2026-08-13T18:10:00Z", "received_at": "2026-08-13T18:15:00Z"}, pha["HOLD"]
    assert position(portfolio, "PHA3")["observation_end"] == "completed"
    phb = held(portfolio, "PHB3", "HOLD")
    assert (phb["state"], phb["valuation"]["price"], position(portfolio, "PHB3")["observation_end"]) == ("window_closed", "29.85000000", "window_closed")
    assert not any(item["symbol"] == "PHB3" for item in portfolio["triggers"])
    keys = ("equity", "result")
    assert amounts(strategy(portfolio, "A"), *keys) == (Decimal("98250.00"), Decimal("-1750.00"))
    assert amounts(strategy(portfolio, "A", "first_quote"), *keys) == (Decimal("97750.00"), Decimal("-2250.00"))
    assert amounts(strategy(portfolio, "B"), *keys) == (Decimal("100750.00"), Decimal("750.00"))
    assert amounts(strategy(portfolio, "C"), *keys) == (Decimal("101250.00"), Decimal("1250.00"))
    expanded = {code: (held(portfolio, "PHA3", code)["state"], held(portfolio, "PHA3", code)["trigger_price_value"], held(portfolio, "PHA3", code)["first_quote_value"]) for code in "DEFGHI"}
    assert expanded == {
        "D": ("exited_stop", "49500.00", "48000.00"), "E": ("exited_stop", "49000.00", "48000.00"), "F": ("exited_stop", "48500.00", "48000.00"),
        "G": ("exited_stop", "49000.00", "48000.00"), "H": ("exited_stop", "48500.00", "48000.00"), "I": ("exited_stop", "48000.00", "48000.00"),
    }, expanded
    hold = strategy(portfolio, "HOLD")
    assert hold["complete"] is False and hold["equity"] is None and (hold["observation_ended"], Decimal(hold["affected_capital"]), Decimal(hold["open_value"])) == (1, Decimal("50000.00"), Decimal("49750.00"))
    after = next(item for item in portfolio["equity_by_session"] if item["session_date"] == "2026-08-18")
    hold_after = next(item for item in after["strategies"] if item["strategy"] == "HOLD")
    assert hold_after["trigger_price_equity"] is None and hold_after["positions_unobserved"] == 1

    before = portfolio_at(date(2026, 8, 12), at(8, 13, 13))
    assert position(before, "PHA3")["observation_end"] == "open" and held(before, "PHA3", "B")["state"] == "open"
    assert held(before, "PHA3", "A")["state"] == "exited_stop" and held(before, "PHA3", "HOLD")["valuation"]["price"] == "48.00000000"

    second = portfolio_at(date(2026, 8, 17), at(8, 18, 17, 30))
    assert [item["symbol"] for item in second["positions"]] == ["PHA3"] and second["composition"]["participants"] == 1
    assert held(second, "PHA3", "A")["state"] == "exited_target" and Decimal(second["composition"]["allocation_per_participant"]) == Decimal("100000.00")


def check_interfaces(settings: Settings, engine) -> None:
    reader = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}

    def stored() -> tuple:
        with Session(engine) as session:
            return tuple(session.scalar(select(func.count(model.id))) for model in (CollectionRun, SignalObservation, TrackingRun, TriggerEvent, PriceQuote, CandidateDecision))

    before = stored()
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        response = client.get("/v1/reports/daily", headers=reader, params={"market_session_date": "2026-08-03"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"][0]["portfolio"]["simulation_version"] == "exit-v2" and "not real time" in body["portfolio_semantics"]
        assert body["items"][0]["horizons"] and body["items"][0]["selection"] is not None
        paged = client.get("/v1/reports/daily", headers=reader, params={"market_session_date": "2026-08-03", "signal_offset": 1, "signal_limit": 1}).json()
        assert paged["items"][0]["portfolio"] is None
        call = client.post("/mcp", headers={**reader, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "daily_report", "arguments": {"query": {"market_session_date": "2026-08-12"}}}})
        result = call.json()["result"]
        assert result["isError"] is False and result["structuredContent"]["items"][0]["portfolio"]["composition"]["participants"] == 2, result
        assert "portfolio_simulation" in client.get("/v1/status", headers=reader).json()["capabilities"]
    assert stored() == before


def main() -> None:
    check_definitions()
    check_documented_example()
    check_triggers_and_independence()
    check_short_stop_then_recovery()
    check_four_percent_stop()
    check_coverage_by_interval()
    check_precision_and_split()
    check_reconciliation()
    check_composition()
    check_session_availability()
    settings = Settings.from_environment()
    admin = create_engine(database_url())
    reader_engine = create_engine(settings.database_url())
    world = World(admin)
    build_assisted(world)
    build_cancellations(world)
    build_automatic(world)

    def portfolio_at(day: date, cut: datetime) -> dict:
        with Session(reader_engine) as session:
            report = ReportService(session, now=cut).daily(DailyReportQuery(market_session_date=day)).model_dump(mode="json")
        return report["items"][0]["portfolio"]

    check_assisted(portfolio_at)
    check_cancellations(portfolio_at, world)
    check_unknown_receipt(portfolio_at, world)
    check_automatic(portfolio_at)
    check_interfaces(settings, reader_engine)
    admin.dispose()
    reader_engine.dispose()
    print("Portfolio checks passed: ten strategy definitions, triggers, jumps, the -4% stop, independent strategies after a short stop, preserved exits, coverage by interval, cancellations, completion, expiry, cut, composition, unknown reference receipts, data availability per session, precision, reconciliation and read-only access.")


if __name__ == "__main__":
    main()
