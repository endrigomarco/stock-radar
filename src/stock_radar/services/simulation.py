from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext

from stock_radar.services.errors import ServiceError

SIMULATION_VERSION = "exit-v2"
ORIGINAL_VERSION = "exit-v1"
INITIAL_CAPITAL = Decimal("100000.00")
CENT = Decimal("0.01")
PRICE_STEP = Decimal("0.00000001")
PERCENT_STEP = Decimal("0.01")
PERCENT_BASE = Decimal(100)
ZERO = Decimal("0.00")
INTERMEDIATE_PRECISION = 34
TRIGGER_BASIS = "trigger_price"
QUOTE_BASIS = "first_quote"
EXIT_STATES = ("exited_target", "exited_stop")
VALUED_STATES = ("open", "window_closed")
UNRESOLVED_STATES = ("observation_ended", "unproven")
END_STATES = {"open": "open", "window_closed": "window_closed", "completed": "observation_ended"}
STATE_ORDER = ("exited_target", "exited_stop", "open", "window_closed", "pending_entry", "observation_ended", "unproven")


@dataclass(frozen=True)
class Strategy:
    code: str
    target_percent: Decimal | None
    stop_percent: Decimal | None
    added_in: str


STRATEGIES = (
    Strategy("A", Decimal("1"), Decimal("-3"), ORIGINAL_VERSION),
    Strategy("B", Decimal("2"), Decimal("-5"), ORIGINAL_VERSION),
    Strategy("C", Decimal("3"), Decimal("-6"), ORIGINAL_VERSION),
    Strategy("D", Decimal("1"), Decimal("-1"), SIMULATION_VERSION),
    Strategy("E", Decimal("2"), Decimal("-2"), SIMULATION_VERSION),
    Strategy("F", Decimal("3"), Decimal("-3"), SIMULATION_VERSION),
    Strategy("G", Decimal("1"), Decimal("-2"), SIMULATION_VERSION),
    Strategy("H", Decimal("2"), Decimal("-3"), SIMULATION_VERSION),
    Strategy("I", Decimal("3"), Decimal("-4"), SIMULATION_VERSION),
    Strategy("HOLD", None, None, ORIGINAL_VERSION),
)


@dataclass(frozen=True)
class Reading:
    price: Decimal
    quoted_at: datetime
    received_at: datetime | None


@dataclass(frozen=True)
class TradingSession:
    day: date
    opens: datetime
    closes: datetime


@dataclass(frozen=True)
class Observation:
    reference: Reading | None
    readings: tuple[Reading, ...]
    end: str
    observed_until: datetime | None
    expires_at: datetime | None
    sessions: tuple[TradingSession, ...]
    calendar_complete: bool


@dataclass(frozen=True)
class Outcome:
    strategy: Strategy
    state: str
    trigger_percent: Decimal | None
    trigger_price: Decimal | None
    exit_reading: Reading | None
    valuation: Reading | None
    trigger_value: Decimal | None
    quote_value: Decimal | None
    missing_sessions: tuple[date, ...] | None

    def value(self, basis: str) -> Decimal | None:
        return self.trigger_value if basis == TRIGGER_BASIS else self.quote_value


@dataclass(frozen=True)
class Totals:
    counts: dict[str, int]
    realized: Decimal
    unrealized: Decimal
    cash: Decimal
    open_value: Decimal
    complete: bool
    equity: Decimal | None
    result: Decimal | None
    result_percent: Decimal | None
    affected_capital: Decimal
    affected_positions: int
    coverage_missing_capital: Decimal
    coverage_missing_positions: int


@dataclass(frozen=True)
class SessionValue:
    trigger_equity: Decimal | None
    quote_equity: Decimal | None
    positions_without_quote: int
    positions_unobserved: int


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def position_value(allocation: Decimal, price: Decimal, reference: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = INTERMEDIATE_PRECISION
        return money(allocation * price / reference)


def threshold(reference: Decimal, percent: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = INTERMEDIATE_PRECISION
        return reference * (1 + percent / PERCENT_BASE)


def display_quantity(allocation: Decimal, reference: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = INTERMEDIATE_PRECISION
        return (allocation / reference).quantize(PRICE_STEP, rounding=ROUND_HALF_UP)


def display_price(price: Decimal) -> Decimal:
    return price.quantize(PRICE_STEP, rounding=ROUND_HALF_UP)


def split_capital(participants: int) -> tuple[Decimal, Decimal]:
    if participants == 0:
        return ZERO, INITIAL_CAPITAL
    with localcontext() as context:
        context.prec = INTERMEDIATE_PRECISION
        allocation = (INITIAL_CAPITAL / participants).quantize(CENT, rounding=ROUND_DOWN)
    return allocation, INITIAL_CAPITAL - allocation * participants


def first_trigger(strategy: Strategy, reference: Reading, readings: tuple[Reading, ...]) -> tuple[str, Decimal, Decimal, Reading] | None:
    if strategy.target_percent is None or strategy.stop_percent is None:
        return None
    target = threshold(reference.price, strategy.target_percent)
    stop = threshold(reference.price, strategy.stop_percent)
    for reading in readings:
        if reading.price >= target:
            return "exited_target", strategy.target_percent, target, reading
        if reading.price <= stop:
            return "exited_stop", strategy.stop_percent, stop, reading
    return None


def missing_sessions(observation: Observation, end: datetime) -> tuple[date, ...] | None:
    if not observation.calendar_complete:
        return None
    points = [point for point in (observation.reference, *observation.readings) if point.quoted_at <= end]
    return tuple(
        item.day for item in observation.sessions
        if item.opens <= end and not any(item.opens <= point.quoted_at <= item.closes for point in points)
    )


def evaluate(strategy: Strategy, allocation: Decimal, observation: Observation) -> Outcome:
    reference = observation.reference
    if reference is None:
        return Outcome(strategy, "pending_entry", None, None, None, None, None, None, ())
    if reference.received_at is None:
        return Outcome(strategy, "unproven", None, None, None, None, None, None, ())
    trigger = first_trigger(strategy, reference, observation.readings)
    if trigger is not None:
        state, percent, price, reading = trigger
        return Outcome(
            strategy, state, percent, price, reading, None,
            position_value(allocation, price, reference.price), position_value(allocation, reading.price, reference.price),
            missing_sessions(observation, reading.quoted_at),
        )
    valuation = observation.readings[-1] if observation.readings else reference
    value = position_value(allocation, valuation.price, reference.price)
    return Outcome(
        strategy, END_STATES.get(observation.end, "unproven"), None, None, None, valuation, value, value,
        missing_sessions(observation, observation.observed_until),
    )


def summarize(entries: list[tuple[Outcome, Decimal]], residual: Decimal, basis: str) -> Totals:
    counts = Counter(outcome.state for outcome, _ in entries)
    cash, open_value, realized, unrealized, affected, coverage_capital = residual, ZERO, ZERO, ZERO, ZERO, ZERO
    coverage_positions = 0
    for outcome, allocation in entries:
        value = outcome.value(basis)
        if outcome.state == "pending_entry":
            cash += allocation
            continue
        if outcome.state in EXIT_STATES:
            cash += value
            realized += value - allocation
        elif outcome.state in VALUED_STATES:
            open_value += value
            unrealized += value - allocation
        else:
            affected += allocation
        if outcome.missing_sessions != ():
            coverage_capital += allocation
            coverage_positions += 1
    unresolved = sum(counts[state] for state in UNRESOLVED_STATES)
    return _totals(counts, (realized, unrealized, cash, open_value), unresolved, affected, (coverage_capital, coverage_positions))


def _totals(counts: Counter, amounts: tuple[Decimal, Decimal, Decimal, Decimal], unresolved: int, affected: Decimal, coverage: tuple[Decimal, int]) -> Totals:
    realized, unrealized, cash, open_value = amounts
    complete = unresolved == 0
    equity = cash + open_value if complete else None
    result = equity - INITIAL_CAPITAL if equity is not None else None
    if result is not None and result != realized + unrealized:
        raise ServiceError("portfolio_reconciliation_failed", 500)
    percent = (result * PERCENT_BASE / INITIAL_CAPITAL).quantize(PERCENT_STEP, rounding=ROUND_HALF_UP) if result is not None else None
    return Totals(
        counts={state: counts[state] for state in STATE_ORDER}, realized=realized, unrealized=unrealized, cash=cash,
        open_value=open_value, complete=complete, equity=equity, result=result, result_percent=percent,
        affected_capital=affected, affected_positions=unresolved, coverage_missing_capital=coverage[0],
        coverage_missing_positions=coverage[1],
    )


def session_value(entries: list[tuple[Outcome, Decimal, Observation]], residual: Decimal, item: TradingSession, cut: datetime) -> SessionValue:
    instant = min(item.closes, cut)
    trigger_total, quote_total = residual, residual
    without_quote, unobserved = 0, 0
    for outcome, allocation, observation in entries:
        state, values = _session_contribution(outcome, allocation, observation, item.opens, instant)
        without_quote += state == "without_quote"
        unobserved += state == "unobserved"
        if values is not None:
            trigger_total += values[0]
            quote_total += values[1]
    if without_quote or unobserved:
        return SessionValue(None, None, without_quote, unobserved)
    return SessionValue(trigger_total, quote_total, 0, 0)


def _available(point: Reading, instant: datetime) -> bool:
    return point.quoted_at <= instant and point.received_at is not None and point.received_at <= instant


def _session_contribution(outcome: Outcome, allocation: Decimal, observation: Observation, opens: datetime, instant: datetime) -> tuple[str, tuple[Decimal, Decimal] | None]:
    reference = observation.reference
    if reference is None or reference.quoted_at > instant:
        return "cash", (allocation, allocation)
    if reference.received_at is None:
        return "unobserved", None
    if not _available(reference, instant):
        return "cash", (allocation, allocation)
    exit_reading = outcome.exit_reading
    if exit_reading is not None and _available(exit_reading, instant):
        return "exited", (outcome.trigger_value, outcome.quote_value)
    after_end = observation.observed_until is not None and instant > observation.observed_until
    if after_end and observation.end != "window_closed":
        return "unobserved", None
    known = [
        point for point in (reference, *observation.readings)
        if _available(point, instant) and (exit_reading is None or point.quoted_at < exit_reading.quoted_at) and (after_end or point.quoted_at >= opens)
    ]
    if not known:
        return "without_quote", None
    value = position_value(allocation, known[-1].price, reference.price)
    return "valued", (value, value)
