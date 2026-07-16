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
    margin_mm: float = 0.0
    allow_rotation: bool = True
    add_bleed_mm: float = 0.0

    # Preflight overrides
    min_dpi: int = 300
    force_cmyk: bool = True
    # Absolute path to the destination CMYK ICC profile. Empty = no colour
    # management (Pillow's naive conversion, which overshoots ink limits).
    icc_profile_path: str = ""

    # Export Settings
    export_format: str = "PDF/X-1a"
    export_dpi: int = 300
    draw_cutlines: bool = True
    add_crop_marks: bool = True

    # Layout extras
    add_qr_code: bool = False
    qr_code_size_mm: float = 20.0
    generate_thumbnail: bool = True
    separate_cut_layer: bool = False

    # Plotter registration marks (Graphtec ARMS): "none", "graphtec1"
    # (L arms pointing OUT toward the media corners) or "graphtec2"
    # (L arms pointing IN toward the artwork) — must match the mark type
    # configured in the plotter's ARMS menu.
    plotter_marks: str = "none"
    plotter_mark_length_mm: float = 15.0
    plotter_mark_thickness_mm: float = 0.5
    plotter_mark_margin_mm: float = 5.0

    # Print & cut RIPs: stroke every pose with the "CutContour" spot color.
    cut_contour_spot: bool = False

    # Set by the app from the active license: a Personnel/unlicensed job stamps
    # a discreet mark on its sheets. Lives here because sheet generation runs
    # in a worker process, with no access to the licensing singleton.
    watermark_text: str = ""

    def plotter_reserve_mm(self) -> float:
        """Margin the nesting must reserve so no pose collides with the ARMS
        marks (mark inset + arm length + quiet zone for reliable sensing)."""
        if self.plotter_marks == "none":
            return 0.0
        return self.plotter_mark_margin_mm + self.plotter_mark_length_mm + 3.0


class FileItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    path: Path
    format: FileFormat
    # Dimensions INCLUDE the bleed when bleed_mm > 0 (the artwork really is
    # that big); the finished size is width_mm - 2*bleed_mm.
    width_mm: float
    height_mm: float
    dpi: int
    color_mode: ColorMode
    quantity: int = 1
    bleed_mm: float = 0.0
    preflight_status: PreflightStatus = PreflightStatus.PENDING
    preflight_errors: List[PreflightError] = Field(default_factory=list)


class PlacedItem(BaseModel):
    """A pose on a sheet. x/y/width/height cover the artwork AS PRINTED —
    bleed included. Cutting happens at the finished size: the same rectangle
    inset by bleed_mm on every side (see trim_rect_mm)."""
    file_item_id: UUID
    source_path: Path
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotated: bool = False
    bleed_mm: float = 0.0

    def trim_rect_mm(self) -> tuple:
        """(x, y, width, height) of the finished size — where the blade goes."""
        b = self.bleed_mm
        return (self.x_mm + b, self.y_mm + b,
                max(0.0, self.width_mm - 2 * b), max(0.0, self.height_mm - 2 * b))


class Sheet(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    sheet_number: int
    width_mm: float = 900.0
    height_mm: float = 600.0
    items: List[PlacedItem] = Field(default_factory=list)
    fill_rate: float = 0.0
    export_path: Optional[Path] = None
    thumbnail_path: Optional[Path] = None
    cut_layer_path: Optional[Path] = None


class QRErrorCorrection(str, Enum):
    """QR error-correction level = how much of the code can be damaged (or
    covered by a logo) while still scanning. L≈7%, M≈15%, Q≈25%, H≈30%."""
    L = "L"
    M = "M"
    Q = "Q"
    H = "H"


class QRCodeSettings(BaseModel):
    """Visual/encoding parameters for QR generation (JELOTIA QR Generator).
    Physical size_mm + dpi drive print output; box_size/border drive the raw
    module raster before it's scaled to the requested physical size."""
    ecc: QRErrorCorrection = QRErrorCorrection.M
    box_size: int = 10  # pixels per module in the base raster
    border: int = 4  # quiet-zone width in modules (4 = spec minimum)
    fill_color: str = "#000000"
    back_color: str = "#FFFFFF"
    size_mm: float = 30.0  # physical side length for print (PDF/PNG)
    dpi: int = 300
    logo_path: Optional[Path] = None
    logo_scale: float = 0.22  # logo side as a fraction of the QR side


class QRItem(BaseModel):
    """One row of a batch = one QR code to produce. `data` is the encoded
    URL/text; `filename` is the output base name (from a configurable import
    column); `quantity` is how many copies to place when imposed on a sheet.
    `row` keeps the full imported row so template text zones can substitute
    {Colonne} placeholders with per-row values (variable-data printing)."""
    id: UUID = Field(default_factory=uuid4)
    data: str
    filename: str = ""
    quantity: int = 1
    row: dict = Field(default_factory=dict)


class TemplateQRZone(BaseModel):
    """Where the QR code lands on a card template (top-left corner + side)."""
    x_mm: float = 5.0
    y_mm: float = 5.0
    size_mm: float = 20.0


class TemplateTextZone(BaseModel):
    """A text block on a card template. `text` may contain {Colonne}
    placeholders, substituted from the imported row at composition time."""
    id: UUID = Field(default_factory=uuid4)
    text: str = "Texte"
    x_mm: float = 5.0
    y_mm: float = 5.0
    font_size_pt: float = 10.0
    color: str = "#000000"
    bold: bool = False


class CardTemplate(BaseModel):
    """A print template ("modèle") — QR card, business card, sticker, poster…
    Optionally backed by an imported PDF used as the background artwork; the
    QR zone and text zones are stamped on top by TemplateComposer."""
    id: UUID = Field(default_factory=uuid4)
    name: str = "Nouveau modèle"
    width_mm: float = 85.0
    height_mm: float = 55.0
    base_pdf: Optional[Path] = None
    qr_zone: TemplateQRZone = Field(default_factory=TemplateQRZone)
    texts: List[TemplateTextZone] = Field(default_factory=list)
    # Archived templates are hidden from pickers but kept on disk for reuse.
    archived: bool = False


class ProductPreset(BaseModel):
    """A manufacturing preset ("gamme") — everything a recurring product needs
    (sheet size, spacing, margins, ARMS marks, CutContour, export format…)
    bundled under one name, selectable in one click at job creation instead of
    re-entering the global settings for each order."""
    id: UUID = Field(default_factory=uuid4)
    name: str = "Nouvelle gamme"
    support: str = ""  # media note for the operator (e.g. "Vinyle blanc 80µ")
    settings: JobSettings = Field(default_factory=JobSettings)
    archived: bool = False


class WatchRule(BaseModel):
    """One watched folder bound to a product preset: drop files in it and the
    job is created with that gamme's whole recipe — the unattended 24/7 mode.
    An empty preset_id means "use the global settings"."""
    id: UUID = Field(default_factory=uuid4)
    name: str = "Nouvelle règle"
    folder: str = ""
    preset_id: str = ""
    enabled: bool = True


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
