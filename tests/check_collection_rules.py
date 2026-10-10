from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from stock_radar.app import create_app
from stock_radar.db import prune_collection
from stock_radar.db.models import CollectionRun, Instrument, SignalObservation, TrackingRun
from stock_radar.services.tracking import TrackingService
from stock_radar.settings import Settings

ROWS_ON_PAGE = 4


def legacy_collection(session: Session, source_id: str, prefix: str, rows: list[dict], tracked: set[str]) -> str:
    collection = CollectionRun(
        client_collection_id=uuid4(), source_id=source_id, payload_hash=uuid4().hex + uuid4().hex,
        source_url="https://example.invalid/synthetic-legacy", observed_at=datetime.now(timezone.utc),
        market_session_date=date(2026, 1, 5), status="complete", source_total=len(rows),
    )
    session.add(collection)
    session.flush()
    tracking = TrackingService(session)
    version = tracking.current_version()
    assert version is not None
    for index, row in enumerate(rows, start=1):
        symbol = f"{prefix}{index}"
        instrument = Instrument(exchange="LEGACY", symbol=symbol, currency="BRL")
        session.add(instrument)
        session.flush()
        observation = SignalObservation(
            collection_run_id=collection.id, instrument_id=instrument.id, source_symbol=f"LEGACY:{symbol}",
            normalization_version="tradingview-analyst-v1", observed_at=collection.observed_at,
            parse_status="valid", observed_price="10", **row,
        )
        session.add(observation)
        session.flush()
        if symbol in tracked:
            assert tracking.attach(observation.id, instrument.id, version)
    session.commit()
    return str(collection.id)


def main() -> None:
    settings = Settings.from_environment()
    reader = {"Authorization": f"Bearer {settings.reader_token.get_secret_value()}"}
    collector = {"Authorization": f"Bearer {settings.collector_token.get_secret_value()}"}
    engine = create_engine(settings.database_url(write=True))

    def stored(model, *conditions) -> int:
        with Session(engine) as session:
            return session.scalar(select(func.count(model.id)).where(*conditions))

    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        source = client.post("/v1/sources", headers=collector, json={"code": "tradingview", "name": "TradingView"}).json()
        now = datetime.now(timezone.utc).isoformat()

        def row(symbol: str, **changes) -> dict:
            base = {"exchange": "RULES", "symbol": symbol, "currency": "BRL", "source_symbol": f"RULES:{symbol}", "signal_kind": "analyst_consensus", "source_column": "Synthetic analyst column", "original_rating": "Viés de alta forte", "observed_price": "12.34", "daily_change_percent": "-2.5", "observed_at": now}
            return {**base, **changes}

        def payload(observations: list[dict], **changes) -> dict:
            base = {"schema_version": 2, "client_collection_id": str(uuid4()), "source_id": source["id"], "source_url": "https://example.invalid/synthetic-rules", "observed_at": now, "market_session_date": now[:10], "status": "complete", "source_total": ROWS_ON_PAGE, "rows_examined": ROWS_ON_PAGE, "observations": observations}
            return {**base, **changes}

        def post(body: dict):
            return client.post("/v1/collections", headers=collector, json=body)

        qualified = row("QUAL1")
        unqualified = [
            row("OTHER1", original_rating="Viés de alta"),
            row("OTHER1", original_rating="Neutral"),
            row("OTHER1", original_rating=None),
            row("OTHER1", signal_kind="technical_rating", source_column="Synthetic technical column"),
            row("OTHER1", daily_change_percent="0"),
            row("OTHER1", daily_change_percent="1.25"),
            row("OTHER1", daily_change_percent=None),
        ]
        for rejected in unqualified:
            for observations in ([qualified, rejected], [rejected]):
                body = payload(observations)
                response = post(body)
                assert response.status_code == 422 and response.json()["error"]["code"] == "observation_not_eligible", response.text
                assert stored(CollectionRun, CollectionRun.client_collection_id == body["client_collection_id"]) == 0
        assert stored(Instrument, Instrument.exchange == "RULES") == 0

        body = payload([qualified, row("QUAL2", original_rating="Strong Buy", observed_price=None)])
        response = post(body)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["observation_count"] == 2 and receipt["eligible_count"] == 2 and receipt["incomplete_count"] == 1, receipt
        assert receipt["rows_examined"] == ROWS_ON_PAGE and receipt["source_total"] == ROWS_ON_PAGE and receipt["duplicate"] is False
        replay = post(body).json()
        assert replay["duplicate"] is True and {**replay, "duplicate": False} == receipt, replay
        assert client.get("/v1/collections/" + receipt["id"], headers=reader).json() == receipt
        assert stored(SignalObservation, SignalObservation.collection_run_id == receipt["id"]) == 2
        assert stored(TrackingRun, TrackingRun.signal_observation_id.in_(select(SignalObservation.id).where(SignalObservation.collection_run_id == receipt["id"]))) == 2
        assert post({**body, "rows_examined": 3, "status": "partial"}).status_code == 409
        signals = client.get("/v1/signals", headers=reader, params={"collection_id": receipt["id"]}).json()["items"]
        assert {item["original_rating"] for item in signals} == {"Viés de alta forte", "Strong Buy"} and all(item["eligible"] for item in signals)

        empty = payload([])
        response = post(empty)
        assert response.status_code == 200, response.text
        empty_receipt = response.json()
        assert empty_receipt["status"] == "complete" and empty_receipt["observation_count"] == 0 and empty_receipt["eligible_count"] == 0
        assert empty_receipt["rows_examined"] == ROWS_ON_PAGE and post(empty).json()["duplicate"] is True

        assert post(payload([], status="failed", rows_examined=0, source_total=None)).status_code == 200
        assert post(payload([row("QUAL3")], status="partial", rows_examined=3)).status_code == 200
        for invalid in (
            payload([row("QUAL4")], rows_examined=0, source_total=None),
            payload([row("QUAL4")], rows_examined=3),
            payload([row("QUAL4")], schema_version=1),
            {key: value for key, value in payload([row("QUAL4")]).items() if key != "rows_examined"},
            {key: value for key, value in payload([row("QUAL4")]).items() if key != "schema_version"},
        ):
            response = post(invalid)
            assert response.status_code == 422 and response.json()["error"]["code"] != "observation_not_eligible", response.text
        assert stored(Instrument, Instrument.exchange == "RULES", Instrument.symbol == "QUAL4") == 0

        mixed = [
            {"signal_kind": "analyst_consensus", "original_rating": "Viés de alta forte", "normalized_rating": "strong_buy", "daily_change_percent": "-1"},
            {"signal_kind": "analyst_consensus", "original_rating": "Strong Buy", "normalized_rating": "strong_buy", "daily_change_percent": "-3"},
            {"signal_kind": "analyst_consensus", "original_rating": "Viés de alta", "normalized_rating": None, "daily_change_percent": "-1"},
            {"signal_kind": "technical_rating", "original_rating": "Viés de alta forte", "normalized_rating": None, "daily_change_percent": "-2"},
            {"signal_kind": "analyst_consensus", "original_rating": "Viés de alta forte", "normalized_rating": "strong_buy", "daily_change_percent": "1"},
        ]
        with Session(engine) as session:
            target = legacy_collection(session, source["id"], "KEEP", mixed, {"KEEP1"})
            untouched = legacy_collection(session, source["id"], "ELSE", mixed[2:4], set())
            blocked = legacy_collection(session, source["id"], "LOCK", [mixed[0], mixed[2]], {"LOCK2"})

        def run(collection_id: str, total: int, eligible: int, symbols: str, *flags: str) -> int:
            return prune_collection.main(["--collection-id", collection_id, "--expected-total", str(total), "--expected-eligible", str(eligible), "--expected-symbols", symbols, *flags])

        def observations_of(collection_id: str) -> int:
            return stored(SignalObservation, SignalObservation.collection_run_id == collection_id)

        assert run(target, 5, 2, "KEEP1,KEEP2") == 0 and observations_of(target) == 5
        assert run(target, 4, 2, "KEEP1,KEEP2", "--apply") == 1
        assert run(target, 5, 3, "KEEP1,KEEP2", "--apply") == 1
        assert run(target, 5, 2, "KEEP1,KEEP3", "--apply") == 1
        assert run(str(uuid4()), 5, 2, "KEEP1,KEEP2", "--apply") == 1
        assert run(blocked, 2, 1, "LOCK1", "--apply") == 1 and observations_of(blocked) == 2
        assert run(receipt["id"], 2, 2, "QUAL1,QUAL2", "--apply") == 1 and observations_of(receipt["id"]) == 2
        assert observations_of(target) == 5

        assert run(target, 5, 2, "KEEP1,KEEP2", "--apply") == 0
        pruned = client.get("/v1/collections/" + target, headers=reader).json()
        assert pruned["observation_count"] == 2 and pruned["eligible_count"] == 2 and pruned["rows_examined"] == 5 and pruned["source_total"] == 5, pruned
        kept = client.get("/v1/signals", headers=reader, params={"collection_id": target}).json()["items"]
        assert sorted(item["source_symbol"] for item in kept) == ["LEGACY:KEEP1", "LEGACY:KEEP2"]
        assert stored(TrackingRun, TrackingRun.signal_observation_id.in_(select(SignalObservation.id).where(SignalObservation.collection_run_id == target))) == 1
        assert stored(Instrument, Instrument.exchange == "LEGACY", Instrument.symbol.like("KEEP%")) == 5
        assert observations_of(untouched) == 2 and observations_of(blocked) == 2
        assert run(target, 5, 2, "KEEP1,KEEP2", "--apply") == 1 and observations_of(target) == 2
    engine.dispose()
    print("Collection rule checks passed: eligibility guard, analyst versus technical, negative change, empty complete collection, idempotency and restricted pruning.")


if __name__ == "__main__":
    main()
