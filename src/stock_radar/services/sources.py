from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_radar.db.models import Source
from stock_radar.viewmodels.sources import SourceInput, SourceListInput, SourceListOutput, SourceOutput
from stock_radar.services.errors import ServiceError


@dataclass(frozen=True)
class SourceQuery:
    limit: int
    offset: int
    code: str | None


class SourceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, request: SourceInput) -> SourceOutput:
        with self.session.begin():
            source_id = self.session.scalar(insert(Source).values(code=request.code, name=request.name).on_conflict_do_nothing(index_elements=[Source.code]).returning(Source.id))
            entity = self.session.get(Source, source_id) if source_id else self.session.scalar(select(Source).where(Source.code == request.code))
            if entity.name != request.name:
                raise ServiceError("source_identity_conflict", 409)
            result = self._transform_output(entity)
        return result

    def list_sources(self, request: SourceListInput) -> SourceListOutput:
        query = self._transform_input(request)
        statement = select(Source).order_by(Source.code, Source.id)
        if query.code is not None:
            statement = statement.where(Source.code == query.code)
        entities = self.session.scalars(statement.offset(query.offset).limit(query.limit + 1)).all()
        return SourceListOutput(
            items=[self._transform_output(entity) for entity in entities[:query.limit]],
            limit=query.limit,
            offset=query.offset,
            has_more=len(entities) > query.limit,
        )

    @staticmethod
    def _transform_input(request: SourceListInput) -> SourceQuery:
        return SourceQuery(
            limit=request.limit,
            offset=request.offset,
            code=request.code.lower() if request.code is not None else None,
        )

    @staticmethod
    def _transform_output(entity: Source) -> SourceOutput:
        return SourceOutput(id=entity.id, code=entity.code, name=entity.name)
