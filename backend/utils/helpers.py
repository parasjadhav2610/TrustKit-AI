"""TrustKit AI — Utility Helpers.

Shared helper functions and logging configuration used across
the backend modules.
"""

import logging
from datetime import datetime, timezone


def get_logger(name: str) -> logging.Logger:
    """Create and return a configured logger instance.

    Args:
        name: The logger name, typically ``__name__`` of the calling module.

    Returns:
        A ``logging.Logger`` instance configured with a stream handler
        and a human-readable format.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def timestamp() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Returns:
        str: Current UTC time in ISO-8601 format
             (e.g. ``'2026-03-07T20:13:24+00:00'``).
    """
    return datetime.now(timezone.utc).isoformat()
