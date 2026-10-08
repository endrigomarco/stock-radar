"""Build database URLs without interpolating secrets into configuration files."""

import os

from sqlalchemy import URL


def database_url() -> URL:
    """Read explicit credentials, preserving password punctuation verbatim."""
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Missing database settings: {', '.join(missing)}")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
    )
