from __future__ import annotations

import logging

from recipe_assistant.core.config import Settings


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure the V2 logger without touching legacy file handlers."""

    logger = logging.getLogger("recipe_assistant")
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)

    return logger
