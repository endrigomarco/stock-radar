from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event_data", None)
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "stock-radar",
            "request_id": request_id.get(),
        }
        if event is None:
            data.update(event="runtime_log", logger=record.name)
            if record.exc_info and record.exc_info[0]:
                data["exception_type"] = record.exc_info[0].__name__
        else:
            data.update(event)
        return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


class SharedRotatingHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            with open(self.baseFilename + ".lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if self.stream:
                    self.stream.close()
                    self.stream = None
                super().emit(record)
        except OSError:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        sys.stderr.write('{"level":"ERROR","event":"log_storage_unavailable"}\n')


def configure_logging(directory: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        handlers.append(SharedRotatingHandler(path / "events.jsonl", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8", delay=True))
    formatter = JsonFormatter()
    root = logging.getLogger()
    for old in root.handlers[:]:
        root.removeHandler(old)
        old.close()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger("stock_radar.telemetry").setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "mcp"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.WARNING)


def emit(event: str, level: int = logging.INFO, **fields) -> None:
    logging.getLogger("stock_radar.telemetry").log(level, event, extra={"event_data": {"event": event, **fields}})
