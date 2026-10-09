"""Keep API keys out of the log files.

TMDB takes its key as a query parameter, and httpx logs every request URL at
INFO, so a default setup wrote `api_key=<key>` into F7FIVE0-API.err.log. Two
layers, both installed by `install()` right after logging is configured:

- `httpx` and `httpcore` are held at WARNING, so request URLs are not logged.
- `RedactApiKeyFilter` sits on the root handler(s) and rewrites the value of
  any `api_key=` parameter to `***` in every record: the message, its
  arguments, and the traceback text, so an exception that carries a URL is
  covered too.
"""
from __future__ import annotations

import logging
import re

# `api_key=` up to the next `&`, space, or quote. Case-insensitive, and the
# original spelling of the name is kept.
_KEY_RE = re.compile(r"(api_key=)[^&\s'\"]+", re.IGNORECASE)

_NOISY_LOGGERS = ("httpx", "httpcore")
# uvicorn logs request-handling tracebacks through its own handlers, which
# the root handler never sees.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    """`...?api_key=SECRET&q=1` -> `...?api_key=***&q=1`."""
    return _KEY_RE.sub(r"\1***", text)


class RedactApiKeyFilter(logging.Filter):
    """Rewrites `api_key=<value>` to `api_key=***` on the way to the handler.
    Never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = None  # a malformed record is the caller's bug, not ours
        if message is not None:
            redacted = redact(message)
            if redacted != message:
                record.msg = redacted
                record.args = ()
        if record.exc_info and record.exc_info[0] is not None:
            if not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(record.exc_text)
        return True


def _add_once(handler: logging.Handler) -> None:
    if not any(isinstance(f, RedactApiKeyFilter) for f in handler.filters):
        handler.addFilter(RedactApiKeyFilter())


def install() -> None:
    """Quiet httpx/httpcore and put the redaction filter on the root handler(s).
    Call it after `logging.basicConfig`. Safe to call more than once."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        _add_once(handler)
    for name in _UVICORN_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            _add_once(handler)
