from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_radar.dependencies import get_session, get_write_session
from stock_radar.security import require_collector, require_reader
from stock_radar.services.collections import CollectionService, SignalService
from stock_radar.viewmodels.collections import CollectionInput, CollectionOutput, SignalPage, SignalQuery

router = APIRouter(prefix="/v1", dependencies=[Depends(require_reader)])


@router.post("/collections", response_model=CollectionOutput, dependencies=[Depends(require_collector)])
def register_collection(request: CollectionInput, session: Annotated[Session, Depends(get_write_session)]) -> CollectionOutput:
    return CollectionService(session).register(request)


@router.get("/collections/{collection_id}", response_model=CollectionOutput)
def get_collection(collection_id: UUID, session: Annotated[Session, Depends(get_session)]) -> CollectionOutput:
    return CollectionService(session).get(collection_id)


@router.get("/signals", response_model=SignalPage)
def list_signals(query: Annotated[SignalQuery, Query()], session: Annotated[Session, Depends(get_session)]) -> SignalPage:
    return SignalService(session).list_signals(query)
