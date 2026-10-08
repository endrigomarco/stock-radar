import argparse
import os

from stock_radar.observability.logging import configure_logging, request_id
from stock_radar.observability.telemetry import Telemetry, correlation_id

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from stock_radar.db.models import WebhookReceipt
from stock_radar.services.webhooks import process_receipt
from stock_radar.settings import Settings


def run(telemetry: Telemetry) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("limit must be between 1 and 1000")
    settings = Settings.from_environment()
    engine = create_engine(settings.webhook_database_url(), hide_parameters=True, connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"})
    try:
        with Session(engine) as session:
            ids = session.scalars(select(WebhookReceipt.id).where(WebhookReceipt.status.in_(["pending", "unmapped", "failed"])).order_by(WebhookReceipt.processed_at.asc().nullsfirst(), WebhookReceipt.received_at, WebhookReceipt.id).limit(args.limit)).all()
        deferred = 0
        for receipt_id in ids:
            if not process_receipt(engine, receipt_id, telemetry):
                deferred += 1
        print(f"Attempted recovery of {len(ids)} webhook receipts; {deferred} processing failures.")
        if deferred:
            raise SystemExit(1)
    finally:
        engine.dispose()


def main() -> None:
    configure_logging(os.environ.get("LOG_DIRECTORY"))
    telemetry = Telemetry()
    token = request_id.set(correlation_id())
    try:
        run(telemetry)
    except Exception as error:
        identity = telemetry.error(error, "recovery")
        print(f"Recovery failed; error_id={identity}")
        raise SystemExit(1) from None
    finally:
        request_id.reset(token)


if __name__ == "__main__":
    main()
