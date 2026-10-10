from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_radar.db.models import TradingDay

MARKET_TIMEZONE = ZoneInfo("America/Sao_Paulo")
ONE_DAY = timedelta(days=1)

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


def _bounds(day: date, opens: time, closes: time) -> SessionBounds:
    return _instant(day, opens), _instant(day, closes)


def _instant(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, tzinfo=MARKET_TIMEZONE).astimezone(timezone.utc)
