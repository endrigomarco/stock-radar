from typing import Literal

from pydantic import BaseModel


class HealthOutput(BaseModel):
    status: Literal["ok"] = "ok"
