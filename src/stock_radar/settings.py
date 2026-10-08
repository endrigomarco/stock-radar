import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import URL


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
        )

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
