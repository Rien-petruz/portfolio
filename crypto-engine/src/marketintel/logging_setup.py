"""Structured JSON logging (stdlib only).

``extra={...}`` fields are emitted as top-level JSON keys. Keys that look like
credentials are redacted defensively, although no component in this build
handles credentials.
"""

from __future__ import annotations

import logging
import sys
import time

import orjson

_STD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}
_SECRET_HINTS = ("key", "secret", "token", "password", "signature")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k in _STD or k.startswith("_"):
                continue
            out[k] = "***" if any(h in k.lower() for h in _SECRET_HINTS) else v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(out, default=str).decode()


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("websockets", "httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
