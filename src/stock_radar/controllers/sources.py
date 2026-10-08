from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session
from stock_radar.security import require_reader
from stock_radar.services.sources import SourceService
from stock_radar.viewmodels.sources import SourceListInput, SourceListOutput

from stock_radar.dependencies import get_write_session
from stock_radar.security import require_collector
from stock_radar.viewmodels.sources import SourceInput, SourceOutput

router = APIRouter(prefix="/v1/sources", tags=["sources"], dependencies=[Depends(require_reader)])


@router.get("", response_model=SourceListOutput)
def list_sources(
    query: Annotated[SourceListInput, Query()],
    session: Annotated[Session, Depends(get_session)],
) -> SourceListOutput:
    return SourceService(session).list_sources(query)


@router.post("", response_model=SourceOutput, dependencies=[Depends(require_collector)])
def register_source(request: SourceInput, session: Annotated[Session, Depends(get_write_session)]) -> SourceOutput:
    return SourceService(session).register(request)
