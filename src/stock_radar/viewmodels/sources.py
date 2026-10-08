from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class SourceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    code: str
    name: str


class SourceListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[SourceOutput]
    limit: int
    offset: int
    has_more: bool


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
