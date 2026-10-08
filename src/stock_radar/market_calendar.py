from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/Sao_Paulo")
SATURDAY = 5


class CalendarUnavailable(Exception):
    def __init__(self, year: int) -> None:
        super().__init__(f"No versioned B3 calendar for {year}")
        self.year = year


@dataclass(frozen=True)
class TradingHours:
    effective_from: date
    opens: time
    closes: time


@dataclass(frozen=True)
class YearCalendar:
    closed: frozenset[date]
    late_openings: dict[date, time]
    hours: tuple[TradingHours, ...]


CALENDARS: dict[int, YearCalendar] = {
    2026: YearCalendar(
        closed=frozenset({
            date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 4, 21),
            date(2026, 5, 1), date(2026, 6, 4), date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 2),
            date(2026, 11, 20), date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31),
        }),
        late_openings={date(2026, 2, 18): time(13, 0)},
        hours=(TradingHours(date(2026, 1, 1), time(10, 0), time(17, 0)),),
    ),
}


def session_bounds(day: date) -> tuple[datetime, datetime] | None:
    calendar = CALENDARS.get(day.year)
    if calendar is None:
        raise CalendarUnavailable(day.year)
    if day.weekday() >= SATURDAY or day in calendar.closed:
        return None
    hours = [item for item in calendar.hours if item.effective_from <= day][-1]
    opens = calendar.late_openings.get(day, hours.opens)
    return _instant(day, opens), _instant(day, hours.closes)


def in_session(instant: datetime) -> bool:
    bounds = session_bounds(instant.astimezone(MARKET_TIMEZONE).date())
    return bounds is not None and bounds[0] <= instant <= bounds[1]


def polling_open(instant: datetime) -> bool:
    bounds = session_bounds(instant.astimezone(MARKET_TIMEZONE).date())
    return bounds is not None and bounds[0] <= instant < bounds[1]


def window_close(activated_at: datetime, sessions: int) -> datetime:
    day = activated_at.astimezone(MARKET_TIMEZONE).date()
    remaining = sessions
    while True:
        bounds = session_bounds(day)
        if bounds is not None:
            remaining -= 1
            if remaining == 0:
                return bounds[1]
        day += timedelta(days=1)


def _instant(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, tzinfo=MARKET_TIMEZONE).astimezone(timezone.utc)
