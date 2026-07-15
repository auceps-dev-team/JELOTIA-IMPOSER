import logging
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightErrorType,
    PreflightStatus,
)

logger = logging.getLogger(__name__)


class CorrectionEngine:
    """
    Engine responsible for applying automatic corrections to files
    that have generated WARNINGs during the preflight phase.
    """

    def __init__(self, settings: JobSettings, work_dir: Path):
        """
        :param settings: JobSettings containing correction preferences.
        :param work_dir: Directory where corrected files will be saved.
        """
        self.settings = settings
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def process(self, file_item: FileItem) -> FileItem:
        """
        Processes a FileItem. If it has WARNINGS, applies corrections and returns
        a new FileItem pointing to the corrected file. If OK, returns it as is.
        If ERROR, returns it as is (cannot be automatically corrected).
        """
        if file_item.preflight_status != PreflightStatus.WARNING:
            return file_item

        # Determine which corrections are needed based on preflight errors
        needs_cmyk = any(
            e.type == PreflightErrorType.WRONG_COLOR_MODE for e in file_item.preflight_errors
        )
        needs_flattening = any(
            e.type == PreflightErrorType.TRANSPARENCY_DETECTED for e in file_item.preflight_errors
        )
        needs_dpi_fix = any(
            e.type == PreflightErrorType.RESOLUTION_LOW for e in file_item.preflight_errors
        )

        # If no actionable warnings, just return
        if not (needs_cmyk or needs_flattening or needs_dpi_fix):
            return file_item

        corrected_item = file_item.model_copy()

        try:
            if file_item.format in [FileFormat.PNG, FileFormat.JPEG, FileFormat.TIFF]:
                new_path = self._correct_image(
                    corrected_item, needs_cmyk, needs_flattening, needs_dpi_fix
                )
            elif file_item.format == FileFormat.PDF:
                new_path = self._correct_pdf(corrected_item, needs_cmyk, needs_flattening, needs_dpi_fix)
            else:
                return file_item
        except Exception:
            # In a production setting we should log the error `e`
            return file_item

        # Update the corrected item properties
        corrected_item.path = new_path
        corrected_item.preflight_status = PreflightStatus.OK
        corrected_item.preflight_errors = []

        if needs_cmyk and self.settings.force_cmyk:
            corrected_item.color_mode = ColorMode.CMYK

        if needs_dpi_fix:
            corrected_item.dpi = max(file_item.dpi, self.settings.min_dpi)

        return corrected_item

    def _to_cmyk(self, img: "Image.Image") -> "Image.Image":
        """CMYK conversion through the configured ICC profile, with an honest
        fallback: without a profile we keep Pillow's naive conversion rather
        than fail the job, but the log says the output is not colour-managed."""
        profile = (self.settings.icc_profile_path or "").strip()
        if not profile:
            logger.warning(
                "Aucun profil ICC configuré — conversion CMJN approximative "
                "(F6·CONFIG > Exportation). L'encrage peut dépasser les limites RIP."
            )
            return img.convert("CMYK")

        from src.core.engines.icc_engine import ICCError, convert_image_to_cmyk

        try:
            return convert_image_to_cmyk(img, Path(profile))
        except ICCError as e:
            logger.error(f"{e} — conversion CMJN approximative utilisée à la place")
            return img.convert("CMYK")

    def _correct_image(self, file_item: FileItem, cmyk: bool, flatten: bool, dpi: bool) -> Path:
        """
        Applies corrections to raster images using Pillow.
        """
        img: Image.Image = Image.open(file_item.path)

        # Flattening (Remove Alpha channel)
        if flatten or img.mode in ("RGBA", "LA", "P"):
            if img.mode == "RGBA":
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])  # 3 is the alpha channel
                img = background
            elif img.mode == "LA":
                background = Image.new("L", img.size, 255)
                background.paste(img.split()[0], mask=img.split()[1])
                img = background.convert("RGB")
            else:
                img = img.convert("RGB")

        # Colour conversion — through a real ICC profile when one is
        # configured. Pillow's img.convert("CMYK") is a naive formula that
        # turns pure black into C+M+Y+K = 300 % ink (undryable, RIP-rejected);
        # the ICC path gives a clean 100K black. Falls back to the naive
        # conversion only when no profile is available, and says so.
        if cmyk and self.settings.force_cmyk and img.mode != "CMYK":
            img = self._to_cmyk(img)

        # Resampling DPI
        target_dpi = (file_item.dpi, file_item.dpi)
        if dpi and file_item.dpi < self.settings.min_dpi:
            target_dpi = (self.settings.min_dpi, self.settings.min_dpi)
            scale_factor = self.settings.min_dpi / file_item.dpi
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            img = img.resize(new_size, resample=Image.Resampling.LANCZOS)
            file_item.dpi = self.settings.min_dpi

        # NOTE: bleed is NOT added here. This used to pad the artwork with a
        # WHITE frame and call it bleed — the exact sliver that bleed exists to
        # prevent. It now happens after correction, in BleedEngine (mirrored
        # edges for rasters, stretched vector edges for PDFs); doing it in both
        # places would also apply it twice.

        new_filename = f"corrected_{file_item.id}.tif"
        new_path = self.work_dir / new_filename

        img.save(new_path, format="TIFF", dpi=target_dpi)
        return new_path

    def _correct_pdf(self, file_item: FileItem, cmyk: bool, flatten: bool, dpi: bool) -> Path:
        """
        Applies corrections to PDF files using PyMuPDF.
        Rasterizes the PDF page to a Pixmap and saves it back as a PDF.
        """
        doc = fitz.open(file_item.path)
        page = doc[0]

        target_dpi = self.settings.min_dpi if dpi else max(file_item.dpi, 72)

        colorspace = fitz.csCMYK if (cmyk and self.settings.force_cmyk) else fitz.csRGB

        # alpha=False guarantees flattening (background will be white)
        pix = page.get_pixmap(dpi=target_dpi, colorspace=colorspace, alpha=False)

        new_doc = fitz.open()

        # Calculate dimensions in points (1/72 inch)
        width_pt = (pix.width / target_dpi) * 72
        height_pt = (pix.height / target_dpi) * 72

        bleed_pt = 0.0
        if self.settings.add_bleed_mm > 0:
            bleed_pt = (self.settings.add_bleed_mm / 25.4) * 72
            file_item.width_mm += 2 * self.settings.add_bleed_mm
            file_item.height_mm += 2 * self.settings.add_bleed_mm

        new_width_pt = width_pt + 2 * bleed_pt
        new_height_pt = height_pt + 2 * bleed_pt

        rect = fitz.Rect(bleed_pt, bleed_pt, bleed_pt + width_pt, bleed_pt + height_pt)

        new_page = new_doc.new_page(width=new_width_pt, height=new_height_pt)
        new_page.insert_image(rect, pixmap=pix)

        new_filename = f"corrected_{file_item.id}.pdf"
        new_path = self.work_dir / new_filename

        new_doc.save(new_path)
        new_doc.close()
        doc.close()

        return new_path
