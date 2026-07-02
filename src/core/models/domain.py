from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    ERROR = "ERROR"


class FileFormat(str, Enum):
    PDF = "PDF"
    TIFF = "TIFF"
    PNG = "PNG"
    JPEG = "JPEG"


class ColorMode(str, Enum):
    CMYK = "CMYK"
    RGB = "RGB"
    GRAY = "GRAY"


class PreflightStatus(str, Enum):
    PENDING = "PENDING"
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"


class PreflightErrorType(str, Enum):
    RESOLUTION_LOW = "RESOLUTION_LOW"
    WRONG_COLOR_MODE = "WRONG_COLOR_MODE"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    TRANSPARENCY_DETECTED = "TRANSPARENCY_DETECTED"
    FONTS_NOT_EMBEDDED = "FONTS_NOT_EMBEDDED"
    NO_BLEED = "NO_BLEED"
    CORRUPTED = "CORRUPTED"


class PreflightError(BaseModel):
    type: PreflightErrorType
    message: str
    is_blocking: bool


class JobSettings(BaseModel):
    # Imposition
    sheet_width_mm: float = 900.0
    sheet_height_mm: float = 600.0
    gap_mm: float = 3.0
    allow_rotation: bool = True
    add_bleed_mm: float = 0.0

    # Preflight overrides
    min_dpi: int = 300
    force_cmyk: bool = True

    # Export Settings
    export_format: str = "PDF/X-1a"
    export_dpi: int = 300
    draw_cutlines: bool = True
    add_crop_marks: bool = True


class FileItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    path: Path
    format: FileFormat
    width_mm: float
    height_mm: float
    dpi: int
    color_mode: ColorMode
    quantity: int = 1
    preflight_status: PreflightStatus = PreflightStatus.PENDING
    preflight_errors: List[PreflightError] = Field(default_factory=list)


class PlacedItem(BaseModel):
    file_item_id: UUID
    source_path: Path
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotated: bool = False


class Sheet(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    sheet_number: int
    width_mm: float = 900.0
    height_mm: float = 600.0
    items: List[PlacedItem] = Field(default_factory=list)
    fill_rate: float = 0.0
    export_path: Optional[Path] = None


class JobStats(BaseModel):
    total_files: int = 0
    total_quantity: int = 0
    total_sheets: int = 0
    average_fill_rate: float = 0.0
    processing_time_sec: float = 0.0


class Job(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    files: List[FileItem] = Field(default_factory=list)
    settings: JobSettings = Field(default_factory=JobSettings)
    sheets: List[Sheet] = Field(default_factory=list)
    stats: JobStats = Field(default_factory=JobStats)
