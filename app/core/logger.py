"""Structured logging setup.

Logs go to stdout (so Docker/App Runner/CloudWatch capture them) and to a
daily rotating file for local debugging. Configured exactly once.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from app.core.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_configured = False


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.logs_dir / f"app_{datetime.now(timezone.utc):%Y-%m-%d}.log"

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Third-party libraries are chatty; keep them at WARNING.
    for noisy in ("httpx", "urllib3", "sentence_transformers", "httpcore", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger with root configuration applied."""
    _configure_root_logger()
    return logging.getLogger(name)
