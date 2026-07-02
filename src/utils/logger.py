import sys
from typing import Any

from loguru import logger

from src.utils.config import config


def setup_logger() -> Any:
    """Configure loguru logger."""
    config.setup_directories()

    # Remove default handler
    logger.remove()

    # Console handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
    )

    # File handler (daily rotation)
    log_file = config.log_dir / "jelotia_imposer_{time:YYYY-MM-DD}.log"
    logger.add(
        str(log_file),
        rotation="00:00",
        retention="30 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="INFO",
    )

    return logger


# Create a default configured logger instance
app_logger = setup_logger()
