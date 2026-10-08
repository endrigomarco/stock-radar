import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_radar.db.models import Source, TrackingRun, TriggerEvent, TriggerLevel, WebhookReceipt
from stock_radar.services.errors import ServiceError
from stock_radar.viewmodels.webhooks import WebhookInput, WebhookOutput

from stock_radar.observability.logging import emit, request_id
from stock_radar.observability.telemetry import Telemetry, correlation_id


class WebhookService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def receive(self, request: WebhookInput) -> WebhookOutput:
        payload, key = self._transform_input(request)
        with self.session.begin():
            source_id = self.session.scalar(select(Source.id).where(Source.code == "tradingview"))
            if source_id is None:
                raise ServiceError("webhook_source_not_configured", 503)
            existing = self.session.scalar(select(WebhookReceipt).where(
                WebhookReceipt.source_id == source_id, WebhookReceipt.deduplication_key == key,
            ))
            if existing is not None:
                return self._duplicate(existing, payload)
            if request.source_event_at > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ServiceError("event_timestamp_in_future", 422)
            receipt_id = self.session.scalar(insert(WebhookReceipt).values(
                source_id=source_id, deduplication_key=key,
                provider_event_id=request.provider_event_id,
                reported_alert_mapping_id=request.alert_mapping_id,
                source_event_at=request.source_event_at, sanitized_payload=payload,
            ).on_conflict_do_nothing(index_elements=[WebhookReceipt.source_id, WebhookReceipt.deduplication_key]).returning(WebhookReceipt.id))
            if receipt_id is None:
                existing = self.session.scalar(select(WebhookReceipt).where(
                    WebhookReceipt.source_id == source_id, WebhookReceipt.deduplication_key == key,
                ))
                return self._duplicate(existing, payload)
            result = self._transform_output(self.session.get(WebhookReceipt, receipt_id))
        return result

    def get(self, receipt_id: UUID) -> WebhookOutput:
        receipt = self.session.get(WebhookReceipt, receipt_id)
        if receipt is None:
            raise ServiceError("webhook_receipt_not_found", 404)
        return self._transform_output(receipt)

    def process(self, receipt_id: UUID) -> str:
        with self.session.begin():
            receipt = self.session.scalar(select(WebhookReceipt).where(WebhookReceipt.id == receipt_id).with_for_update())
            if receipt is None:
                return "missing"
            if receipt.status == "processed":
                return "already_processed"
            receipt.processing_attempts += 1
            try:
                request = WebhookInput.model_validate(receipt.sanitized_payload)
            except ValidationError:
                self._finish(receipt, "failed", "invalid_stored_payload")
                return "failed"
            level = self.session.scalar(select(TriggerLevel).where(TriggerLevel.alert_mapping_id == request.alert_mapping_id))
            if level is None:
                self._finish(receipt, "unmapped", "alert_mapping_not_found")
                return "unmapped"
            run = self.session.get(TrackingRun, level.tracking_run_id)
            error = self._mapping_error(receipt, request, level, run)
            if error:
                self._finish(receipt, "failed", error)
                return "failed"
            statement = insert(TriggerEvent).values(
                trigger_level_id=level.id, webhook_receipt_id=receipt.id,
                occurred_at=request.source_event_at, observed_price=request.observed_price,
                evidence_quality="timestamped",
            )
            self.session.execute(statement.on_conflict_do_update(
                index_elements=[TriggerEvent.trigger_level_id],
                set_={"webhook_receipt_id": statement.excluded.webhook_receipt_id,
                      "occurred_at": statement.excluded.occurred_at,
                      "observed_price": statement.excluded.observed_price,
                      "evidence_quality": statement.excluded.evidence_quality},
                where=(TriggerEvent.occurred_at.is_(None) | (statement.excluded.occurred_at < TriggerEvent.occurred_at)),
            ))
            self._finish(receipt, "processed", None)
        return "processed"

    @staticmethod
    def _mapping_error(receipt: WebhookReceipt, request: WebhookInput, level: TriggerLevel, run: TrackingRun) -> str | None:
        if level.alert_source_id != receipt.source_id:
            return "alert_source_mismatch"
        if level.tracking_run_id != request.tracking_run_id or level.signed_percent != request.signed_percent:
            return "alert_mapping_mismatch"
        if run.status not in {"active", "completed"} or run.activated_at is None or level.alert_active_at is None:
            return "alert_not_active"
        start = max(run.activated_at, level.alert_active_at)
        end = min(run.expires_at, level.alert_expires_at) if level.alert_expires_at else run.expires_at
        if not start <= request.source_event_at < end:
            return "event_outside_tracking_window"
        threshold = level.configured_price or level.mathematical_price
        if request.observed_price is not None:
            if (level.signed_percent > 0 and request.observed_price < threshold) or (level.signed_percent < 0 and request.observed_price > threshold):
                return "price_threshold_mismatch"
        return None

    @staticmethod
    def _finish(receipt: WebhookReceipt, status: str, error: str | None) -> None:
        receipt.status = status
        receipt.last_error_code = error
        receipt.processed_at = datetime.now(timezone.utc)

    @staticmethod
    def _transform_input(request: WebhookInput) -> tuple[dict, str]:
        payload = request.model_dump(mode="json")
        payload["signed_percent"] = str(request.signed_percent.normalize())
        payload["observed_price"] = str(request.observed_price.normalize()) if request.observed_price is not None else None
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        key = "event:" + hashlib.sha256(request.provider_event_id.encode()).hexdigest() if request.provider_event_id else "payload:" + digest
        return payload, key

    def _duplicate(self, receipt: WebhookReceipt, payload: dict) -> WebhookOutput:
        if receipt.sanitized_payload != payload:
            raise ServiceError("webhook_identity_conflict", 409)
        result = self._transform_output(receipt)
        result.duplicate = True
        return result

    @staticmethod
    def _transform_output(receipt: WebhookReceipt) -> WebhookOutput:
        return WebhookOutput(
            id=receipt.id, status=receipt.status, received_at=receipt.received_at,
            source_event_at=receipt.source_event_at, processing_attempts=receipt.processing_attempts,
            last_error_code=receipt.last_error_code,
        )


def process_receipt(engine, receipt_id: UUID, telemetry: Telemetry | None = None) -> bool:
    telemetry = telemetry or Telemetry()
    token = request_id.set(correlation_id())
    try:
        with Session(engine) as session:
            outcome = WebhookService(session).process(receipt_id)
        telemetry.webhooks.labels(outcome).inc()
        emit("webhook_processed", logging.WARNING if outcome in {"unmapped", "failed", "missing"} else logging.INFO,
             receipt_id=str(receipt_id), outcome=outcome)
        return True
    except Exception as error:
        telemetry.webhooks.labels("error").inc()
        telemetry.error(error, "webhook", receipt_id=str(receipt_id))
        return False
    finally:
        request_id.reset(token)
