"""
Centralized logging configuration.
Used across services so processing stages, validation failures, OCR/model
calls and exceptions are all traceable during evaluation.
"""
import logging
import sys
from app.core.config import get_settings

_settings = get_settings()


def configure_logging() -> None:
    level = getattr(logging, _settings.LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. reload) - avoid duplicate handlers
        return
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
