import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import logging
import os
import time

from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from stock_radar import brapi
from stock_radar.market_calendar import CalendarUnavailable, polling_open
from stock_radar.observability.logging import configure_logging, emit, request_id
from stock_radar.observability.telemetry import Telemetry, correlation_id
from stock_radar.services.tracking import POLL_INTERVAL_MINUTES, TrackingService, quote_rejection
from stock_radar.settings import MonitorSettings, monitor_enabled

CYCLE_LOCK_KEY = "stock_radar:monitor_cycle"
STALE_CYCLES = 5
SLOT_SECONDS = POLL_INTERVAL_MINUTES * 60
SLOT_FIRST_MINUTE = 10
SLOT_OFFSET_SECONDS = 5
SLOT_PHASE_SECONDS = SLOT_FIRST_MINUTE * 60 + SLOT_OFFSET_SECONDS
IDLE_SECONDS = 3600
INFORMATIONAL_REJECTIONS = {"quote_too_old"}
SESSION_OPEN = "open"

FetchQuote = Callable[[str, str], brapi.Quote]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_cycle(engine: Engine, fetch: FetchQuote, capacity: int, stale: dict, telemetry: Telemetry, clock: Clock = utc_now) -> dict:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as guard:
        if not guard.scalar(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": CYCLE_LOCK_KEY}):
            emit("monitor_cycle_skipped", logging.WARNING, reason="cycle_already_running")
            return {"outcome": "cycle_already_running"}
        try:
            summary = _cycle(engine, fetch, capacity, stale, telemetry, clock)
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": CYCLE_LOCK_KEY})
    emit("monitor_cycle", **summary)
    return summary


def _cycle(engine: Engine, fetch: FetchQuote, capacity: int, stale: dict, telemetry: Telemetry, clock: Clock) -> dict:
    now = clock()
    with Session(engine) as session:
        expired = TrackingService(session).expire(now)
    summary = {"outcome": "completed", "expired": len(expired), "admitted": 0, "instruments": 0, "recorded": 0, "unchanged": 0, "rejected": 0, "failed": 0, "skipped": 0, "stale": []}
    state = _session_state(now)
    if state != SESSION_OPEN:
        return summary | {"outcome": state}
    with Session(engine) as session:
        service = TrackingService(session)
        source_id = service.ensure_quote_source()
        summary["admitted"] = len(service.admit(capacity, now))
        instruments = service.monitored_instruments(now)
    summary["instruments"] = len(instruments)
    for position, instrument in enumerate(instruments):
        state = _session_state(clock())
        if state != SESSION_OPEN:
            summary["outcome"] = "session_ended" if state == "market_closed" else state
            summary["skipped"] = len(instruments) - position
            break
        try:
            quote = fetch(instrument.symbol, instrument.currency)
            received_at = clock()
            reason = quote_rejection(quote.quoted_at, received_at)
            if reason:
                level = logging.INFO if reason in INFORMATIONAL_REJECTIONS else logging.WARNING
                emit("quote_rejected", level, instrument_id=str(instrument.id), symbol=instrument.symbol, reason=reason, quoted_at=quote.quoted_at.isoformat())
                outcome = "rejected"
            else:
                with Session(engine) as session:
                    outcome = TrackingService(session).apply_quote(instrument.id, source_id, quote.price, quote.quoted_at, received_at)
        except brapi.QuoteError as error:
            summary["failed"] += 1
            emit("quote_failed", logging.WARNING, instrument_id=str(instrument.id), symbol=instrument.symbol, code=error.code)
            continue
        except Exception as error:
            summary["failed"] += 1
            telemetry.error(error, "monitor", instrument_id=str(instrument.id))
            continue
        summary[outcome] += 1
        if outcome == "recorded":
            stale.pop(instrument.id, None)
            continue
        stale[instrument.id] = stale.get(instrument.id, 0) + 1
        if stale[instrument.id] >= STALE_CYCLES:
            summary["stale"].append(instrument.symbol)
            emit("quote_stale", logging.WARNING, instrument_id=str(instrument.id), symbol=instrument.symbol, cycles_without_progress=stale[instrument.id])
    return summary


def _session_state(instant: datetime) -> str:
    try:
        return SESSION_OPEN if polling_open(instant) else "market_closed"
    except CalendarUnavailable as error:
        emit("calendar_unavailable", logging.WARNING, year=error.year)
        return "calendar_unavailable"


def seconds_until_next_slot(now: float) -> float:
    return SLOT_SECONDS - (now - SLOT_PHASE_SECONDS) % SLOT_SECONDS


def run(telemetry: Telemetry) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not monitor_enabled():
        emit("monitor_disabled", logging.WARNING)
        if args.once:
            print("Monitoring is disabled. Set MONITOR_ENABLED=true and BRAPI_API_KEY in the selected environment file.")
            raise SystemExit(2)
        while True:
            time.sleep(IDLE_SECONDS)
    try:
        settings = MonitorSettings.from_environment()
    except ValidationError:
        emit("monitor_configuration_invalid", logging.ERROR)
        print("Monitor configuration is invalid. Check BRAPI_API_KEY, MONITOR_POSTGRES_PASSWORD, MONITOR_MAX_INSTRUMENTS and POSTGRES_DB.")
        raise SystemExit(2) from None
    api_key = settings.api_key.get_secret_value()
    engine = create_engine(
        settings.database_url(), pool_pre_ping=True, pool_size=2, max_overflow=0, hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000 -c lock_timeout=5000"},
    )

    def fetch(symbol: str, currency: str) -> brapi.Quote:
        return brapi.fetch_quote(symbol, currency, api_key)

    stale: dict = {}
    try:
        if args.once:
            summary = run_cycle(engine, fetch, settings.max_instruments, stale, telemetry)
            print(f"Monitoring cycle finished: {summary}")
            return
        emit("monitor_started", capacity=settings.max_instruments)
        while True:
            time.sleep(seconds_until_next_slot(time.time()))
            token = request_id.set(correlation_id())
            try:
                run_cycle(engine, fetch, settings.max_instruments, stale, telemetry)
            except Exception as error:
                telemetry.error(error, "monitor")
            finally:
                request_id.reset(token)
    finally:
        engine.dispose()


def main() -> None:
    configure_logging(os.environ.get("LOG_DIRECTORY"))
    telemetry = Telemetry()
    token = request_id.set(correlation_id())
    try:
        run(telemetry)
    except SystemExit:
        raise
    except Exception as error:
        identity = telemetry.error(error, "monitor")
        print(f"Monitor failed; error_id={identity}")
        raise SystemExit(1) from None
    finally:
        request_id.reset(token)


if __name__ == "__main__":
    main()
