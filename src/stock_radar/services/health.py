from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_radar.viewmodels.health import HealthOutput


class HealthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def readiness(self) -> HealthOutput:
        self.session.execute(text("SELECT 1"))
        return HealthOutput()
