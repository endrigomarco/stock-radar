from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_radar.db.models import CollectionRun, SignalObservation
from stock_radar.viewmodels.status import QualityOutput, QualityQuery, StatusOutput


class StatusService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def status(self) -> StatusOutput:
        last = self.session.scalar(select(func.max(CollectionRun.received_at)).where(CollectionRun.status == "complete"))
        return StatusOutput(last_complete_collection_at=last)

    def quality(self, request: QualityQuery) -> QualityOutput:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=request.days)
        conditions = [CollectionRun.observed_at >= since, CollectionRun.observed_at <= now]
        if request.source_id:
            conditions.append(CollectionRun.source_id == request.source_id)
        counts = self.session.execute(select(
            func.count(CollectionRun.id),
            func.count(CollectionRun.id).filter(CollectionRun.status == "partial"),
            func.count(CollectionRun.id).filter(CollectionRun.status == "failed"),
        ).where(*conditions)).one()
        rows = self.session.execute(select(
            func.count(SignalObservation.id),
            func.count(SignalObservation.id).filter(SignalObservation.parse_status != "valid"),
        ).join(CollectionRun).where(*conditions)).one()
        return QualityOutput(as_of=now, since=since, source_id=request.source_id, collections=counts[0], partial_collections=counts[1], failed_collections=counts[2], observations=rows[0], incomplete_observations=rows[1])
