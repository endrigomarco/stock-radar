import os
import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import URL

MCP_LOCAL_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
MCP_LOCAL_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")
MCP_ALLOWED_HOST_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?(:[0-9]{1,5})?$")
MCP_ALLOWED_HOSTS_LIMIT = 8


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    log_directory: str | None = None
    webhook_token: SecretStr = Field(min_length=32)
    webhook_password: SecretStr = Field(min_length=32)
    reader_token: SecretStr = Field(min_length=32)
    collector_token: SecretStr = Field(min_length=32)
    collector_password: SecretStr = Field(min_length=32)
    database_password: SecretStr = Field(min_length=32)
    database_name: str = Field(min_length=1)
    database_host: str = "postgres"
    database_port: int = Field(default=5432, ge=1, le=65535)
    mcp_allowed_hosts: tuple[str, ...] = Field(default=(), max_length=MCP_ALLOWED_HOSTS_LIMIT)

    @field_validator("mcp_allowed_hosts", mode="before")
    @classmethod
    def exact_hosts(cls, value: object) -> tuple[str, ...]:
        entries = value.split(",") if isinstance(value, str) else list(value or ())
        hosts = tuple(str(entry).strip().lower() for entry in entries if str(entry).strip())
        for host in hosts:
            if not MCP_ALLOWED_HOST_PATTERN.fullmatch(host):
                raise ValueError("MCP_ALLOWED_HOSTS accepts exact host or host:port entries only")
        return hosts

    @model_validator(mode="after")
    def separate_tokens(self) -> "Settings":
        tokens = [self.reader_token.get_secret_value(), self.collector_token.get_secret_value(), self.webhook_token.get_secret_value()]
        if len(set(tokens)) != len(tokens):
            raise ValueError("Reader, collector and webhook tokens must differ")
        return self

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            log_directory=os.environ.get("LOG_DIRECTORY") or None,
            webhook_token=os.environ.get("WEBHOOK_TOKEN", ""),
            webhook_password=os.environ.get("WEBHOOK_POSTGRES_PASSWORD", ""),
            collector_token=os.environ.get("API_COLLECTOR_TOKEN", ""),
            collector_password=os.environ.get("COLLECTOR_POSTGRES_PASSWORD", ""),
            reader_token=os.environ.get("API_READER_TOKEN", ""),
            database_password=os.environ.get("APP_POSTGRES_PASSWORD", ""),
            database_name=os.environ.get("POSTGRES_DB", ""),
            database_host=os.environ.get("POSTGRES_HOST", "postgres"),
            database_port=os.environ.get("POSTGRES_PORT", "5432"),
            mcp_allowed_hosts=os.environ.get("MCP_ALLOWED_HOSTS", ""),
        )

    def mcp_hosts(self) -> list[str]:
        return [*MCP_LOCAL_HOSTS, *self.mcp_allowed_hosts]

    def database_url(self, write: bool = False) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username="stock_radar_collector" if write else "stock_radar_reader",
            password=(self.collector_password if write else self.database_password).get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )

    def webhook_database_url(self) -> URL:
        return self.database_url().set(username="stock_radar_webhook", password=self.webhook_password.get_secret_value())


def monitor_enabled() -> bool:
    return os.environ.get("MONITOR_ENABLED", "false").strip().lower() == "true"


class MonitorSettings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    log_directory: str | None = None
    enabled: bool = False
    api_key: SecretStr | None = None
    max_instruments: int = Field(default=30, ge=1, le=200)
    database_password: SecretStr = Field(min_length=32)
    database_name: str = Field(min_length=1)
    database_host: str = "postgres"
    database_port: int = Field(default=5432, ge=1, le=65535)

    @model_validator(mode="after")
    def key_when_enabled(self) -> "MonitorSettings":
        if self.enabled and (self.api_key is None or not self.api_key.get_secret_value().strip()):
            raise ValueError("BRAPI_API_KEY is required when MONITOR_ENABLED is true")
        return self

    @classmethod
    def from_environment(cls) -> "MonitorSettings":
        return cls(
            log_directory=os.environ.get("LOG_DIRECTORY") or None,
            enabled=monitor_enabled(),
            api_key=os.environ.get("BRAPI_API_KEY") or None,
            max_instruments=os.environ.get("MONITOR_MAX_INSTRUMENTS") or 30,
            database_password=os.environ.get("MONITOR_POSTGRES_PASSWORD", ""),
            database_name=os.environ.get("POSTGRES_DB", ""),
            database_host=os.environ.get("POSTGRES_HOST", "postgres"),
            database_port=os.environ.get("POSTGRES_PORT", "5432"),
        )

    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username="stock_radar_monitor",
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )
