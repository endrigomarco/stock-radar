import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_radar.db.models import CollectionRun, Instrument, SignalObservation, Source
from stock_radar.services.errors import ServiceError
from stock_radar.viewmodels.collections import CollectionInput, CollectionOutput, ObservationInput, SignalOutput, SignalPage, SignalQuery


def eligible_expression():
    return (
        (SignalObservation.signal_kind == "analyst_consensus")
        & (SignalObservation.normalized_rating == "strong_buy")
        & (SignalObservation.daily_change_percent < 0)
    )


class CollectionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, request: CollectionInput) -> CollectionOutput:
        values, digest = self._transform_input(request)
        with self.session.begin():
            source = self.session.get(Source, request.source_id)
            if source is None:
                raise ServiceError("source_not_found", 404)
            statement = insert(CollectionRun).values(**values, payload_hash=digest).on_conflict_do_nothing(
                index_elements=[CollectionRun.source_id, CollectionRun.client_collection_id]
            ).returning(CollectionRun.id)
            collection_id = self.session.scalar(statement)
            duplicate = collection_id is None
            if duplicate:
                existing = self.session.scalar(select(CollectionRun).where(
                    CollectionRun.source_id == request.source_id,
                    CollectionRun.client_collection_id == request.client_collection_id,
                ))
                if existing.payload_hash != digest:
                    raise ServiceError("collection_identity_conflict", 409)
                collection_id = existing.id
            else:
                for row in sorted(request.observations, key=lambda item: (item.exchange, item.symbol, item.signal_kind)):
                    instrument_id = self.session.scalar(insert(Instrument).values(
                        exchange=row.exchange, symbol=row.symbol, currency=row.currency,
                    ).on_conflict_do_nothing(index_elements=[Instrument.exchange, Instrument.symbol]).returning(Instrument.id))
                    if instrument_id is None:
                        instrument = self.session.scalar(select(Instrument).where(Instrument.exchange == row.exchange, Instrument.symbol == row.symbol))
                        if instrument.currency != row.currency:
                            raise ServiceError("instrument_currency_conflict", 409)
                        instrument_id = instrument.id
                    rating = self._normalize_rating(source.code, row)
                    observed_values = {"observed_price": row.observed_price, "daily_change_percent": row.daily_change_percent, "original_rating": row.original_rating}
                    missing = [name for name, value in observed_values.items() if value is None]
                    if rating is None:
                        missing.append("normalized_rating")
                    self.session.add(SignalObservation(
                        collection_run_id=collection_id, instrument_id=instrument_id,
                        signal_kind=row.signal_kind, source_symbol=row.source_symbol,
                        source_column=row.source_column, original_rating=row.original_rating,
                        normalized_rating=rating, normalization_version="tradingview-analyst-v1" if source.code == "tradingview" else "unmapped-v1",
                        observed_price=row.observed_price, daily_change_percent=row.daily_change_percent,
                        observed_at=row.observed_at, source_published_at=row.source_published_at,
                        parse_status="partial" if missing else "valid", raw_evidence=row.raw_evidence,
                        quality_details={"missing_or_unknown": missing} if missing else {},
                    ))
                self.session.flush()
            result = self.get(collection_id)
            result.duplicate = duplicate
        return result

    def get(self, collection_id: UUID) -> CollectionOutput:
        entity = self.session.get(CollectionRun, collection_id)
        if entity is None:
            raise ServiceError("collection_not_found", 404)
        counts = self.session.execute(select(
            func.count(SignalObservation.id),
            func.count(SignalObservation.id).filter(eligible_expression()),
            func.count(SignalObservation.id).filter(SignalObservation.parse_status != "valid"),
        ).where(SignalObservation.collection_run_id == collection_id)).one()
        return self._transform_output(entity, *counts)

    @staticmethod
    def _transform_input(request: CollectionInput) -> tuple[dict, str]:
        canonical = request.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        values = {
            "client_collection_id": request.client_collection_id,
            "source_id": request.source_id,
            "source_url": str(request.source_url),
            "observed_at": request.observed_at,
            "market_session_date": request.market_session_date,
            "status": request.status,
            "source_total": request.source_total,
            "filters": request.filters,
        }
        return values, digest

    @staticmethod
    def _transform_output(entity: CollectionRun, count: int, eligible: int, incomplete: int) -> CollectionOutput:
        return CollectionOutput(
            id=entity.id, source_id=entity.source_id, client_collection_id=entity.client_collection_id,
            status=entity.status, observed_at=entity.observed_at, received_at=entity.received_at,
            observation_count=count, eligible_count=eligible, incomplete_count=incomplete,
        )

    @staticmethod
    def _normalize_rating(source_code: str, row: ObservationInput) -> str | None:
        if source_code != "tradingview" or row.signal_kind != "analyst_consensus" or row.original_rating is None:
            return None
        labels = {"strong buy": "strong_buy", "viés de alta forte": "strong_buy", "buy": "buy", "neutral": "neutral", "sell": "sell", "strong sell": "strong_sell"}
        return labels.get(row.original_rating.strip().casefold())


class SignalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_signals(self, request: SignalQuery) -> SignalPage:
        statement = self._transform_input(request)
        entities = self.session.scalars(statement.limit(request.limit + 1).offset(request.offset)).all()
        return SignalPage(items=[self._transform_output(entity) for entity in entities[:request.limit]], limit=request.limit, offset=request.offset, has_more=len(entities) > request.limit)

    @staticmethod
    def _transform_input(request: SignalQuery):
        statement = select(SignalObservation).join(CollectionRun).order_by(SignalObservation.observed_at.desc(), SignalObservation.id)
        if request.collection_id:
            statement = statement.where(SignalObservation.collection_run_id == request.collection_id)
        if request.source_id:
            statement = statement.where(CollectionRun.source_id == request.source_id)
        if request.instrument_id:
            statement = statement.where(SignalObservation.instrument_id == request.instrument_id)
        if request.eligible_only:
            statement = statement.where(eligible_expression())
        return statement

    @staticmethod
    def _transform_output(entity: SignalObservation) -> SignalOutput:
        eligible = entity.signal_kind == "analyst_consensus" and entity.normalized_rating == "strong_buy" and entity.daily_change_percent is not None and entity.daily_change_percent < 0
        return SignalOutput(
            id=entity.id, collection_id=entity.collection_run_id, instrument_id=entity.instrument_id,
            signal_kind=entity.signal_kind, source_symbol=entity.source_symbol,
            original_rating=entity.original_rating, normalized_rating=entity.normalized_rating,
            observed_price=entity.observed_price, daily_change_percent=entity.daily_change_percent,
            observed_at=entity.observed_at, parse_status=entity.parse_status, eligible=eligible,
        )
