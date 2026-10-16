from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session, get_write_session
from stock_radar.security import require_collector, require_reader
from stock_radar.services.selection import SelectionService
from stock_radar.viewmodels.selection import CandidateQuery, CandidateSession, SelectionInput, SelectionOutput

router = APIRouter(prefix="/v1", dependencies=[Depends(require_reader)])


@router.get("/selection/candidates", response_model=CandidateSession)
def list_selection_candidates(query: Annotated[CandidateQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> CandidateSession:
    return SelectionService(session).candidates(query)


@router.post("/selections", response_model=SelectionOutput, dependencies=[Depends(require_collector)])
def confirm_selection(request: SelectionInput, session: Annotated[Session, Depends(get_write_session)]) -> SelectionOutput:
    return SelectionService(session).confirm(request)
