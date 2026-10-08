from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session
from stock_radar.security import require_reader
from stock_radar.services.status import StatusService
from stock_radar.viewmodels.status import QualityOutput, QualityQuery, StatusOutput

router = APIRouter(prefix="/v1", dependencies=[Depends(require_reader)])


@router.get("/status", response_model=StatusOutput)
def service_status(session: Annotated[Session, Depends(get_session)]) -> StatusOutput:
    return StatusService(session).status()


@router.get("/data-quality", response_model=QualityOutput)
def data_quality_report(query: Annotated[QualityQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> QualityOutput:
    return StatusService(session).quality(query)
