from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from stock_radar.app import create_app
from stock_radar.db.config import database_url
from stock_radar.db.models import CollectionRun, Instrument, PriceQuote, SignalObservation, Source, TrackingRun, TriggerEvent, TriggerLevel
from stock_radar.market_calendar import window_close
from stock_radar.services.reports import ReportService
from stock_radar.services.tracking import TrackingService
from stock_radar.settings import Settings
from stock_radar.viewmodels.reports import DailyReportQuery

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
EXCHANGE = "REPORT"
PERCENTS = [Decimal(value) for value in ("1", "2", "3", "-1", "-2", "-3")]
RECEIPT_DELAY = timedelta(minutes=5)
RECORDING_DELAY = timedelta(minutes=10)


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=SAO_PAULO).astimezone(timezone.utc)


class Scenario:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.version = TrackingService(session).current_version()
        self.tradingview = self._source("tradingview", "TradingView")
        self.brapi = self._source("brapi", "brapi")
        self.instruments: dict[str, Instrument] = {}

    def _source(self, code: str, name: str):
        self.session.execute(insert(Source).values(code=code, name=name).on_conflict_do_nothing(index_elements=[Source.code]))
        return self.session.scalar(select(Source.id).where(Source.code == code))

    def collection(self, day: date, received_at: datetime) -> CollectionRun:
        collection = CollectionRun(
            client_collection_id=uuid4(), source_id=self.tradingview, payload_hash=uuid4().hex + uuid4().hex,
            source_url="https://example.invalid/synthetic-report", observed_at=received_at, received_at=received_at,
            market_session_date=day, status="complete", rows_examined=40,
        )
        self.session.add(collection)
        self.session.flush()
        return collection

    def signal(self, collection: CollectionRun, symbol: str) -> SignalObservation:
        if symbol not in self.instruments:
            self.instruments[symbol] = Instrument(exchange=EXCHANGE, symbol=symbol, currency="BRL")
            self.session.add(self.instruments[symbol])
            self.session.flush()
        observation = SignalObservation(
            collection_run_id=collection.id, instrument_id=self.instruments[symbol].id, signal_kind="analyst_consensus",
            source_symbol=f"{EXCHANGE}:{symbol}", original_rating="Viés de alta forte", normalized_rating="strong_buy",
            normalization_version="tradingview-analyst-v1", observed_price=Decimal("10"), daily_change_percent=Decimal("-1"),
            observed_at=collection.received_at, parse_status="valid", created_at=collection.received_at,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def run(self, observation: SignalObservation, status: str, admitted_at: datetime | None = None, reference: tuple[str, datetime] | None = None, expires_at: datetime | None = None) -> TrackingRun:
        run = TrackingRun(
            client_tracking_id=uuid4(), payload_hash=uuid4().hex + uuid4().hex, signal_observation_id=observation.id,
            experiment_version_id=self.version.id, status=status, admitted_at=admitted_at, created_at=observation.created_at,
        )
        if reference is not None:
            price, reference_at = Decimal(reference[0]), reference[1]
            run.reference_price, run.reference_at, run.activated_at = price, reference_at, reference_at
            run.reference_source_id, run.reference_evidence = self.brapi, {"provider": "synthetic"}
            run.expires_at = expires_at or window_close(self.session, reference_at, 20)
            run.price_coverage = "partial"
        self.session.add(run)
        self.session.flush()
        if reference is not None:
            self.quote(observation.instrument_id, reference[1], reference[0])
            for percent in PERCENTS:
                self.session.add(TriggerLevel(tracking_run_id=run.id, signed_percent=percent, mathematical_price=run.reference_price * (1 + percent / 100)))
            self.session.flush()
        return run

    def quote(self, instrument_id, quoted_at: datetime, price: str) -> PriceQuote:
        quote = PriceQuote(instrument_id=instrument_id, source_id=self.brapi, price=Decimal(price), quoted_at=quoted_at, received_at=quoted_at + RECEIPT_DELAY)
        self.session.add(quote)
        self.session.flush()
        return quote

    def quotes(self, symbol: str, readings: list[tuple[datetime, str]]) -> None:
        for quoted_at, price in readings:
            self.quote(self.instruments[symbol].id, quoted_at, price)

    def hit(self, run: TrackingRun, percents: list[str], quoted_at: datetime, price: str, timed: bool = True) -> None:
        instrument_id = self.session.scalar(select(SignalObservation.instrument_id).where(SignalObservation.id == run.signal_observation_id))
        quote = self.session.scalar(select(PriceQuote).where(PriceQuote.instrument_id == instrument_id, PriceQuote.quoted_at == quoted_at))
        if quote is None:
            quote = self.quote(instrument_id, quoted_at, price)
        for percent in percents:
            level = self.session.scalar(select(TriggerLevel.id).where(TriggerLevel.tracking_run_id == run.id, TriggerLevel.signed_percent == Decimal(percent)))
            self.session.add(TriggerEvent(
                trigger_level_id=level, price_quote_id=quote.id, occurred_at=quoted_at if timed else None,
                observed_price=Decimal(price), evidence_quality="coarse" if timed else "unknown", created_at=quoted_at + RECORDING_DELAY,
            ))
        self.session.flush()


def build(session: Session) -> None:
    scenario = Scenario(session)
    earlier = scenario.collection(date(2026, 10, 1), at(1, 16, 25))
    main_group = scenario.collection(date(2026, 10, 5), at(5, 16, 25))
    later = scenario.collection(date(2026, 10, 6), at(6, 16, 25))
    admitted = at(5, 16, 40)

    first_j = scenario.run(scenario.signal(earlier, "RPTJ"), "completed", at(1, 16, 40), ("50", at(2, 10, 20)))
    scenario.hit(first_j, ["-1", "-2", "-3"], at(2, 11, 20), "48")
    scenario.hit(first_j, ["1", "2", "3"], at(2, 15, 20), "52")
    open_at_reuse = scenario.run(scenario.signal(earlier, "RPTK"), "expired", at(1, 16, 40), ("30", at(2, 10, 20)), at(9, 17))
    scenario.hit(open_at_reuse, ["-2"], at(2, 11, 20), "29.3")
    closed_before_reuse = scenario.run(scenario.signal(earlier, "RPTL"), "expired", at(1, 16, 40), ("40", at(2, 10, 20)), at(5, 17))
    scenario.hit(closed_before_reuse, ["2"], at(2, 11, 20), "40.9")

    a = scenario.run(scenario.signal(main_group, "RPTA"), "active", admitted, ("10", at(6, 10, 20)))
    scenario.quotes("RPTA", [(at(6, 16, 20), "10.05"), (at(7, 16, 20), "10.12"), (at(8, 16, 20), "10.09"), (at(9, 16, 20), "10.10"), (at(13, 16, 20), "10.16")])
    scenario.hit(a, ["1"], at(7, 11, 20), "10.11")
    b = scenario.run(scenario.signal(main_group, "RPTB"), "active", admitted, ("20", at(6, 10, 50)))
    scenario.quotes("RPTB", [(at(6, 16, 20), "19.95"), (at(8, 16, 20), "19.88"), (at(9, 16, 20), "19.90"), (at(13, 16, 20), "19.94")])
    scenario.hit(b, ["-1"], at(7, 16, 20), "19.74")
    c = scenario.run(scenario.signal(main_group, "RPTC"), "active", admitted, ("5", at(6, 10, 20)))
    scenario.quotes("RPTC", [(at(9, 16, 20), "5.03"), (at(13, 16, 20), "5.04")])
    scenario.hit(c, ["1"], at(7, 16, 20), "5.07")
    scenario.run(scenario.signal(main_group, "RPTD"), "active", admitted, ("8", at(6, 10, 20)))
    scenario.quotes("RPTD", [(at(7, 16, 20), "8.01"), (at(9, 16, 20), "8.02"), (at(13, 16, 20), "8.03")])
    scenario.run(scenario.signal(main_group, "RPTE"), "prepared")
    scenario.run(scenario.signal(main_group, "RPTF"), "prepared", admitted)
    cancelled = scenario.run(scenario.signal(main_group, "RPTG"), "cancelled", admitted, ("6", at(6, 10, 20)))
    scenario.hit(cancelled, ["1"], at(7, 11, 20), "6.07")
    early = scenario.run(scenario.signal(main_group, "RPTH"), "completed", admitted, ("4", at(6, 10, 20)))
    scenario.hit(early, ["1", "2", "3"], at(6, 14, 20), "4.13")
    scenario.hit(early, ["-1", "-2", "-3"], at(7, 11, 20), "3.87")
    untimed = scenario.run(scenario.signal(main_group, "RPTI"), "completed", admitted, ("7", at(6, 10, 20)))
    scenario.hit(untimed, ["1", "3"], at(6, 14, 20), "7.22")
    scenario.hit(untimed, ["2"], at(6, 14, 50), "7.23", timed=False)
    scenario.hit(untimed, ["-1", "-2", "-3"], at(7, 11, 20), "6.78")

    for symbol in ("RPTA", "RPTE", "RPTG", "RPTK", "RPTL"):
        scenario.signal(later, symbol)
    scenario.run(scenario.signal(later, "RPTJ"), "active", at(6, 16, 40), ("60", at(7, 10, 20)))
    scenario.quotes("RPTJ", [(at(7, 16, 20), "60.5"), (at(8, 16, 20), "61")])
    scenario.run(scenario.signal(later, "RPTM"), "active", at(6, 16, 40), ("70", at(8, 10, 20)))
    scenario.quotes("RPTM", [(at(8, 16, 20), "70.2"), (at(9, 16, 20), "70.4")])
    session.commit()


def rate(group: dict, sessions: int, block: str, percent: str) -> dict:
    horizon = next(item for item in group["horizons"] if item["sessions"] == sessions)
    return next(item for item in horizon[block]["targets"] if Decimal(item["signed_percent"]) == Decimal(percent))


def block(group: dict, sessions: int, name: str) -> dict:
    return next(item for item in group["horizons"] if item["sessions"] == sessions)[name]


def row(group: dict, symbol: str) -> dict:
    return next(item for item in group["items"] if item["symbol"] == symbol)


def milestone(group: dict, symbol: str, sessions: int) -> dict:
    return next(item for item in row(group, symbol)["milestones"] if item["sessions"] == sessions)


def check_closed_day(report) -> None:
    group = report(date(2026, 10, 5), at(13, 17, 10))
    totals = {key: group[key] for key in ("signals", "own_runs", "with_reference", "waiting_slot", "waiting_quote", "active", "completed", "cancelled", "expired", "reused_confirmed", "unconfirmed_links")}
    assert totals == {"signals": 9, "own_runs": 9, "with_reference": 7, "waiting_slot": 1, "waiting_quote": 1, "active": 4, "completed": 2, "cancelled": 1, "expired": 0, "reused_confirmed": 0, "unconfirmed_links": 0}, totals

    first = block(group, 1, "concluded")
    assert (first["runs"], first["eligible"], first["excluded_cancelled"], first["excluded_insufficient_coverage"], first["completed_early"]) == (7, 5, 1, 1, 0), first
    assert rate(group, 1, "concluded", "1") == {"signed_percent": "1", "hits": 3, "denominator": 5, "rate_percent": "60.0", "indeterminate": 0, "proven_hits_outside_sample": 2}
    assert (rate(group, 1, "concluded", "-1")["hits"], rate(group, 1, "concluded", "-1")["rate_percent"]) == (2, "40.0")
    assert block(group, 1, "partial")["runs"] == 0 and rate(group, 1, "partial", "1")["rate_percent"] is None

    second = block(group, 2, "concluded")
    assert (second["eligible"], second["excluded_insufficient_coverage"], second["excluded_cancelled"], second["completed_early"]) == (3, 3, 1, 1), second
    assert rate(group, 2, "concluded", "1") == {"signed_percent": "1", "hits": 2, "denominator": 3, "rate_percent": "66.7", "indeterminate": 0, "proven_hits_outside_sample": 3}
    assert (rate(group, 2, "concluded", "2")["hits"], rate(group, 2, "concluded", "2")["denominator"]) == (1, 3)

    for sessions in (5, 10, 19):
        future = next(item for item in group["horizons"] if item["sessions"] == sessions)
        assert (future["future_runs"], future["concluded"]["runs"], future["partial"]["runs"]) == (7, 0, 0), future
        assert all(target["denominator"] == 0 and target["rate_percent"] is None and target["proven_hits_outside_sample"] == 0 for block_name in ("concluded", "partial") for target in future[block_name]["targets"])
    assert next(item for item in group["horizons"] if item["sessions"] == 1)["future_runs"] == 0
    states = {item["sessions"]: (item["state"], item["window_end"]) for item in group["horizons"]}
    assert states[20] == ("out_of_window", False) and states[19] == ("measured", True) and states[10] == ("measured", False)

    assert row(group, "RPTA")["latest_quote"]["return_percent"] == "1.60" and row(group, "RPTA")["latest_quote"]["quoted_at"] != row(group, "RPTA")["latest_quote"]["received_at"]
    assert (milestone(group, "RPTA", 1)["state"], milestone(group, "RPTA", 1)["quote"]["return_percent"]) == ("final", "1.20")
    assert milestone(group, "RPTA", 2)["quote"]["return_percent"] == "0.90"
    assert (milestone(group, "RPTA", 5)["state"], milestone(group, "RPTA", 5)["session_date"]) == ("future", "2026-10-14")
    assert milestone(group, "RPTA", 19)["session_date"] == "2026-11-04" and milestone(group, "RPTA", 20)["state"] == "out_of_window"
    assert (milestone(group, "RPTC", 2)["state"], milestone(group, "RPTC", 2)["reason"], milestone(group, "RPTC", 2)["quote"]) == ("no_data", "no_quote_in_session", None)
    assert (milestone(group, "RPTG", 1)["state"], milestone(group, "RPTG", 1)["reason"]) == ("not_available", "cancelled_without_timestamp")
    assert (milestone(group, "RPTH", 1)["quote"]["return_percent"], milestone(group, "RPTH", 2)["reason"]) == ("-3.25", "run_completed")
    assert milestone(group, "RPTI", 1)["reason"] == "completion_time_unknown" and row(group, "RPTI")["latest_quote"] is None
    assert row(group, "RPTE")["pending_reason"] == "waiting_slot" and row(group, "RPTF")["pending_reason"] == "waiting_quote" and row(group, "RPTE")["milestones"] == []
    assert group["target_order"] == {"up_first": 1, "down_first": 0, "only_up": 0, "only_down": 0, "neither": 4, "indeterminate": 1, "not_assessed": 1}, group["target_order"]


def check_open_session(report) -> None:
    group = report(date(2026, 10, 5), at(7, 14))
    assert block(group, 1, "concluded")["runs"] == 0
    partial = block(group, 1, "partial")
    assert (partial["runs"], partial["eligible"], partial["excluded_cancelled"], partial["excluded_insufficient_coverage"], partial["completed_early"]) == (7, 2, 1, 4, 0), partial
    assert rate(group, 1, "partial", "1") == {"signed_percent": "1", "hits": 2, "denominator": 2, "rate_percent": "100.0", "indeterminate": 0, "proven_hits_outside_sample": 2}
    assert rate(group, 1, "partial", "-1") == {"signed_percent": "-1", "hits": 1, "denominator": 2, "rate_percent": "50.0", "indeterminate": 0, "proven_hits_outside_sample": 1}
    second = next(item for item in group["horizons"] if item["sessions"] == 2)
    assert (second["future_runs"], second["partial"]["runs"], second["concluded"]["runs"]) == (7, 0, 0) and rate(group, 2, "partial", "1")["rate_percent"] is None
    assert (milestone(group, "RPTA", 1)["state"], milestone(group, "RPTA", 1)["quote"]["return_percent"]) == ("in_progress", "1.10")
    assert milestone(group, "RPTA", 2)["state"] == "future" and row(group, "RPTA")["latest_quote"]["return_percent"] == "1.10"
    assert milestone(group, "RPTB", 1)["state"] == "in_progress" and milestone(group, "RPTB", 1)["quote"] is None

    before_quote = report(date(2026, 10, 5), at(8, 14))
    waiting = block(before_quote, 2, "partial")
    assert (waiting["runs"], waiting["eligible"], waiting["excluded_insufficient_coverage"], waiting["excluded_cancelled"], waiting["completed_early"]) == (7, 1, 5, 1, 1), waiting
    assert rate(before_quote, 2, "partial", "1") == {"signed_percent": "1", "hits": 1, "denominator": 1, "rate_percent": "100.0", "indeterminate": 0, "proven_hits_outside_sample": 4}
    assert rate(before_quote, 2, "partial", "-1")["proven_hits_outside_sample"] == 2 and rate(before_quote, 2, "partial", "2")["proven_hits_outside_sample"] == 0
    assert block(before_quote, 1, "concluded")["eligible"] == 5 and row(before_quote, "RPTA")["latest_quote"]["quoted_at"] == at(7, 16, 20).isoformat().replace("+00:00", "Z")

    after_quote = report(date(2026, 10, 5), at(8, 16, 30))
    included = block(after_quote, 2, "partial")
    assert (included["eligible"], included["excluded_insufficient_coverage"], included["completed_early"]) == (3, 3, 1), included
    assert rate(after_quote, 2, "partial", "1") == {"signed_percent": "1", "hits": 2, "denominator": 3, "rate_percent": "66.7", "indeterminate": 0, "proven_hits_outside_sample": 3}


def check_links_and_separation(report) -> None:
    later = report(date(2026, 10, 6), at(13, 17, 10))
    links = {item["symbol"]: (item["tracking_link"], item["origin_market_session_date"]) for item in later["items"]}
    assert links == {
        "RPTA": ("reused_confirmed", "2026-10-05"), "RPTK": ("reused_confirmed", "2026-10-01"), "RPTJ": ("own", "2026-10-06"), "RPTM": ("own", "2026-10-06"),
        "RPTE": ("unconfirmed", None), "RPTG": ("unconfirmed", None), "RPTL": ("unconfirmed", None),
    }, links
    assert (later["signals"], later["own_runs"], later["reused_confirmed"], later["unconfirmed_links"], later["with_reference"]) == (7, 2, 2, 3, 2)
    assert block(later, 1, "concluded")["runs"] == 2 and row(later, "RPTA")["milestones"] == [] and row(later, "RPTA")["reference_price"] is None

    mixed = report(date(2026, 10, 6), at(9, 14))
    first, second = (next(item for item in mixed["horizons"] if item["sessions"] == sessions) for sessions in (1, 2))
    assert (first["concluded"]["runs"], first["concluded"]["eligible"], first["partial"]["runs"], first["partial"]["excluded_insufficient_coverage"], first["future_runs"]) == (1, 1, 1, 1, 0), first
    assert (second["concluded"]["runs"], second["partial"]["runs"], second["partial"]["excluded_insufficient_coverage"], second["future_runs"]) == (0, 1, 1, 1), second
    assert (milestone(mixed, "RPTJ", 2)["state"], milestone(mixed, "RPTM", 1)["state"], milestone(mixed, "RPTM", 2)["state"]) == ("in_progress", "in_progress", "future")

    earlier = report(date(2026, 10, 1), at(13, 17, 10))
    first_run = row(earlier, "RPTJ")
    assert first_run["latest_quote"]["price"] == "52.00000000" and first_run["latest_quote"]["return_percent"] == "4.00"
    assert [(milestone(earlier, "RPTJ", sessions)["state"], milestone(earlier, "RPTJ", sessions)["reason"]) for sessions in (1, 2, 5)] == [("no_data", "run_completed")] * 3
    assert block(earlier, 5, "concluded")["completed_early"] == 1 and rate(earlier, 5, "concluded", "3")["hits"] == 1
    assert earlier["target_order"] == earlier["target_order"] | {"down_first": 1, "only_down": 1, "only_up": 1}, earlier["target_order"]
    assert row(later, "RPTJ")["latest_quote"]["price"] == "61.00000000" and row(later, "RPTJ")["reference_price"] == "60.00000000"


def check_pagination(service) -> None:
    full = service(DailyReportQuery(market_session_date=date(2026, 10, 5)), at(13, 17, 10))["items"][0]
    page = service(DailyReportQuery(market_session_date=date(2026, 10, 5), signal_limit=4), at(13, 17, 10))["items"][0]
    last = service(DailyReportQuery(market_session_date=date(2026, 10, 5), signal_limit=4, signal_offset=8), at(13, 17, 10))["items"][0]
    assert (len(page["items"]), page["signals_has_more"], len(last["items"]), last["signals_has_more"], full["signals_has_more"]) == (4, True, 1, False, False)
    for key in ("signals", "own_runs", "horizons", "target_order"):
        assert page[key] == full[key] == last[key], key
    dates = service(DailyReportQuery(limit=1), at(13, 17, 10))
    assert dates["has_more"] is True and len(dates["items"]) == 1 and dates["limit"] == 1
    listed = [item["market_session_date"] for item in service(DailyReportQuery(limit=30), at(13, 17, 10))["items"]]
    assert listed == sorted(listed, reverse=True) and {"2026-10-01", "2026-10-05", "2026-10-06"} <= set(listed)


def check_interfaces(settings: Settings, engine) -> None:
    reader = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}

    def stored() -> tuple:
        with Session(engine) as session:
            return tuple(session.scalar(select(func.count(model.id))) for model in (CollectionRun, SignalObservation, TrackingRun, TriggerEvent, PriceQuote))

    before = stored()
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        assert client.get("/v1/reports/daily").status_code == 401
        response = client.get("/v1/reports/daily", headers=reader, params={"market_session_date": "2026-10-05"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"][0]["signals"] == 9 and body["generated_at"] and "not complete coverage" in body["coverage_rule"]
        assert client.get("/v1/reports/daily", headers=reader, params={"signal_offset": 5}).status_code == 422
        assert client.get("/v1/reports/daily", headers=reader, params={"limit": 31}).status_code == 422
        call = client.post("/mcp", headers={**reader, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "daily_report", "arguments": {"query": {"market_session_date": "2026-10-05"}}}})
        result = call.json()["result"]
        assert result["isError"] is False and result["structuredContent"]["items"][0]["own_runs"] == 9, result
        assert "daily_report" in client.get("/v1/status", headers=reader).json()["capabilities"]
    assert stored() == before
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM trading_days")
    except DBAPIError as error:
        assert error.orig.sqlstate == "42501"
    else:
        raise AssertionError("Reader could change the trading calendar")


def main() -> None:
    settings = Settings.from_environment()
    admin = create_engine(database_url())
    reader_engine = create_engine(settings.database_url())
    with Session(admin) as session:
        build(session)

    def service(query: DailyReportQuery, now: datetime) -> dict:
        with Session(reader_engine) as session:
            return ReportService(session, now=now).daily(query).model_dump(mode="json")

    def report(day: date, now: datetime) -> dict:
        return service(DailyReportQuery(market_session_date=day), now)["items"][0]

    check_closed_day(report)
    check_open_session(report)
    check_links_and_separation(report)
    check_pagination(service)
    check_interfaces(settings, reader_engine)
    admin.dispose()
    reader_engine.dispose()
    print("Report checks passed: denominators, exclusions, partial blocks, early completion, cancellation, links, run separation, milestones, pagination and read-only access.")


if __name__ == "__main__":
    main()
