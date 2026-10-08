from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_webhook_session
from stock_radar.security import require_reader, require_webhook
from stock_radar.services.webhooks import WebhookService, process_receipt
from stock_radar.viewmodels.webhooks import WebhookInput, WebhookOutput
from stock_radar.observability.logging import emit

router = APIRouter()


@router.post("/webhooks/tradingview", status_code=202, response_model=WebhookOutput, dependencies=[Depends(require_webhook)])
def receive_webhook(payload: WebhookInput, request: Request, tasks: BackgroundTasks, session: Annotated[Session, Depends(get_webhook_session)]) -> WebhookOutput:
    result = WebhookService(session).receive(payload)
    emit("webhook_received", receipt_id=str(result.id), duplicate=result.duplicate, status=result.status)
    if result.status != "processed":
        tasks.add_task(process_receipt, request.app.state.webhook_engine, result.id, request.app.state.telemetry)
    return result


@router.get("/v1/webhook-receipts/{receipt_id}", response_model=WebhookOutput, dependencies=[Depends(require_reader)])
def get_receipt(receipt_id: UUID, session: Annotated[Session, Depends(get_webhook_session)]) -> WebhookOutput:
    return WebhookService(session).get(receipt_id)
