from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
import time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from stock_radar.app import create_app
from stock_radar.db.config import database_url
from stock_radar.db.models import CandidateDecision, CandidateSelection, CollectionRun, Experiment, ExperimentVersion, Instrument, SignalObservation, TrackingRun
from stock_radar.services.collections import CollectionService
from stock_radar.services.reports import ReportService
from stock_radar.services import selection as selection_module
from stock_radar.services.selection import SelectionService
from stock_radar.services.tracking import EXPERIMENT_CODE, TrackingService
from stock_radar.settings import Settings
from stock_radar.viewmodels.collections import CollectionInput
from stock_radar.viewmodels.reports import DailyReportQuery
from stock_radar.viewmodels.selection import CandidateQuery, SelectionInput

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
BASELINE_SCHEMA_2_HASH = "ecb4000462fc3807cfcd6e5aeca9a5805761fbc27116af1ae6ecf262c55313b8"
CRITERIA = "selection-v1"
EXCHANGE = "SEL"
LOCK_WAIT_SECONDS = 1.5


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SAO_PAULO).astimezone(timezone.utc)


def schema_2_hash_is_unchanged() -> None:
    payload = {
        "schema_version": 2, "client_collection_id": "00000000-0000-4000-8000-0000000000aa", "source_id": "00000000-0000-4000-8000-0000000000bb",
        "source_url": "https://example.invalid/synthetic-hash", "observed_at": "2026-09-15T14:00:00Z", "market_session_date": "2026-09-15",
        "status": "complete", "source_total": 2, "rows_examined": 2, "filters": {"list": "synthetic"},
        "observations": [{
            "exchange": "HASH", "symbol": "HASH3", "currency": "BRL", "source_symbol": "HASH:HASH3", "signal_kind": "analyst_consensus",
            "source_column": "Synthetic analyst column", "original_rating": "Viés de alta forte", "observed_price": "12.34",
            "daily_change_percent": "-2.5", "observed_at": "2026-09-15T14:00:00Z", "source_published_at": None, "raw_evidence": {"price_text": "12,34"},
        }],
    }
    assert CollectionService._transform_input(CollectionInput.model_validate(payload))[1] == BASELINE_SCHEMA_2_HASH
    with_volume = {**payload, "observations": [{**payload["observations"][0], "volume": "1000"}]}
    try:
        CollectionInput.model_validate(with_volume)
    except ValueError:
        pass
    else:
        raise AssertionError("Schema 2 accepted a schema 3 field")


class Harness:
    def __init__(self, client: TestClient, admin, reader: dict, collector: dict, source_id: str) -> None:
        self.client, self.admin, self.reader, self.collector, self.source_id = client, admin, reader, collector, source_id

    def row(self, symbol: str, observed_at: datetime, price: str | None = "10.00", volume: str | None = "100000", sector: str | None = "Energia", exchange: str = EXCHANGE) -> dict:
        values = {
            "exchange": exchange, "symbol": symbol, "currency": "BRL", "source_symbol": f"{exchange}:{symbol}", "signal_kind": "analyst_consensus",
            "original_rating": "Viés de alta forte", "observed_price": price, "daily_change_percent": "-2.5", "observed_at": observed_at.isoformat(),
        }
        if volume is not None:
            values["volume"] = volume
        if sector is not None:
            values["sector"] = sector
        return values

    def collect(self, day: date, rows: list[dict], observed_at: datetime | None = None, expected: int = 200, **changes) -> dict:
        observed = observed_at or local(day, 11)
        schema = 3 if any("volume" in item or "sector" in item for item in rows) else 2
        body = {
            "schema_version": schema, "client_collection_id": str(uuid4()), "source_id": self.source_id, "source_url": "https://example.invalid/synthetic-selection",
            "observed_at": observed.isoformat(), "market_session_date": day.isoformat(), "status": "complete", "source_total": 40, "rows_examined": 40,
            "observations": rows, **changes,
        }
        response = self.client.post("/v1/collections", headers=self.collector, json=body)
        assert response.status_code == expected, response.text
        return response.json()

    def candidates(self, day: date | None = None, expected: int = 200) -> dict:
        params = {"market_session_date": day.isoformat()} if day else {}
        response = self.client.get("/v1/selection/candidates", headers=self.reader, params=params)
        assert response.status_code == expected, response.text
        return response.json()

    @staticmethod
    def request(day: date, decisions: list[dict], **changes) -> dict:
        return {
            "client_selection_id": str(uuid4()), "market_session_date": day.isoformat(), "criteria_version": CRITERIA, "ranking_basis": "full",
            "summary": "Synthetic selection.", "plugin_version": "0.8.0", "decisions": decisions, **changes,
        }

    def confirm(self, body: dict, expected: int | None = 200, headers: dict | None = None):
        response = self.client.post("/v1/selections", headers=headers or self.collector, json=body)
        if expected is not None:
            assert response.status_code == expected, response.text
        return response

    def by_symbol(self, session_data: dict) -> dict[str, dict]:
        return {item["symbol"]: item for item in session_data["candidates"]}

    def runs_of(self, symbols: list[str]) -> int:
        with Session(self.admin) as session:
            return session.scalar(
                select(func.count(TrackingRun.id)).join(SignalObservation, SignalObservation.id == TrackingRun.signal_observation_id)
                .join(Instrument, Instrument.id == SignalObservation.instrument_id).where(Instrument.exchange == EXCHANGE, Instrument.symbol.in_(symbols))
            )


def legacy_version(session: Session) -> ExperimentVersion:
    return session.scalar(
        select(ExperimentVersion).join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
        .where(Experiment.code == EXPERIMENT_CODE, ExperimentVersion.version == 1)
    )


def decide(candidate: dict, outcome: str, rank: int | None = None, reason: str | None = None, **extra) -> dict:
    return {"decision_id": candidate["decision_id"], "outcome": outcome, "rank": rank, "reason_code": reason, "rationale": f"Synthetic {outcome} rationale.", **extra}


def dated_evidence(consulted_at: datetime) -> list[dict]:
    return [{
        "kind": "filing", "publisher": "Synthetic exchange notice", "url": "https://example.invalid/notice",
        "published_at": (consulted_at - timedelta(hours=1)).isoformat(), "consulted_at": consulted_at.isoformat(),
        "summary": "Synthetic notice used only by isolated checks.", "stance": "unfavorable",
    }]


def check_full_data(h: Harness, day: date) -> dict:
    receipt = h.collect(day, [h.row(f"SA{index}", local(day, 11), volume=str(1000 * index), sector="Energia" if index % 2 else "Bancos") for index in range(1, 9)])
    assert receipt["selection_policy"] == "assisted" and receipt["candidates_pending"] == 8 and receipt["selection_slots_remaining"] == 3, receipt
    assert h.runs_of([f"SA{index}" for index in range(1, 9)]) == 0
    listed = h.candidates(day)
    assert listed["liquidity_comparable"] and listed["baseline_rule"] == "estimated_turnover_then_tiebreak" and listed["slots_remaining"] == 3
    items = h.by_symbol(listed)
    assert items["SA8"]["baseline_rank"] == 1 and items["SA5"]["baseline_rank"] == 4 and items["SA8"]["estimated_turnover_at_observed_price"] == "80000.00000000"
    assert items["SA8"]["turnover_partial_session"] is True and items["SA8"]["outcome"] == "pending"
    order = ["SA8", "SA7", "SA5", "SA6", "SA4", "SA3", "SA2", "SA1"]
    decisions = [decide(items[symbol], "selected" if rank <= 3 else "not_selected", rank, None if rank <= 3 else "outranked") for rank, symbol in enumerate(order, start=1)]
    body = h.request(day, decisions)
    assert h.confirm(body, 403, h.reader).json()["detail"] == "Forbidden"
    assert h.confirm({**body, "criteria_version": "other"}, 409).json()["error"]["code"] == "criteria_version_mismatch"
    receipt = h.confirm(body).json()
    assert [(item["symbol"], item["slot"]) for item in receipt["selected"]] == [("SA8", 1), ("SA7", 2), ("SA5", 3)] and receipt["not_selected"] == 5, receipt
    assert receipt["late"] is True and receipt["slots_remaining"] == 0 and h.runs_of(order) == 3
    replay = h.confirm(body).json()
    assert replay["duplicate"] is True and {**replay, "duplicate": False} == receipt
    changed = {**body, "summary": "Changed content under the same identity."}
    assert h.confirm(changed, 409).json()["error"]["code"] == "selection_identity_conflict"
    with Session(h.admin) as session:
        selection = session.scalar(select(CandidateSelection).where(CandidateSelection.client_selection_id == UUID(body["client_selection_id"])))
        created = set(session.scalars(select(TrackingRun.created_at).where(TrackingRun.id.in_([UUID(item["tracking_run_id"]) for item in receipt["selected"]]))).all())
        assert created == {selection.decided_at}
        stored = {decision.rank: decision for decision in session.scalars(select(CandidateDecision).where(CandidateDecision.candidate_selection_id == selection.id)).all()}
        assert stored[3].baseline_rank == 4 and stored[4].reason_code == "outranked" and stored[1].details["ranking_basis"] == "full"
    return receipt


def check_missing_data(h: Harness, day: date) -> None:
    receipt = h.collect(day, [h.row(f"SB{index}", local(day, 11), volume=None, sector=None, price=None if index == 1 else "10.00") for index in range(1, 9)])
    assert receipt["candidates_pending"] == 8 and receipt["incomplete_count"] == 1
    listed = h.candidates(day)
    assert not listed["liquidity_comparable"] and listed["baseline_rule"] == "tiebreak_only"
    items = h.by_symbol(listed)
    assert sorted(item["baseline_rank"] for item in items.values()) == list(range(1, 9))
    assert items["SB1"]["turnover_unavailable_reason"] == "price_and_volume_missing" and items["SB2"]["turnover_unavailable_reason"] == "volume_missing"
    order = sorted(items, key=lambda symbol: items[symbol]["baseline_rank"])
    for selected in (0, 2):
        decisions = [decide(items[symbol], "selected" if rank <= selected else "not_selected", rank, None if rank <= selected else "outranked") for rank, symbol in enumerate(order, start=1)]
        response = h.confirm(h.request(day, decisions, no_selection_reason="Synthetic." if not selected else None), 409)
        assert response.json()["error"]["code"] == "selection_underfilled"
    decisions = [decide(items[symbol], "selected" if rank <= 3 else "not_selected", rank, None if rank <= 3 else "outranked") for rank, symbol in enumerate(order, start=1)]
    receipt = h.confirm(h.request(day, decisions, ranking_basis="limited")).json()
    assert len(receipt["selected"]) == 3 and receipt["not_selected"] == 5


def check_few_apt(h: Harness, day: date) -> None:
    h.collect(day, [h.row(symbol, local(day, 11)) for symbol in ("SC1", "SC2", "SC3", "SC4")])
    items = h.by_symbol(h.candidates(day))
    consulted = datetime.now(timezone.utc) - timedelta(minutes=1)
    halted = decide(items["SC3"], "not_selected", reason="trading_halted", evidence=dated_evidence(consulted))
    corporate = decide(items["SC4"], "not_selected", reason="price_comparison_invalid", evidence=dated_evidence(consulted), event_date=(day + timedelta(days=7)).isoformat())
    selected = [decide(items["SC1"], "selected", 1), decide(items["SC2"], "selected", 2)]
    undated = {**halted, "evidence": []}
    assert h.confirm(h.request(day, selected + [undated, corporate]), 422).json()["error"]["code"] == "invalid_request"
    assert h.confirm(h.request(day, selected + [halted, {**corporate, "event_date": None}]), 422).json()["error"]["code"] == "invalid_request"
    future = {**halted, "evidence": dated_evidence(datetime.now(timezone.utc) + timedelta(days=1))}
    assert h.confirm(h.request(day, selected + [future, corporate]), 422).json()["error"]["code"] == "evidence_after_decision"
    receipt = h.confirm(h.request(day, selected + [halted, corporate])).json()
    assert [item["symbol"] for item in receipt["selected"]] == ["SC1", "SC2"] and receipt["not_selected"] == 2 and receipt["slots_remaining"] == 1
    sc4 = h.by_symbol(h.candidates(day))["SC4"]
    assert sc4["details"]["event_date"] and "not known at decision time" in sc4["details"]["window_limitation"]


def check_already_tracked(h: Harness, day: date) -> None:
    receipt = h.collect(day, [h.row(symbol, local(day, 11)) for symbol in ("SA8", "SA7", "SD1", "SD2", "SD-3")])
    assert (receipt["candidates_already_tracked"], receipt["candidates_not_monitorable"], receipt["candidates_pending"]) == (2, 1, 2), receipt
    items = h.by_symbol(h.candidates(day))
    assert items["SA8"]["outcome"] == "already_tracked" and items["SA8"]["tracking_run_id"] and items["SD-3"]["reason_code"] == "not_monitorable"
    before = h.runs_of(["SA8", "SA7"])
    receipt = h.confirm(h.request(day, [decide(items["SD1"], "selected", 1), decide(items["SD2"], "selected", 2)])).json()
    assert [item["slot"] for item in receipt["selected"]] == [1, 2] and receipt["slots_remaining"] == 1
    assert h.runs_of(["SA8", "SA7"]) == before


def check_second_execution(h: Harness, day: date) -> None:
    h.collect(day, [h.row(symbol, local(day, 11)) for symbol in ("SE1", "SE2")])
    items = h.by_symbol(h.candidates(day))
    consulted = datetime.now(timezone.utc) - timedelta(minutes=1)
    h.confirm(h.request(day, [decide(items["SE1"], "selected", 1), decide(items["SE2"], "not_selected", reason="trading_halted", evidence=dated_evidence(consulted))]))
    receipt = h.collect(day, [h.row(symbol, local(day, 15)) for symbol in ("SE2", "SE3", "SE4", "SE5")], observed_at=local(day, 15))
    assert receipt["candidates_pending"] == 3 and receipt["selection_slots_remaining"] == 2, receipt
    listed = h.candidates(day)
    assert listed["liquidity_comparable"] and listed["pending"] == 3
    items = h.by_symbol(listed)
    partial = [decide(items["SE3"], "selected", 1), decide(items["SE4"], "selected", 2)]
    assert h.confirm(h.request(day, partial), 409).json()["error"]["code"] == "pending_set_changed"
    too_many = partial + [decide(items["SE5"], "selected", 3)]
    assert h.confirm(h.request(day, too_many), 409).json()["error"]["code"] == "selection_exceeds_slots"
    assert h.confirm(h.request(day, partial + [decide(items["SE1"], "selected", 3)]), 409).json()["error"]["code"] == "candidate_already_decided"
    receipt = h.confirm(h.request(day, partial + [decide(items["SE5"], "not_selected", 3, "outranked")])).json()
    assert [item["slot"] for item in receipt["selected"]] == [2, 3] and receipt["slots_remaining"] == 0
    capped = h.collect(day, [h.row("SE6", local(day, 16))], observed_at=local(day, 16))
    assert capped["candidates_cap_reached"] == 1 and capped["candidates_pending"] == 0 and capped["selection_slots_remaining"] == 0
    assert h.runs_of(["SE1", "SE2", "SE3", "SE4", "SE5", "SE6"]) == 3


def check_zero(h: Harness, halted_day: date, empty_day: date) -> None:
    h.collect(halted_day, [h.row(symbol, local(halted_day, 11)) for symbol in ("SF1", "SF2")])
    items = h.by_symbol(h.candidates(halted_day))
    consulted = datetime.now(timezone.utc) - timedelta(minutes=1)
    decisions = [decide(items[symbol], "not_selected", reason="trading_halted", evidence=dated_evidence(consulted)) for symbol in ("SF1", "SF2")]
    assert h.confirm(h.request(halted_day, decisions), 422).json()["error"]["code"] == "invalid_request"
    receipt = h.confirm(h.request(halted_day, decisions, no_selection_reason="Both candidates had a documented trading halt.")).json()
    assert receipt["selected"] == [] and receipt["not_selected"] == 2 and receipt["slots_remaining"] == 3
    empty = h.collect(empty_day, [])
    assert empty["selection_policy"] == "assisted" and empty["observation_count"] == 0
    listed = h.candidates(empty_day)
    assert listed["candidates"] == [] and listed["pending"] == 0 and listed["collections"][0]["status"] == "complete"
    assert h.candidates()["market_session_date"] >= empty_day.isoformat()


def check_race(h: Harness, day: date) -> None:
    h.collect(day, [h.row(symbol, local(day, 11)) for symbol in ("SG1", "SG2")])
    items = h.by_symbol(h.candidates(day))
    with Session(h.admin) as session, session.begin():
        observation = session.get(SignalObservation, UUID(items["SG1"]["signal_observation_id"]))
        version = legacy_version(session)
        assert TrackingService(session).attach(observation.id, observation.instrument_id, version)
    both = [decide(items["SG1"], "selected", 1), decide(items["SG2"], "selected", 2)]
    assert h.confirm(h.request(day, both), 409).json()["error"]["code"] == "candidate_already_tracked"
    listed = h.by_symbol(h.candidates(day))
    assert listed["SG1"]["outcome"] == "pending" and listed["SG1"]["open_tracking_run_id"] and listed["SG2"]["outcome"] == "pending"
    wrong = [decide(items["SG1"], "already_tracked"), decide(items["SG2"], "already_tracked")]
    assert h.confirm(h.request(day, wrong, no_selection_reason="Synthetic claim."), 409).json()["error"]["code"] == "already_tracked_not_confirmed"
    receipt = h.confirm(h.request(day, [decide(items["SG1"], "already_tracked"), decide(items["SG2"], "selected", 1)])).json()
    assert [item["symbol"] for item in receipt["selected"]] == ["SG2"] and receipt["already_tracked"] == 1 and receipt["slots_remaining"] == 2
    assert h.by_symbol(h.candidates(day))["SG1"]["tracking_run_id"] == listed["SG1"]["open_tracking_run_id"]


def check_concurrency(h: Harness, day: date) -> None:
    h.collect(day, [h.row(symbol, local(day, 11)) for symbol in ("SH1", "SH2", "SH3", "SH4")])
    items = h.by_symbol(h.candidates(day))
    first = [decide(items[symbol], "selected" if rank <= 3 else "not_selected", rank, None if rank <= 3 else "outranked") for rank, symbol in enumerate(("SH1", "SH2", "SH3", "SH4"), start=1)]
    second = [decide(items[symbol], "selected" if rank <= 3 else "not_selected", rank, None if rank <= 3 else "outranked") for rank, symbol in enumerate(("SH4", "SH3", "SH2", "SH1"), start=1)]
    barrier = Barrier(2)

    def submit(decisions: list[dict]):
        barrier.wait(timeout=10)
        return h.confirm(h.request(day, decisions), expected=None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, (first, second)))
    assert sorted(item.status_code for item in responses) == [200, 409], [item.text for item in responses]
    assert h.runs_of(["SH1", "SH2", "SH3", "SH4"]) == 3 and h.candidates(day)["slots_remaining"] == 0


def check_consistent_read(h: Harness, reader_engine, day: date) -> None:
    symbols = ("SL1", "SL2", "SL3", "SL4")
    h.collect(day, [h.row(symbol, local(day, 11)) for symbol in symbols])
    items = h.by_symbol(h.candidates(day))
    decisions = [decide(items[symbol], "selected" if rank <= 3 else "not_selected", rank, None if rank <= 3 else "outranked") for rank, symbol in enumerate(symbols, start=1)]
    original = selection_module.baseline_order

    def interleaved(*args, **kwargs):
        selection_module.baseline_order = original
        h.confirm(h.request(day, decisions))
        h.collect(day, [h.row("SL5", local(day, 15))], observed_at=local(day, 15))
        return original(*args, **kwargs)

    selection_module.baseline_order = interleaved
    try:
        with Session(reader_engine) as session:
            snapshot = SelectionService(session).candidates(CandidateQuery(market_session_date=day))
    finally:
        selection_module.baseline_order = original
    outcomes = {item.symbol: item.outcome for item in snapshot.candidates}
    assert outcomes == dict.fromkeys(symbols, "pending"), outcomes
    assert snapshot.pending == 4 and snapshot.slots_used == 0 and snapshot.slots_remaining == 3, snapshot
    assert all(item.open_tracking_run_id is None and item.tracking_run_id is None for item in snapshot.candidates)
    assert len(snapshot.collections) == 1 and {item.collection_id for item in snapshot.candidates} == {snapshot.collections[0].id}
    current = h.candidates(day)
    assert current["pending"] == 0 and current["slots_remaining"] == 0 and len(current["collections"]) == 2
    assert h.by_symbol(current)["SL5"]["reason_code"] == "daily_cap_reached"
    stale = h.request(day, decisions)
    assert h.confirm(stale, 409).json()["error"]["code"] == "nothing_pending"


def check_reference_after_lock_wait(h: Harness, day: date) -> None:
    h.collect(day, [h.row("SI1", local(day, 11))])
    candidate = h.by_symbol(h.candidates(day))["SI1"]
    with h.admin.connect() as holder:
        key = {"key": f"stock_radar:selection:{day.isoformat()}"}
        holder.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), key)
        before = holder.scalar(select(func.clock_timestamp()))
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(h.confirm, h.request(day, [decide(candidate, "selected", 1)]))
            time.sleep(LOCK_WAIT_SECONDS)
            holder.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), key)
            receipt = pending.result().json()
    decided_at = datetime.fromisoformat(receipt["decided_at"])
    assert decided_at - before >= timedelta(seconds=LOCK_WAIT_SECONDS - 0.1), (before, decided_at)
    run_id = UUID(receipt["selected"][0]["tracking_run_id"])
    with Session(h.admin) as session:
        run = session.get(TrackingRun, run_id)
        assert run.created_at == decided_at
        instrument_id = session.get(SignalObservation, run.signal_observation_id).instrument_id
    with Session(h.admin) as session:
        source_id = TrackingService(session).ensure_quote_source()
    with Session(h.admin) as session:
        TrackingService(session).admit(200, datetime.now(timezone.utc))
    received = datetime.now(timezone.utc) + timedelta(seconds=5)
    with Session(h.admin) as session:
        TrackingService(session).apply_quote(instrument_id, source_id, Decimal("10"), before + timedelta(seconds=0.5), received)
    with Session(h.admin) as session:
        waiting = session.get(TrackingRun, run_id)
        assert waiting.status == "prepared" and waiting.reference_price is None
    with Session(h.admin) as session:
        TrackingService(session).apply_quote(instrument_id, source_id, Decimal("10.5"), decided_at + timedelta(seconds=1), received + timedelta(seconds=1))
    with Session(h.admin) as session:
        active = session.get(TrackingRun, run_id)
        assert active.status == "active" and active.reference_at == decided_at + timedelta(seconds=1) and active.reference_price == Decimal("10.5")


def check_legacy_reference(h: Harness, day: date) -> None:
    observed = local(day, 11)
    with Session(h.admin) as session, session.begin():
        collection = CollectionRun(
            client_collection_id=uuid4(), source_id=UUID(h.source_id), payload_hash="a" * 64, source_url="https://example.invalid/legacy",
            observed_at=observed, received_at=observed, market_session_date=day, status="complete", rows_examined=1,
        )
        instrument = Instrument(exchange=EXCHANGE, symbol="LEG1", currency="BRL")
        session.add_all([collection, instrument])
        session.flush()
        observation = SignalObservation(
            collection_run_id=collection.id, instrument_id=instrument.id, signal_kind="analyst_consensus", source_symbol="SEL:LEG1",
            original_rating="Viés de alta forte", normalized_rating="strong_buy", normalization_version="tradingview-analyst-v1",
            observed_price=Decimal("10"), daily_change_percent=Decimal("-1"), observed_at=observed, parse_status="valid",
        )
        session.add(observation)
        session.flush()
        version = legacy_version(session)
        assert TrackingService(session).attach(observation.id, instrument.id, version)
        run = session.scalar(select(TrackingRun).where(TrackingRun.signal_observation_id == observation.id))
        run_id, instrument_id, created_at = run.id, instrument.id, run.created_at
    with Session(h.admin) as session:
        source_id = TrackingService(session).ensure_quote_source()
    with Session(h.admin) as session:
        TrackingService(session).admit(200, datetime.now(timezone.utc))
    quoted_at = created_at - timedelta(minutes=5)
    with Session(h.admin) as session:
        TrackingService(session).apply_quote(instrument_id, source_id, Decimal("10"), quoted_at, datetime.now(timezone.utc) + timedelta(seconds=5))
    with Session(h.admin) as session:
        legacy = session.get(TrackingRun, run_id)
        assert legacy.status == "active" and legacy.reference_at == quoted_at


def check_on_time_and_reports(h: Harness, day: date, late_day: date, second_day: date) -> None:
    h.collect(day, [h.row("SJ1", local(day, 11))])
    candidate = h.by_symbol(h.candidates(day))["SJ1"]
    decided_at = local(day, 12)
    request = SelectionInput.model_validate(h.request(day, [decide(candidate, "selected", 1)]))
    with Session(h.admin) as session:
        receipt = SelectionService(session, clock=lambda: decided_at).confirm(request)
    assert receipt.late is False and receipt.decided_at == decided_at
    run_id = receipt.selected[0].tracking_run_id
    with Session(h.admin) as session:
        source_id = TrackingService(session).ensure_quote_source()
        instrument_id = session.scalar(select(SignalObservation.instrument_id).join(TrackingRun, TrackingRun.signal_observation_id == SignalObservation.id).where(TrackingRun.id == run_id))
    with Session(h.admin) as session:
        TrackingService(session).admit(200, local(day, 12, 10))
    with Session(h.admin) as session:
        TrackingService(session).apply_quote(instrument_id, source_id, Decimal("10"), local(day, 12, 30), local(day, 12, 31))

    def report(session_day: date, now: datetime) -> dict:
        with Session(h.admin) as session:
            return ReportService(session, now=now).daily(DailyReportQuery(market_session_date=session_day)).model_dump(mode="json")["items"][0]

    on_time = report(day, local(day + timedelta(days=3), 17, 30))
    assert on_time["selection_policy"] == "assisted" and on_time["selection"]["selected_on_time"] == 1 and on_time["late_horizons"] == []
    assert next(item for item in on_time["horizons"] if item["sessions"] == 1)["concluded"]["runs"] == 1
    row = on_time["items"][0]
    assert row["selection_outcome"] == "selected" and row["selected_at"] and row["reference_at"] and row["observed_at"] and row["selection_late"] is False

    late = report(late_day, datetime.now(timezone.utc))
    summary = late["selection"]
    assert (summary["selected"], summary["selected_late"], summary["selected_on_time"], summary["not_selected"]) == (3, 3, 0, {"outranked": 5}), summary
    assert len(late["late_horizons"]) == len(late["horizons"]) and late["own_runs"] == 3 and late["signals"] == 8
    assert {item["tracking_link"] for item in late["items"]} == {"own", "not_selected"} and all(item["selection_late"] for item in late["items"])

    second = report(second_day, datetime.now(timezone.utc))
    summary = second["selection"]
    assert (summary["candidates"], summary["eligible_observations"], summary["selected"], len(summary["selections"])) == (6, 7, 3, 2), summary
    assert summary["not_selected"] == {"trading_halted": 1, "outranked": 1, "daily_cap_reached": 1} and summary["collection_statuses"] == {"complete": 3}


def check_transition(h: Harness, day: date) -> None:
    with Session(h.admin) as session, session.begin():
        earlier = datetime.now(timezone.utc) - timedelta(days=1)
        session.add(CollectionRun(
            client_collection_id=uuid4(), source_id=UUID(h.source_id), payload_hash="b" * 64, source_url="https://example.invalid/pre-migration",
            observed_at=local(day, 11), received_at=earlier, market_session_date=day, status="complete", rows_examined=0,
        ))
    receipt = h.collect(day, [h.row("TR1", local(day, 9))], observed_at=local(day, 9))
    assert receipt["selection_policy"] == "automatic" and receipt["experiment_version"] == 1 and receipt["candidates_pending"] == 0, receipt
    assert h.runs_of(["TR1"]) == 1
    assert h.candidates(day, 409)["error"]["code"] == "session_not_assisted"


def check_session_date(h: Harness, day: date) -> None:
    mismatch = h.collect(day, [h.row("SK1", local(day, 9))], observed_at=local(day, 9), expected=422)
    assert mismatch["error"]["code"] == "market_session_date_mismatch"
    future = date(2028, 6, 14)
    assert h.collect(future, [h.row("SK2", local(future, 11))], expected=422)["error"]["code"] == "collection_observed_in_future"


def check_permissions(collector_engine, reader_engine) -> None:
    for engine, statement in (
        (collector_engine, "UPDATE candidate_decisions SET experiment_version_id = experiment_version_id"),
        (collector_engine, "DELETE FROM candidate_decisions"),
        (collector_engine, "UPDATE candidate_selections SET summary = summary"),
        (reader_engine, "UPDATE candidate_decisions SET outcome = outcome"),
    ):
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except DBAPIError as error:
            assert error.orig.sqlstate == "42501", error
        else:
            raise AssertionError(f"Role exceeded its grants: {statement}")


def cleanup(admin) -> None:
    with admin.begin() as connection:
        connection.execute(text(
            "UPDATE tracking_runs SET status = 'cancelled' WHERE status IN ('prepared', 'active') AND signal_observation_id IN "
            "(SELECT signal_observations.id FROM signal_observations JOIN instruments ON instruments.id = signal_observations.instrument_id WHERE instruments.exchange = :exchange)"
        ), {"exchange": EXCHANGE})


def main() -> None:
    schema_2_hash_is_unchanged()
    settings = Settings.from_environment()
    admin = create_engine(database_url())
    collector_engine = create_engine(settings.database_url(write=True))
    reader_engine = create_engine(settings.database_url())
    reader = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}
    collector = {"Authorization": f"Bearer {settings.collector_token.get_secret_value()}"}
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        source = client.post("/v1/sources", headers=collector, json={"code": "tradingview", "name": "TradingView"}).json()
        h = Harness(client, admin, reader, collector, source["id"])
        mcp = client.post("/mcp", headers={**reader, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_selection_candidates", "arguments": {"query": {"market_session_date": "2026-09-14"}}}})
        assert mcp.json()["result"]["isError"] and "selection_session_not_found" in mcp.text
        check_full_data(h, date(2026, 9, 14))
        check_missing_data(h, date(2026, 9, 15))
        check_few_apt(h, date(2026, 9, 16))
        check_already_tracked(h, date(2026, 9, 17))
        check_second_execution(h, date(2026, 9, 18))
        check_zero(h, date(2026, 9, 21), date(2026, 9, 22))
        check_race(h, date(2026, 9, 23))
        check_concurrency(h, date(2026, 9, 24))
        check_consistent_read(h, reader_engine, date(2026, 9, 11))
        check_reference_after_lock_wait(h, date(2026, 9, 25))
        check_legacy_reference(h, date(2026, 9, 28))
        check_on_time_and_reports(h, date(2026, 9, 29), date(2026, 9, 14), date(2026, 9, 18))
        check_transition(h, date(2026, 9, 30))
        check_session_date(h, date(2026, 9, 14))
        listed = client.post("/mcp", headers={**reader, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_selection_candidates", "arguments": {"query": {"market_session_date": "2026-09-14"}}}})
        assert listed.json()["result"]["structuredContent"]["slots_used"] == 3
        assert "candidate_selection" in client.get("/v1/status", headers=reader).json()["capabilities"]
    check_permissions(collector_engine, reader_engine)
    cleanup(admin)
    for engine in (admin, collector_engine, reader_engine):
        engine.dispose()
    print("Selection checks passed: registration without tracking, missing data, zero to three selections, daily cap, second execution, concurrency, consistent candidate reads, retries, recovery, existing runs, reference after decision, late and on-time reports, transition, schema 2 hash and grants.")


if __name__ == "__main__":
    main()
