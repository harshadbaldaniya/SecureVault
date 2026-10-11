"""Structured application logs.

Two rules keep logs safe: (1) the JSON formatter emits only an explicit allow-list of fields, so a stray `extra=`
(a request object, a header, a body) can never reach the output; (2) the access log below records the route
pattern and status, never query strings, headers, cookies or bodies.
"""

import json
import logging
import traceback
from datetime import UTC, datetime

from core.request_context import current

# Fields the access log may carry (see core.observability). Anything else in `record.sv` is dropped.
ACCESS_FIELDS = ("method", "route", "status", "duration_ms", "user_id", "org_id", "ip")


class RequestIdFilter(logging.Filter):
    """Adds the current request's server-generated id to every record logged while handling a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = current()
        record.request_id = ctx.request_id if ctx else "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp (UTC), level, logger, message, request id, optional access fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        access = getattr(record, "sv", None)
        if isinstance(access, dict):
            entry.update({key: access[key] for key in ACCESS_FIELDS if key in access})
        if record.exc_info:
            entry["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(entry, ensure_ascii=False, default=str)


def logging_config(*, json_output: bool, level: str = "INFO") -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": "core.logs.RequestIdFilter"}},
        "formatters": {
            "json": {"()": "core.logs.JsonFormatter"},
            "plain": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json" if json_output else "plain",
                "filters": ["request_id"],
            }
        },
        "root": {"handlers": ["console"], "level": level},
        # DisallowedHost spam is noise, and its message would echo an attacker-chosen Host header.
        "loggers": {"django.security.DisallowedHost": {"handlers": [], "propagate": False}},
    }
