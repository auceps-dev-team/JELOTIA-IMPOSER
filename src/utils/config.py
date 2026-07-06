import sys
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from src.utils.config_manager import ConfigManager


def _resolve_base_dir() -> Path:
    """Derive the base HotFolder directory from the user-configured input path
    (config.json via ConfigManager), matching the fallback used by main_window
    and OutputManager so all components agree on a single directory tree."""
    input_path = ConfigManager().get("paths", "input") or str(
        Path.home() / "Jelotia" / "HotFolder" / "Input"
    )
    return Path(input_path).parent


class AppConfig(BaseModel):
    # Paths
    base_dir: Path = Field(default_factory=_resolve_base_dir)
    input_dir: Path = Field(default_factory=lambda: _resolve_base_dir() / "Input")
    processing_dir: Path = Field(default_factory=lambda: _resolve_base_dir() / "Processing")
    error_dir: Path = Field(default_factory=lambda: _resolve_base_dir() / "Error")
    output_dir: Path = Field(default_factory=lambda: _resolve_base_dir() / "Output")
    archive_dir: Path = Field(default_factory=lambda: _resolve_base_dir() / "Archive")
    log_dir: Path = Field(default_factory=lambda: _resolve_base_dir() / "Logs")

    # Database
    db_path: Path = Field(default_factory=lambda: _resolve_base_dir() / "jelotia_imposer.db")

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
