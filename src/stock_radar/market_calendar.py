from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_radar.db.models import TradingDay

MARKET_TIMEZONE = ZoneInfo("America/Sao_Paulo")
ONE_DAY = timedelta(days=1)
SESSION_SEARCH_DAYS = 15

SessionBounds = tuple[datetime, datetime]


class CalendarUnavailable(Exception):
    def __init__(self, year: int) -> None:
        super().__init__(f"No trading calendar coverage for {year}")
        self.year = year


@dataclass(frozen=True)
class TradingCalendar:
    days: dict[date, SessionBounds | None]

    def session_bounds(self, day: date) -> SessionBounds | None:
        if day not in self.days:
            raise CalendarUnavailable(day.year)
        return self.days[day]

    def in_session(self, instant: datetime) -> bool:
        bounds = self.session_bounds(market_date(instant))
        return bounds is not None and bounds[0] <= instant <= bounds[1]

    def polling_open(self, instant: datetime) -> bool:
        bounds = self.session_bounds(market_date(instant))
        return bounds is not None and bounds[0] <= instant < bounds[1]


def market_date(instant: datetime) -> date:
    return instant.astimezone(MARKET_TIMEZONE).date()


def load_calendar(session: Session, first: date, last: date | None = None) -> TradingCalendar:
    statement = select(TradingDay.day, TradingDay.is_open, TradingDay.opens_at, TradingDay.closes_at).where(TradingDay.day >= first)
    if last is not None:
        statement = statement.where(TradingDay.day <= last)
    rows = session.execute(statement.order_by(TradingDay.day)).all()
    return TradingCalendar({row.day: _bounds(row.day, row.opens_at, row.closes_at) if row.is_open else None for row in rows})


def load_around(session: Session, instant: datetime) -> TradingCalendar:
    day = market_date(instant)
    return load_calendar(session, day - ONE_DAY, day + ONE_DAY)


def window_close(session: Session, activated_at: datetime, sessions: int) -> datetime:
    day = market_date(activated_at)
    calendar = load_calendar(session, day)
    remaining = sessions
    while True:
        bounds = calendar.session_bounds(day)
        if bounds is not None:
            remaining -= 1
            if remaining == 0:
                return bounds[1]
        day += ONE_DAY


def described_session(session: Session, observed_at: datetime) -> date:
    day = market_date(observed_at)
    calendar = load_calendar(session, day - timedelta(days=SESSION_SEARCH_DAYS), day)
    bounds = calendar.session_bounds(day)
    if bounds is not None and observed_at >= bounds[0]:
        return day
    previous = day - ONE_DAY
    while calendar.session_bounds(previous) is None:
        previous -= ONE_DAY
    return previous


def next_session_open(session: Session, day: date) -> datetime:
    calendar = load_calendar(session, day + ONE_DAY, day + timedelta(days=SESSION_SEARCH_DAYS))
    following = day + ONE_DAY
    while (bounds := calendar.session_bounds(following)) is None:
        following += ONE_DAY
    return bounds[0]


def session_close(session: Session, day: date) -> datetime | None:
    bounds = load_calendar(session, day, day).session_bounds(day)
    return bounds[1] if bounds is not None else None


def _bounds(day: date, opens: time, closes: time) -> SessionBounds:
    return _instant(day, opens), _instant(day, closes)


def _instant(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, tzinfo=MARKET_TIMEZONE).astimezone(timezone.utc)
