import sys
from pathlib import Path

from loguru import logger
from pydantic import BaseModel


class AppConfig(BaseModel):
    # Paths
    base_dir: Path = Path("C:/Jelotia/HotFolder")
    input_dir: Path = base_dir / "Input"
    processing_dir: Path = base_dir / "Processing"
    error_dir: Path = base_dir / "Error"
    output_dir: Path = base_dir / "Output"
    archive_dir: Path = base_dir / "Archive"
    log_dir: Path = base_dir / "Logs"

    # Database
    db_path: Path = base_dir / "jelotia_imposer.db"

    def setup_directories(self) -> None:
        """Create all required directories if they don't exist."""
        for path in [
            self.input_dir,
            self.processing_dir,
            self.error_dir,
            self.output_dir,
            self.archive_dir,
            self.log_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


config = AppConfig()


def setup_logger():
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
