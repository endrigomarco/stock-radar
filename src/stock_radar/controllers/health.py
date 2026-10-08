from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session
from stock_radar.security import require_reader
from stock_radar.services.health import HealthService
from stock_radar.viewmodels.health import HealthOutput

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthOutput)
def live() -> HealthOutput:
    return HealthOutput()


@router.get("/ready", response_model=HealthOutput, dependencies=[Depends(require_reader)])
def ready(session: Annotated[Session, Depends(get_session)]) -> HealthOutput:
    return HealthService(session).readiness()
