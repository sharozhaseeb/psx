from __future__ import annotations
import logging
from pathlib import Path
import structlog

LOG_DIR = Path("data")


def configure_logging(log_file: str = "server.log", level: str = "INFO") -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
