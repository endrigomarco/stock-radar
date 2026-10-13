from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session
from stock_radar.security import require_reader
from stock_radar.services.reports import ReportService
from stock_radar.viewmodels.reports import DailyReport, DailyReportQuery

router = APIRouter(prefix="/v1", dependencies=[Depends(require_reader)])


@router.get("/reports/daily", response_model=DailyReport)
def daily_report(query: Annotated[DailyReportQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> DailyReport:
    return ReportService(session).daily(query)
