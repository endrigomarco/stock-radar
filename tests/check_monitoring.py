from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Barrier, Thread
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from stock_radar import brapi
from stock_radar.app import create_app
from stock_radar.db.config import database_url
from stock_radar.db.models import Experiment, ExperimentVersion, Instrument, PriceQuote, SignalObservation, TrackingRun, TradingDay, TriggerEvent, TriggerLevel
from stock_radar.market_calendar import CalendarUnavailable, load_calendar, window_close
from stock_radar.monitor import run_cycle, seconds_until_next_slot
from stock_radar.observability.telemetry import Telemetry
from stock_radar.services.tracking import EXPERIMENT_CODE, TrackingService
from stock_radar.settings import MonitorSettings, Settings

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
SYNTHETIC_KEY = "synthetic-brapi-key-for-isolated-tests-only"


def at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=SAO_PAULO).astimezone(timezone.utc)


def quote(symbol: str, price: str, when: datetime) -> brapi.Quote:
    return brapi.Quote(symbol=symbol, currency="BRL", price=Decimal(price), quoted_at=when)


class Provider:
    def __init__(self) -> None:
        self.responses: dict = {}
        self.calls: list[str] = []

    def __call__(self, symbol: str, currency: str) -> brapi.Quote:
        self.calls.append(symbol)
        response = self.responses.get(symbol, brapi.QuoteError("provider_http_500"))
        if callable(response):
            response = response()
        if isinstance(response, Exception):
            raise response
        return response


class Clock:
    def __init__(self) -> None:
        self.now = at(3, 16, 9)

    def __call__(self) -> datetime:
        return self.now


def check_schedule() -> None:
    def next_slot(hour: int, minute: int, second: int = 0) -> str:
        now = at(3, 16, hour, minute).timestamp() + second
        wake = datetime.fromtimestamp(now + seconds_until_next_slot(now), SAO_PAULO)
        assert 0 < wake.timestamp() - now <= 1800
        return wake.strftime("%d %H:%M:%S")

    expected = {
        (9, 0): "16 09:10:05", (9, 59, 59): "16 10:10:05", (10, 0): "16 10:10:05", (10, 9, 59): "16 10:10:05",
        (10, 10): "16 10:10:05", (10, 10, 4): "16 10:10:05", (10, 10, 5): "16 10:40:05", (10, 10, 6): "16 10:40:05",
        (10, 30): "16 10:40:05", (10, 39, 59): "16 10:40:05", (10, 40): "16 10:40:05", (10, 40, 5): "16 11:10:05",
        (10, 41): "16 11:10:05", (10, 59, 59): "16 11:10:05", (11, 0): "16 11:10:05", (11, 10, 5): "16 11:40:05",
        (16, 40, 5): "16 17:10:05", (23, 40, 5): "17 00:10:05", (23, 59, 59): "17 00:10:05",
    }
    for moment, wake in expected.items():
        assert next_slot(*moment) == wake, (moment, next_slot(*moment), wake)
    assert seconds_until_next_slot(at(3, 16, 10, 10).timestamp() + 5.25) == 1799.75


def check_provider_contract() -> None:
    valid = {"results": [{"symbol": "AAAA3", "currency": "BRL", "regularMarketPrice": 12.34, "regularMarketTime": "2026-03-16T13:20:00.000Z"}]}
    parsed = brapi.parse_quote(json.dumps(valid).encode(), "AAAA3", "BRL")
    assert parsed.price == Decimal("12.34") and parsed.quoted_at == at(3, 16, 10, 20)
    for change, expected in [
        ({"symbol": "BBBB3"}, "provider_symbol_mismatch"), ({"currency": "USD"}, "provider_currency_mismatch"),
        ({"regularMarketPrice": -1}, "provider_invalid_price"), ({"regularMarketPrice": "12.34"}, "provider_invalid_price"),
        ({"regularMarketTime": "2026-03-16T13:20:00"}, "provider_invalid_timestamp"), ({"regularMarketTime": None}, "provider_invalid_timestamp"),
    ]:
        body = json.dumps({"results": [valid["results"][0] | change]}).encode()
        try:
            brapi.parse_quote(body, "AAAA3", "BRL")
        except brapi.QuoteError as error:
            assert error.code == expected, error.code
        else:
            raise AssertionError(f"Invalid provider payload accepted: {change}")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path.endswith("/REDIR3"):
                self.send_response(302)
                self.send_header("Location", "/api/quote/AAAA3")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(valid).encode())

        def log_message(self, *args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}/api"
        assert brapi.fetch_quote("AAAA3", "BRL", SYNTHETIC_KEY, base_url=base_url).price == Decimal("12.34")
        assert seen == [("/api/quote/AAAA3", "Bearer " + SYNTHETIC_KEY)]
        for symbol, expected in [("REDIR3", "provider_http_302"), ("bad/../x", "unsupported_symbol")]:
            try:
                brapi.fetch_quote(symbol, "BRL", SYNTHETIC_KEY, base_url=base_url)
            except brapi.QuoteError as error:
                assert error.code == expected and SYNTHETIC_KEY not in str(error)
            else:
                raise AssertionError("Unsafe provider request accepted")
        assert len(seen) == 2
    finally:
        server.shutdown()


def check_calendar(admin, monitor_engine, collector_engine, reader_engine) -> None:
    closed_2026 = {
        date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 4, 21),
        date(2026, 5, 1), date(2026, 6, 4), date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 2),
        date(2026, 11, 20), date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31),
    }
    national = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    with Session(admin) as session:
        rows = {row.day: row for row in session.scalars(select(TradingDay)).all()}
    by_year = {year: [day for day in rows if day.year == year] for year in (2026, 2027, 2028)}
    assert [len(by_year[year]) for year in (2026, 2027, 2028)] == [365, 365, 366] and len(rows) == 1096
    weekday_closures = {year: {day for day in by_year[year] if not rows[day].is_open and day.weekday() < 5} for year in by_year}
    assert weekday_closures[2026] == closed_2026
    for year in (2027, 2028):
        assert weekday_closures[year] == {date(year, month, day) for month, day in national if date(year, month, day).weekday() < 5}
    assert all(not rows[day].is_open for day in rows if day.weekday() >= 5)
    hours = {(rows[day].opens_at, rows[day].closes_at) for day in rows if rows[day].is_open and day != date(2026, 2, 18)}
    assert hours == {(time(10, 0), time(17, 0))} and rows[date(2026, 2, 18)].opens_at == time(13, 0) and rows[date(2026, 2, 18)].closes_at == time(17, 0)
    assert {rows[day].origin for day in by_year[2026]} == {"existing_configuration"}
    assert {rows[day].origin for day in by_year[2027] + by_year[2028]} == {"national_holidays"}
    assert rows[date(2028, 2, 29)].is_open and rows[date(2027, 2, 8)].is_open and rows[date(2027, 3, 26)].is_open
    with Session(admin) as session:
        calendar = load_calendar(session, date(2026, 12, 30), date(2027, 1, 4))
    assert calendar.session_bounds(date(2026, 12, 31)) is None and calendar.session_bounds(date(2027, 1, 1)) is None
    assert calendar.session_bounds(date(2027, 1, 4))[1] == datetime(2027, 1, 4, 17, 0, tzinfo=SAO_PAULO).astimezone(timezone.utc)
    try:
        calendar.session_bounds(date(2027, 1, 5))
    except CalendarUnavailable as error:
        assert error.year == 2027
    else:
        raise AssertionError("A day outside the loaded range was treated as covered")
    with monitor_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM trading_days")) == 1096
    for engine, statement in [(monitor_engine, "DELETE FROM trading_days"), (monitor_engine, "UPDATE trading_days SET is_open = false, opens_at = NULL, closes_at = NULL"), (collector_engine, "SELECT 1 FROM trading_days"), (reader_engine, "SELECT 1 FROM trading_days")]:
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except DBAPIError as error:
            assert error.orig.sqlstate == "42501"
        else:
            raise AssertionError("A role exceeded its trading calendar grants")


def main() -> None:
    check_schedule()
    check_provider_contract()
    settings = Settings.from_environment()
    admin = create_engine(database_url())
    collector_engine = create_engine(settings.database_url(write=True))
    monitor_engine = create_engine(MonitorSettings.from_environment().database_url())
    reader_engine = create_engine(settings.database_url())
    check_calendar(admin, monitor_engine, collector_engine, reader_engine)
    reader_engine.dispose()
    reader = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}
    collector = {"Authorization": f"Bearer {settings.collector_token.get_secret_value()}"}
    provider, clock, telemetry, stale = Provider(), Clock(), Telemetry(), {}

    def cycle(when: datetime, capacity: int = 2, counters: dict | None = None, **responses) -> dict:
        clock.now = when
        provider.responses = {symbol + "3": response for symbol, response in responses.items()}
        provider.calls = []
        return run_cycle(monitor_engine, provider, capacity, stale if counters is None else counters, telemetry, clock)

    def run_of(symbol: str, *statuses: str) -> TrackingRun:
        with Session(admin) as session:
            statement = select(TrackingRun).join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id).join(Instrument, Instrument.id == SignalObservation.instrument_id).where(Instrument.exchange == "MON", Instrument.symbol == symbol)
            if statuses:
                statement = statement.where(TrackingRun.status.in_(statuses))
            runs = session.scalars(statement.order_by(TrackingRun.created_at.desc())).all()
            assert len(runs) == 1, (symbol, statuses, len(runs))
            return runs[0]

    def count(model, *conditions) -> int:
        with Session(admin) as session:
            return session.scalar(select(func.count(model.id)).where(*conditions))

    def events_of(run_id: UUID) -> list[TriggerEvent]:
        with Session(admin) as session:
            return list(session.scalars(select(TriggerEvent).join(TriggerLevel, TriggerLevel.id == TriggerEvent.trigger_level_id).where(TriggerLevel.tracking_run_id == run_id)).all())

    def quotes_of(symbol: str) -> int:
        with Session(admin) as session:
            return session.scalar(select(func.count(PriceQuote.id)).join(Instrument, Instrument.id == PriceQuote.instrument_id).where(Instrument.exchange == "MON", Instrument.symbol == symbol))

    with admin.begin() as connection:
        connection.execute(text("UPDATE tracking_runs SET status = 'cancelled' WHERE status = 'prepared' AND reference_price IS NULL"))
        webhook_run_id = connection.scalar(select(TrackingRun.id).join(ExperimentVersion, ExperimentVersion.id == TrackingRun.experiment_version_id).join(Experiment, Experiment.id == ExperimentVersion.experiment_id).where(Experiment.code == "webhook_test"))
    assert webhook_run_id is not None

    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        source = client.post("/v1/sources", headers=collector, json={"code": "tradingview", "name": "TradingView"}).json()

        def collect(symbol: str, observed_at: datetime) -> None:
            row = {"exchange": "MON", "symbol": symbol, "currency": "BRL", "source_symbol": "MON:" + symbol, "signal_kind": "analyst_consensus", "original_rating": "Strong Buy", "observed_price": "10", "daily_change_percent": "-1.5", "observed_at": observed_at.isoformat()}
            payload = {"client_collection_id": str(uuid4()), "source_id": source["id"], "source_url": "https://example.invalid/synthetic", "observed_at": observed_at.isoformat(), "market_session_date": "2026-03-16", "status": "complete", "schema_version": 2, "rows_examined": 2, "observations": [row]}
            response = client.post("/v1/collections", headers=collector, json=payload)
            assert response.status_code == 200, response.text

        def call(tool: str, arguments: dict, headers: dict = reader) -> dict:
            response = client.post("/mcp", headers={**headers, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})
            assert response.status_code == 200, response.text
            return response.json()["result"]

        collect("BBBB3", at(3, 16, 9))
        collect("CCCC3", at(3, 16, 10, 40))
        collect("AAAA3", at(3, 16, 9))
        collect("AAAA3", at(3, 16, 9, 5))
        first = run_of("AAAA3", "prepared")
        assert first.reference_price is None and first.reference_evidence is None and first.admitted_at is None and first.expires_at is None
        assert count(TrackingRun, TrackingRun.status == "prepared") == 3
        assert client.post(f"/v1/tracking-runs/{first.id}/cancel", headers=reader).status_code == 403
        assert client.post(f"/v1/tracking-runs/{uuid4()}/cancel", headers=collector).status_code == 404
        for _ in range(2):
            cancelled = client.post(f"/v1/tracking-runs/{first.id}/cancel", headers=collector)
            assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled", cancelled.text
        assert call("cancel_tracking_run", {"tracking_run_id": str(first.id)}, collector)["structuredContent"]["status"] == "cancelled"
        assert call("cancel_tracking_run", {"tracking_run_id": str(first.id)})["isError"]

        with admin.begin() as connection:
            first_version = connection.execute(select(ExperimentVersion).join(Experiment, Experiment.id == ExperimentVersion.experiment_id).where(Experiment.code == EXPERIMENT_CODE)).one()
            connection.execute(ExperimentVersion.__table__.insert().values(experiment_id=first_version.experiment_id, version=2, analysis_kind=first_version.analysis_kind, rules=first_version.rules))
        with Session(admin) as session:
            versions = session.scalars(select(ExperimentVersion).where(ExperimentVersion.experiment_id == first_version.experiment_id).order_by(ExperimentVersion.version)).all()
            session.expunge_all()
            instrument_id = session.scalar(select(Instrument.id).where(Instrument.exchange == "MON", Instrument.symbol == "AAAA3"))
            observations = session.scalars(select(SignalObservation.id).where(SignalObservation.instrument_id == instrument_id)).all()
        barrier = Barrier(2)

        def attach(index: int) -> bool:
            with Session(collector_engine) as session, session.begin():
                barrier.wait(timeout=10)
                return TrackingService(session).attach(observations[index], instrument_id, versions[index])

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(attach, range(2))) == [False, True]
        run_of("AAAA3", "prepared")
        collect("DDDD3", at(3, 16, 9))
        collect("EEEE3", at(3, 16, 9))

        summary = cycle(at(3, 16, 10, 30), BBBB=quote("BBBB3", "100", at(3, 16, 10, 20)), CCCC=quote("CCCC3", "50", at(3, 16, 10, 25)))
        assert summary["admitted"] == 2 and provider.calls == ["BBBB3", "CCCC3"] and summary["recorded"] == 2, summary
        tracked = run_of("BBBB3")
        assert tracked.status == "active" and tracked.reference_price == Decimal("100") and tracked.activated_at == at(3, 16, 10, 20)
        assert tracked.expires_at == at(4, 13, 17) and tracked.price_coverage == "partial" and tracked.coverage_evidence["method"] == "polling"
        with Session(admin) as session:
            levels = {level.signed_percent: level for level in session.scalars(select(TriggerLevel).where(TriggerLevel.tracking_run_id == tracked.id)).all()}
        assert {percent: level.mathematical_price for percent, level in levels.items()} == {Decimal(p): Decimal(100 + p) for p in [-3, -2, -1, 1, 2, 3]}
        early = run_of("CCCC3")
        assert early.status == "prepared" and early.admitted_at == at(3, 16, 10, 30) and early.reference_price is None and quotes_of("CCCC3") == 1
        assert run_of("AAAA3", "prepared").admitted_at is None
        assert client.post(f"/v1/tracking-runs/{early.id}/cancel", headers=collector).status_code == 200

        collect("BBBB3", at(3, 16, 10, 45))
        summary = cycle(at(3, 16, 11), AAAA=quote("AAAA3", "20", at(3, 16, 10, 50)), BBBB=quote("BBBB3", "100.5", at(3, 16, 10, 50)))
        assert summary["admitted"] == 1 and provider.calls == ["AAAA3", "BBBB3"], summary
        assert run_of("AAAA3", "active").reference_price == Decimal("20") and run_of("DDDD3").admitted_at is None
        unchanged = run_of("BBBB3")
        assert (unchanged.id, unchanged.reference_price, unchanged.reference_at, unchanged.expires_at) == (tracked.id, tracked.reference_price, tracked.reference_at, tracked.expires_at)
        assert count(TriggerLevel, TriggerLevel.tracking_run_id == tracked.id) == 6 and events_of(tracked.id) == []

        summary = cycle(at(3, 16, 11, 30), BBBB=quote("BBBB3", "150", at(3, 16, 11, 40)))
        assert summary["rejected"] == 1 and summary["failed"] == 1 and quotes_of("BBBB3") == 2 and events_of(tracked.id) == [], summary
        summary = cycle(at(3, 16, 12), BBBB=quote("BBBB3", "102.5", at(3, 16, 11, 50)))
        assert summary["recorded"] == 1 and summary["failed"] == 1, summary
        hits = events_of(tracked.id)
        assert {event.trigger_level_id for event in hits} == {levels[Decimal(1)].id, levels[Decimal(2)].id}
        assert all(event.occurred_at == at(3, 16, 11, 50) and event.evidence_quality == "coarse" and event.price_quote_id and event.webhook_receipt_id is None for event in hits)
        summary = cycle(at(3, 16, 12, 30), AAAA=quote("AAAA3", "25", at(3, 16, 11)), BBBB=quote("BBBB3", "102.5", at(3, 16, 11, 50)))
        assert summary["unchanged"] == 1 and summary["rejected"] == 1 and quotes_of("AAAA3") == 1 and len(events_of(tracked.id)) == 2, summary
        summary = cycle(at(3, 16, 12, 35), BBBB=quote("BBBB3", "90", at(3, 16, 11, 45)))
        assert summary["unchanged"] == 1 and len(events_of(tracked.id)) == 2 and quotes_of("BBBB3") == 3, summary
        cycle(at(3, 16, 13, 30), BBBB=quote("BBBB3", "96.5", at(3, 16, 13, 20)))
        assert len(events_of(tracked.id)) == 5 and run_of("BBBB3").status == "active"
        cycle(at(3, 16, 14), BBBB=quote("BBBB3", "103", at(3, 16, 13, 50)))
        assert len(events_of(tracked.id)) == 6 and run_of("BBBB3").status == "completed"
        assert client.post(f"/v1/tracking-runs/{tracked.id}/cancel", headers=collector).status_code == 409

        def cancel_during_fetch() -> brapi.Quote:
            with admin.begin() as connection:
                connection.execute(text("UPDATE tracking_runs SET status = 'cancelled' WHERE id = :id"), {"id": run_of("DDDD3").id})
            return quote("DDDD3", "30", at(3, 16, 14, 20))

        summary = cycle(at(3, 16, 14, 30), DDDD=cancel_during_fetch)
        interrupted = run_of("DDDD3")
        assert summary["admitted"] == 1 and interrupted.status == "cancelled" and interrupted.reference_price is None, summary
        assert count(TriggerLevel, TriggerLevel.tracking_run_id == interrupted.id) == 0 and quotes_of("DDDD3") == 1
        summary = cycle(at(3, 16, 15))
        assert summary["admitted"] == 1 and provider.calls == ["AAAA3", "EEEE3"] and summary["failed"] == 2, summary

        summary = cycle(at(3, 17, 10), AAAA=quote("AAAA3", "21", at(3, 17, 9, 40)))
        assert summary["rejected"] == 1 and quotes_of("AAAA3") == 1, summary
        counters: dict = {}
        repeated = quote("AAAA3", "20.1", at(3, 17, 10, 20))
        assert cycle(at(3, 17, 10, 30), counters=counters, AAAA=repeated)["recorded"] == 1
        for hour, minute in [(11, 0), (11, 30), (12, 0), (12, 30)]:
            assert cycle(at(3, 17, hour, minute), counters=counters, AAAA=repeated)["stale"] == []
        assert cycle(at(3, 17, 13), counters=counters, AAAA=repeated)["stale"] == ["AAAA3"]
        assert quotes_of("AAAA3") == 2 and events_of(run_of("AAAA3", "active").id) == []

        def exceed_close() -> brapi.Quote:
            clock.now = at(3, 17, 17, 1)
            return repeated

        summary = cycle(at(3, 17, 16, 59), AAAA=exceed_close)
        assert provider.calls == ["AAAA3"] and summary == summary | {"outcome": "session_ended", "instruments": 2, "rejected": 1, "skipped": 1, "failed": 0}, summary

        for closed in [at(4, 3, 11), at(2, 18, 11), at(3, 21, 11), at(3, 17, 17)]:
            summary = cycle(closed)
            assert summary["outcome"] == "market_closed" and provider.calls == [], (closed, summary)
        assert cycle(at(2, 18, 13, 30))["outcome"] == "completed" and provider.calls == ["AAAA3", "EEEE3"]

        summary = cycle(at(4, 13, 16, 30), AAAA=quote("AAAA3", "20.2", at(4, 13, 16, 20)))
        final = run_of("AAAA3", "active")
        assert summary["expired"] == 0 and final.status == "active" and len(events_of(final.id)) == 1, summary
        summary = cycle(at(4, 13, 18))
        assert summary == summary | {"outcome": "market_closed", "expired": 1} and provider.calls == [] and run_of("AAAA3", "expired").id == final.id, summary
        cycle(at(4, 14, 10, 30), AAAA=quote("AAAA3", "30", at(4, 14, 10, 20)))
        assert provider.calls == ["EEEE3"] and len(events_of(final.id)) == 1 and quotes_of("AAAA3") == 3

        gap = date(2027, 1, 6)
        columns = "is_open, opens_at, closes_at, description, origin, source_reference, consulted_on"
        with admin.begin() as connection:
            removed = dict(connection.execute(text(f"DELETE FROM trading_days WHERE day = :day RETURNING {columns}"), {"day": gap}).mappings().one())
        summary = cycle(at(12, 14, 10, 30), EEEE=quote("EEEE3", "40", at(12, 14, 10, 20)))
        pending = run_of("EEEE3")
        assert summary["recorded"] == 1 and pending.status == "prepared" and pending.reference_price is None and pending.expires_at is None, summary
        assert count(TriggerLevel, TriggerLevel.tracking_run_id == pending.id) == 0 and quotes_of("EEEE3") == 1
        with admin.begin() as connection:
            connection.execute(text(f"INSERT INTO trading_days (day, {columns}) VALUES (:day, :is_open, :opens_at, :closes_at, :description, :origin, :source_reference, :consulted_on)"), {"day": gap, **removed})
        year_end_close = datetime(2027, 1, 14, 17, 0, tzinfo=SAO_PAULO).astimezone(timezone.utc)
        summary = cycle(at(12, 14, 11, 0), EEEE=quote("EEEE3", "41", at(12, 14, 10, 50)))
        crossing = run_of("EEEE3")
        assert summary["recorded"] == 1 and crossing.status == "active" and crossing.activated_at == at(12, 14, 10, 50) and crossing.expires_at == year_end_close, crossing.expires_at
        statements: list[str] = []

        def record(connection, cursor, statement, parameters, context, executemany) -> None:
            statements.append(statement)

        event.listen(admin, "before_cursor_execute", record)
        with Session(admin) as session:
            assert window_close(session, at(12, 14, 10, 50), 20) == year_end_close
            assert window_close(session, at(12, 14, 10, 50), 1) == at(12, 14, 17)
        event.remove(admin, "before_cursor_execute", record)
        assert len(statements) == 2 and all("trading_days" in statement for statement in statements), statements
        changed = date(2027, 1, 5)
        with admin.begin() as connection:
            connection.execute(text("UPDATE trading_days SET is_open = false, opens_at = NULL, closes_at = NULL WHERE day = :day"), {"day": changed})
        cycle(at(12, 15, 10, 30), EEEE=quote("EEEE3", "41.1", at(12, 15, 10, 20)))
        with Session(admin) as session:
            assert window_close(session, at(12, 14, 10, 50), 20) == datetime(2027, 1, 15, 17, 0, tzinfo=SAO_PAULO).astimezone(timezone.utc)
        assert run_of("EEEE3").expires_at == year_end_close and quotes_of("EEEE3") == 3
        with admin.begin() as connection:
            connection.execute(text("UPDATE trading_days SET is_open = true, opens_at = '10:00', closes_at = '17:00' WHERE day = :day"), {"day": changed})
        clock.now = datetime(2025, 12, 30, 14, 0, tzinfo=timezone.utc)
        provider.calls = []
        assert run_cycle(monitor_engine, provider, 2, stale, telemetry, clock)["outcome"] == "calendar_unavailable" and provider.calls == []

        with Session(admin) as session:
            legacy = session.get(TrackingRun, webhook_run_id)
            assert legacy.status == "active" and legacy.admitted_at is None and legacy.expires_at < at(12, 15, 10, 30)

        with admin.connect() as holder:
            holder.execute(text("SELECT pg_advisory_lock(hashtextextended('stock_radar:monitor_cycle', 0))"))
            assert cycle(at(12, 15, 10, 30))["outcome"] == "cycle_already_running" and provider.calls == []
            holder.execute(text("SELECT pg_advisory_unlock(hashtextextended('stock_radar:monitor_cycle', 0))"))
        assert cycle(at(12, 15, 10, 30))["outcome"] == "completed" and provider.calls == ["EEEE3"]

        with admin.begin() as connection:
            connection.execute(text("UPDATE trigger_levels SET alert_source_id = :source, alert_active_at = :active WHERE id = :id"), {"source": source["id"], "active": at(3, 16, 10, 20), "id": levels[Decimal(1)].id})
        webhook = {"schema_version": 1, "alert_mapping_id": str(levels[Decimal(1)].alert_mapping_id), "tracking_run_id": str(tracked.id), "signed_percent": "1", "source_event_at": at(3, 16, 11, 30).isoformat(), "observed_price": "101", "provider_event_id": "earlier-than-quote"}
        accepted = client.post("/webhooks/tradingview", json=webhook, headers={"Authorization": "Bearer " + settings.webhook_token.get_secret_value()})
        assert accepted.status_code == 202, accepted.text
        receipt = client.get("/v1/webhook-receipts/" + accepted.json()["id"], headers=reader).json()
        assert receipt["status"] == "processed", receipt
        with Session(admin) as session:
            replaced = session.scalar(select(TriggerEvent).where(TriggerEvent.trigger_level_id == levels[Decimal(1)].id))
            assert str(replaced.webhook_receipt_id) == receipt["id"] and replaced.price_quote_id is None and replaced.occurred_at == at(3, 16, 11, 30)

        assert client.get("/v1/tracking-runs").status_code == 401
        completed = client.get("/v1/tracking-runs?status=completed", headers=reader).json()["items"]
        assert [(item["symbol"], item["levels_hit"], item["levels_total"], item["reference_price"]) for item in completed] == [("BBBB3", 6, 6, "100.00000000")]
        assert client.get("/v1/tracking-runs?status=invalid", headers=reader).status_code == 422
        latest = client.get(f"/v1/quotes/latest?instrument_id={completed[0]['instrument_id']}", headers=reader).json()["items"]
        assert len(latest) == 1 and latest[0]["price"] == "103.00000000" and latest[0]["quoted_at"] != latest[0]["received_at"]
        events = client.get(f"/v1/trigger-events?tracking_run_id={tracked.id}", headers=reader).json()["items"]
        assert len(events) == 6 and sorted(item["evidence_kind"] for item in events).count("webhook") == 1
        assert call("list_tracking_runs", {"query": {"status": "expired"}})["structuredContent"]["items"][0]["symbol"] == "AAAA3"
        assert len(call("list_trigger_events", {"query": {"tracking_run_id": str(tracked.id)}})["structuredContent"]["items"]) == 6
        assert call("list_latest_quotes", {"query": {"limit": 1}})["structuredContent"]["has_more"]

    for engine in (monitor_engine, collector_engine):
        for statement in ["DELETE FROM price_quotes", "UPDATE tracking_runs SET payload_hash = repeat('0', 64)", "SELECT * FROM webhook_receipts"]:
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
            except Exception as error:
                assert getattr(error.orig, "sqlstate", None) == "42501", error
            else:
                raise AssertionError("Role exceeded its database grants")
        engine.dispose()
    admin.dispose()
    print("Monitoring checks passed: schedule, reuse, capacity, activation, immutability, temporal validation, hits, idempotency, expiry, calendar, cancellation, provider failures and webhook compatibility.")


if __name__ == "__main__":
    main()
