from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_write_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.collector_engine) as session:
        yield session


def get_webhook_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.webhook_engine) as session:
        yield session
