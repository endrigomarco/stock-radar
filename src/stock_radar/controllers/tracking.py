from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session, get_write_session
from stock_radar.security import require_collector, require_reader
from stock_radar.services.tracking import TrackingService
from stock_radar.viewmodels.tracking import (
    LatestQuoteQuery,
    QuotePage,
    TrackingRunOutput,
    TrackingRunPage,
    TrackingRunQuery,
    TriggerEventPage,
    TriggerEventQuery,
)

router = APIRouter(prefix="/v1", dependencies=[Depends(require_reader)])


@router.get("/tracking-runs", response_model=TrackingRunPage)
def list_tracking_runs(query: Annotated[TrackingRunQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> TrackingRunPage:
    return TrackingService(session).list_runs(query)


@router.post("/tracking-runs/{tracking_run_id}/cancel", response_model=TrackingRunOutput, dependencies=[Depends(require_collector)])
def cancel_tracking_run(tracking_run_id: UUID, session: Annotated[Session, Depends(get_write_session)]) -> TrackingRunOutput:
    return TrackingService(session).cancel(tracking_run_id)


@router.get("/quotes/latest", response_model=QuotePage)
def list_latest_quotes(query: Annotated[LatestQuoteQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> QuotePage:
    return TrackingService(session).list_latest_quotes(query)


@router.get("/trigger-events", response_model=TriggerEventPage)
def list_trigger_events(query: Annotated[TriggerEventQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> TriggerEventPage:
    return TrackingService(session).list_events(query)
