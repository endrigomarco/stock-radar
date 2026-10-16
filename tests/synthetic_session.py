from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_radar.db.models import TradingDay

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
AFTER_OPEN = timedelta(hours=1)


def recent_open_session(engine) -> tuple[date, datetime]:
    today = datetime.now(SAO_PAULO).date()
    with Session(engine) as session:
        day, opens_at = session.execute(
            select(TradingDay.day, TradingDay.opens_at).where(TradingDay.is_open, TradingDay.day < today)
            .order_by(TradingDay.day.desc()).limit(1)
        ).one()
    return day, (datetime.combine(day, opens_at, tzinfo=SAO_PAULO) + AFTER_OPEN).astimezone(timezone.utc)
