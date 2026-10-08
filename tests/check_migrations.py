from argparse import Namespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, inspect, select
from sqlalchemy.exc import IntegrityError

from stock_radar.db.config import database_url
from stock_radar.db.models import (
    Base,
    CollectionRun,
    Experiment,
    ExperimentVersion,
    Instrument,
    SignalObservation,
    Source,
    TrackingRun,
    TriggerEvent,
    TriggerLevel,
    WebhookReceipt,
)


def main() -> None:
    engine = create_engine(database_url())
    now = datetime.now(timezone.utc)

    def insert(model, **values):
        with engine.begin() as connection:
            result = connection.execute(model.__table__.insert().values(**values).returning(model.id)).scalar_one()
        assert result.version == 4
        return result

    def reject(model, expected_state, **values):
        try:
            insert(model, **values)
        except IntegrityError as error:
            assert error.orig.sqlstate == expected_state
        else:
            raise AssertionError(f"Invalid {model.__tablename__} row accepted")

    with TemporaryDirectory() as temporary:
        scripts = Path(temporary) / "migrations"
        shutil.copytree("/app/migrations", scripts)
        cfg = Config("/app/alembic.ini")
        cfg.set_main_option("script_location", str(scripts))
        command.upgrade(cfg, "head")
        command.check(cfg)
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        assert len(Base.metadata.tables) == 10
        for table in Base.metadata.tables:
            assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        before = set((scripts / "versions").glob("*.py"))
        cfg.cmd_opts = Namespace(autogenerate=True)
        command.revision(cfg, message="no changes", autogenerate=True)
        cfg.cmd_opts = None
        assert set((scripts / "versions").glob("*.py")) == before

        source = insert(Source, code="synthetic", name="Synthetic")
        other_source = insert(Source, code="another", name="Another")
        reject(Source, "23505", code="synthetic", name="Duplicate")
        instrument = insert(Instrument, exchange="TEST", symbol="SYN1", currency="BRL")
        reject(Instrument, "23505", exchange="TEST", symbol="SYN1", currency="BRL")
        collection_values = dict(
            client_collection_id=uuid4(), payload_hash="a" * 64, source_url="https://example.invalid",
            observed_at=now, market_session_date=now.date(), status="complete",
        )
        collection = insert(CollectionRun, source_id=source, **collection_values)
        reject(CollectionRun, "23505", source_id=source, **collection_values)
        other_collection = insert(CollectionRun, source_id=other_source, **collection_values)
        reject(CollectionRun, "23503", source_id=uuid4(), **collection_values)
        observation_values = dict(
            instrument_id=instrument, signal_kind="analyst_consensus", source_symbol="SYN1",
            original_rating="Synthetic Buy", normalized_rating="strong_buy", normalization_version="v1",
            observed_price=Decimal("12.34567891"), daily_change_percent=Decimal("-2.500000"),
            observed_at=now, parse_status="valid",
        )
        observation = insert(SignalObservation, collection_run_id=collection, **observation_values)
        insert(SignalObservation, collection_run_id=other_collection, **observation_values)
        reject(SignalObservation, "23505", collection_run_id=collection, **observation_values)
        invalid = observation_values | {"observed_price": Decimal("-1"), "signal_kind": "invalid_price"}
        reject(SignalObservation, "23514", collection_run_id=collection, **invalid)
        with engine.connect() as connection:
            assert connection.scalar(select(SignalObservation.observed_price).where(SignalObservation.id == observation)) == Decimal("12.34567891")
        experiment = insert(Experiment, code="rebound", name="Rebound")
        other_experiment = insert(Experiment, code="comparison", name="Comparison")
        version = insert(ExperimentVersion, experiment_id=experiment, version=1, analysis_kind="threshold_crossing", rules={"synthetic": True})
        other_version = insert(ExperimentVersion, experiment_id=other_experiment, version=1, analysis_kind="fixed_horizon", rules={"synthetic": True})
        reject(ExperimentVersion, "23505", experiment_id=experiment, version=1, analysis_kind="threshold_crossing", rules={})
        tracking_values = dict(
            client_tracking_id=uuid4(), payload_hash="b" * 64, signal_observation_id=observation,
            reference_price=Decimal("12.34567891"), reference_at=now, reference_source_id=source,
            reference_evidence={"synthetic": True}, expires_at=now + timedelta(days=5),
        )
        tracking = insert(TrackingRun, experiment_version_id=version, **tracking_values)
        insert(TrackingRun, experiment_version_id=other_version, **(tracking_values | {"client_tracking_id": uuid4()}))
        reject(TrackingRun, "23505", experiment_version_id=version, **tracking_values)
        reject(TrackingRun, "23514", experiment_version_id=version, **(tracking_values | {"client_tracking_id": uuid4(), "expires_at": now}))
        levels = []
        for percent in [-3, -2, -1, 1, 2, 3]:
            levels.append(insert(TriggerLevel, tracking_run_id=tracking, signed_percent=percent, mathematical_price=Decimal("12.34567891") * (1 + Decimal(percent) / 100)))
        reject(TriggerLevel, "23505", tracking_run_id=tracking, signed_percent=1, mathematical_price=13)
        reject(TriggerLevel, "23514", tracking_run_id=tracking, signed_percent=0, mathematical_price=13)
        receipt = insert(WebhookReceipt, source_id=source, deduplication_key="synthetic-delivery", sanitized_payload={})
        insert(WebhookReceipt, source_id=source, deduplication_key="unmapped-delivery", reported_alert_mapping_id=uuid4(), sanitized_payload={}, status="unmapped")
        reject(WebhookReceipt, "23505", source_id=source, deduplication_key="synthetic-delivery", sanitized_payload={})
        insert(TriggerEvent, trigger_level_id=levels[0], webhook_receipt_id=receipt, occurred_at=now, evidence_quality="timestamped")
        reject(TriggerEvent, "23505", trigger_level_id=levels[0], webhook_receipt_id=receipt)
        try:
            with engine.begin() as connection:
                connection.execute(delete(Source).where(Source.id == source))
        except IntegrityError as error:
            assert error.orig.sqlstate in {"23001", "23503"}
        else:
            raise AssertionError("Referenced source was deleted")
        command.upgrade(cfg, "head")
        command.check(cfg)
        command.downgrade(cfg, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        command.upgrade(cfg, "head")
        command.check(cfg)
    engine.dispose()
    print("Schema checks passed: UUIDs, relationships, uniqueness, checks, Decimal, upgrade and downgrade.")


if __name__ == "__main__":
    main()
