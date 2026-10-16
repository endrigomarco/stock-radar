from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_radar.db.models import CollectionRun, Experiment, ExperimentVersion

EXPERIMENT_CODE = "tradingview_losers_strong_buy"
SELECTION_KEY = "candidate_selection"


@dataclass(frozen=True)
class SelectionRules:
    max_new_per_session: int
    criteria_version: str


def selection_rules(rules: dict[str, Any] | None) -> SelectionRules | None:
    settings = (rules or {}).get(SELECTION_KEY)
    if not isinstance(settings, dict):
        return None
    return SelectionRules(max_new_per_session=int(settings["max_new_per_session"]), criteria_version=str(settings["criteria_version"]))


def reference_after_decision(rules: dict[str, Any] | None) -> bool:
    settings = (rules or {}).get(SELECTION_KEY)
    return isinstance(settings, dict) and bool(settings.get("reference_after_decision"))


class PolicyResolver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def versions(self) -> list[ExperimentVersion]:
        return list(self.session.scalars(
            select(ExperimentVersion).join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
            .where(Experiment.code == EXPERIMENT_CODE).order_by(ExperimentVersion.version.desc())
        ).all())

    def for_session(self, market_session_date: date) -> ExperimentVersion | None:
        first = self.session.execute(
            select(CollectionRun.id, CollectionRun.experiment_version_id)
            .where(CollectionRun.market_session_date == market_session_date)
            .order_by(CollectionRun.received_at, CollectionRun.id).limit(1)
        ).first()
        versions = self.versions()
        if first is None:
            return versions[0] if versions else None
        if first.experiment_version_id is not None:
            return next((version for version in versions if version.id == first.experiment_version_id), None)
        return next((version for version in versions if selection_rules(version.rules) is None), None)

    def lock_session(self, market_session_date: date) -> None:
        advisory_lock(self.session, f"stock_radar:selection:{market_session_date.isoformat()}")


def advisory_lock(session: Session, key: str) -> None:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
