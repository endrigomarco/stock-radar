from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import subprocess
import sys
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from stock_radar.app import create_app
from stock_radar.db.config import database_url
from stock_radar.db.models import Experiment, ExperimentVersion, SignalObservation, Source, TrackingRun, TriggerEvent, TriggerLevel, WebhookReceipt
from stock_radar.services.webhooks import WebhookService
from stock_radar.settings import Settings


def recover() -> None:
    admin = create_engine(database_url())
    with Session(admin) as session:
        receipt = session.scalar(select(WebhookReceipt).where(WebhookReceipt.provider_event_id == "restart-recovery"))
        assert receipt.status == "pending"
    subprocess.run([sys.executable, "-m", "stock_radar.webhooks"], check=True)
    with Session(admin) as session:
        receipt = session.scalar(select(WebhookReceipt).where(WebhookReceipt.provider_event_id == "restart-recovery"))
        assert receipt.status == "processed" and receipt.processing_attempts == 1
    admin.dispose()
    print("Webhook pending receipt survived database restart and was recovered by the operator command.")


def main() -> None:
    settings = Settings.from_environment()
    admin = create_engine(database_url())
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)
    mapping = uuid4()
    with admin.begin() as connection:
        source_id = connection.scalar(select(Source.id).where(Source.code == "tradingview"))
        observation_id = connection.scalar(select(SignalObservation.id).limit(1))
        experiment_id = connection.scalar(Experiment.__table__.insert().values(code="webhook_test", name="Synthetic webhook experiment").returning(Experiment.id))
        version_id = connection.scalar(ExperimentVersion.__table__.insert().values(experiment_id=experiment_id, version=1, analysis_kind="threshold_crossing", rules={"synthetic": True}).returning(ExperimentVersion.id))
        run_id = connection.scalar(TrackingRun.__table__.insert().values(
            client_tracking_id=uuid4(), payload_hash="c" * 64, signal_observation_id=observation_id,
            experiment_version_id=version_id, reference_price=100, reference_at=start,
            reference_source_id=source_id, reference_evidence={"synthetic": True}, activated_at=start,
            expires_at=now + timedelta(hours=1), status="active",
        ).returning(TrackingRun.id))
        level_id = connection.scalar(TriggerLevel.__table__.insert().values(
            tracking_run_id=run_id, signed_percent=1, mathematical_price=101, configured_price=101,
            alert_mapping_id=mapping, alert_source_id=source_id, alert_active_at=start,
        ).returning(TriggerLevel.id))
    header = {"Authorization": "Bearer " + settings.webhook_token.get_secret_value()}
    reader = {"Authorization": "Bearer " + settings.reader_token.get_secret_value()}
    payload = {"schema_version": 1, "alert_mapping_id": str(mapping), "tracking_run_id": str(run_id), "signed_percent": "1", "source_event_at": now.isoformat(), "observed_price": "101"}
    with TestClient(create_app(settings)) as client:
        def send(body):
            return client.post("/webhooks/tradingview", json=body, headers=header)

        assert client.post("/webhooks/tradingview", json=payload).status_code == 401
        assert client.post("/webhooks/tradingview", json=payload, headers=reader).status_code == 401
        assert client.get("/v1/sources", headers=header).status_code == 401
        assert client.post("/webhooks/tradingview", content='{}', headers={**header, "Content-Type": "text/plain"}).status_code == 415
        for invalid in [dict(payload, signed_percent="0"), dict(payload, source_event_at=now.replace(tzinfo=None).isoformat()), dict(payload, source_event_at=(now + timedelta(minutes=6)).isoformat()), dict(payload, observed_price="NaN"), dict(payload, password="sensitive")]:
            response = send(invalid)
            assert response.status_code == 422, response.text
            assert "sensitive" not in response.text
        response = send(payload)
        assert response.status_code == 202, response.text
        receipt_id = response.json()["id"]
        assert response.json()["status"] == "pending"
        receipt = client.get("/v1/webhook-receipts/" + receipt_id, headers=reader).json()
        assert receipt["status"] == "processed" and receipt["processing_attempts"] == 1, receipt
        replay = send(dict(payload, signed_percent="1.000000", observed_price="101.00"))
        assert replay.status_code == 202 and replay.json()["id"] == receipt_id and replay.json()["duplicate"]
        assert replay.json()["processing_attempts"] == 1
        assert client.get("/v1/webhook-receipts/" + receipt_id).status_code == 401
        assert client.get("/v1/webhook-receipts/" + str(uuid4()), headers=reader).status_code == 404
        explicit = dict(payload, provider_event_id="provider-1")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: send(explicit), range(2)))
        assert all(result.status_code == 202 for result in results), [result.text for result in results]
        assert len({result.json()["id"] for result in results}) == 1
        assert sorted(result.json()["duplicate"] for result in results) == [False, True]
        assert send(dict(explicit, observed_price="102")).status_code == 409
        early = dict(payload, provider_event_id="late-arriving-earlier-event", source_event_at=(now - timedelta(minutes=5)).isoformat(), observed_price="101.5")
        earlier_id = send(early).json()["id"]
        with Session(admin) as session:
            events = session.scalars(select(TriggerEvent).where(TriggerEvent.trigger_level_id == level_id)).all()
            assert len(events) == 1 and events[0].webhook_receipt_id == UUID(earlier_id)
            assert events[0].observed_price == Decimal("101.5")
        with patch.object(WebhookService, "_finish", side_effect=SQLAlchemyError("synthetic rollback")):
            interrupted = send(dict(payload, provider_event_id="processing-rollback", source_event_at=(now - timedelta(minutes=10)).isoformat()))
            assert interrupted.status_code == 202
        with Session(admin) as session:
            assert session.get(WebhookReceipt, UUID(interrupted.json()["id"])).status == "pending"
            event = session.scalar(select(TriggerEvent).where(TriggerEvent.trigger_level_id == level_id))
            assert event.webhook_receipt_id == UUID(earlier_id)
        for key, body, expected in [
            ("wrong-run", dict(payload, tracking_run_id=str(uuid4())), "alert_mapping_mismatch"),
            ("wrong-threshold", dict(payload, signed_percent="2"), "alert_mapping_mismatch"),
            ("outside-window", dict(payload, source_event_at=(start - timedelta(seconds=1)).isoformat()), "event_outside_tracking_window"),
            ("wrong-price", dict(payload, observed_price="100"), "price_threshold_mismatch"),
        ]:
            result = send(dict(body, provider_event_id=key))
            assert result.status_code == 202
            receipt = client.get("/v1/webhook-receipts/" + result.json()["id"], headers=reader).json()
            assert receipt["status"] == "failed" and receipt["last_error_code"] == expected, receipt
        unknown_mapping = uuid4()
        unknown = dict(payload, alert_mapping_id=str(unknown_mapping), signed_percent="-1", observed_price="99")
        unknown_id = send(unknown).json()["id"]
        assert client.get("/v1/webhook-receipts/" + unknown_id, headers=reader).json()["status"] == "unmapped"
        with admin.begin() as connection:
            connection.execute(TriggerLevel.__table__.insert().values(tracking_run_id=run_id, signed_percent=-1, mathematical_price=99, alert_mapping_id=unknown_mapping, alert_source_id=source_id, alert_active_at=start))
        with Session(client.app.state.webhook_engine) as session:
            WebhookService(session).process(UUID(unknown_id))
        assert client.get("/v1/webhook-receipts/" + unknown_id, headers=reader).json()["status"] == "processed"
        with patch("stock_radar.controllers.webhooks.process_receipt"):
            pending = send(dict(payload, provider_event_id="restart-recovery"))
            assert pending.status_code == 202
        with Session(admin) as session:
            assert session.get(WebhookReceipt, UUID(pending.json()["id"])).status == "pending"
        assert client.post("/webhooks/tradingview", headers=header, content=b"x" * 1048577).status_code == 413
    bad = settings.model_copy(update={"database_name": "missing_synthetic_database"})
    with TestClient(create_app(bad)) as client:
        response = client.post("/webhooks/tradingview", headers=header, json=payload)
        assert response.status_code == 503 and response.json() == {"error": {"code": "database_unavailable"}}
    webhook_engine = create_engine(settings.webhook_database_url())
    for statement in ["DELETE FROM webhook_receipts", "UPDATE webhook_receipts SET sanitized_payload = '{}'", "UPDATE tracking_runs SET reference_price = 1", "INSERT INTO sources (code, name) VALUES ('forbidden_hook', 'Forbidden')"]:
        try:
            with webhook_engine.begin() as connection:
                connection.execute(text(statement))
        except DBAPIError as error:
            assert error.orig.sqlstate == "42501"
        else:
            raise AssertionError("Webhook role exceeded its grants")
    webhook_engine.dispose()
    admin.dispose()
    print("Webhook checks passed: authentication, validation, canonical retries, concurrency, conflicts, first-hit uniqueness, late events, quarantine and least privilege.")


if __name__ == "__main__":
    recover() if "--recover" in sys.argv else main()
