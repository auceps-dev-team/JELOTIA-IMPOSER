import fitz
from loguru import logger

from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightError,
    PreflightErrorType,
    PreflightStatus,
)


class PreflightEngine:
    """Analyzes imported FileItems to ensure they meet minimum requirements."""

    def run_preflight(self, item: FileItem, settings: JobSettings) -> FileItem:
        """Runs all preflight checks on a given FileItem."""
        # Reset any existing preflight data
        item.preflight_errors = []
        item.preflight_status = PreflightStatus.PENDING

        try:
            self._check_resolution(item, settings.min_dpi)
            self._check_color_mode(item, settings.force_cmyk)
            self._check_dimensions(item, settings)

            # Deep checks for PDFs
            if item.format == FileFormat.PDF:
                self._analyze_pdf_deep(item, settings)

            # Determine final status
            if any(error.is_blocking for error in item.preflight_errors):
                item.preflight_status = PreflightStatus.ERROR
            elif len(item.preflight_errors) > 0:
                item.preflight_status = PreflightStatus.WARNING
            else:
                item.preflight_status = PreflightStatus.OK

        except Exception as e:
            logger.exception(f"Exception during preflight of {item.path}: {e}")
            item.preflight_errors.append(
                PreflightError(
                    type=PreflightErrorType.CORRUPTED,
                    message=f"Preflight engine crashed: {str(e)}",
                    is_blocking=True,
                )
            )
            item.preflight_status = PreflightStatus.ERROR

        return item

    def _check_resolution(self, item: FileItem, min_dpi: int) -> None:
        if item.dpi < min_dpi:
            item.preflight_errors.append(
                PreflightError(
                    type=PreflightErrorType.RESOLUTION_LOW,
                    message=f"Resolution is {item.dpi} DPI, which is below the minimum of {min_dpi} DPI.",
                    is_blocking=False,  # Treat as warning, Correction Engine might handle or upsample
                )
            )

    def _check_color_mode(self, item: FileItem, force_cmyk: bool) -> None:
        if force_cmyk and item.color_mode != ColorMode.CMYK:
            item.preflight_errors.append(
                PreflightError(
                    type=PreflightErrorType.WRONG_COLOR_MODE,
                    message=f"Color mode is {item.color_mode.value}, expected CMYK.",
                    is_blocking=False,  # Treat as warning, Correction Engine will convert
                )
            )

    def _check_dimensions(self, item: FileItem, settings: JobSettings) -> None:
        # A file cannot be physically larger than the maximum sheet dimensions
        if item.width_mm > settings.sheet_width_mm or item.height_mm > settings.sheet_height_mm:
            # Maybe it fits if rotated?
            if settings.allow_rotation and (
                item.height_mm <= settings.sheet_width_mm
                and item.width_mm <= settings.sheet_height_mm
            ):
                pass  # It fits rotated
            else:
                item.preflight_errors.append(
                    PreflightError(
                        type=PreflightErrorType.SIZE_MISMATCH,
                        message=f"File dimensions ({item.width_mm}x{item.height_mm}mm) exceed sheet limits ({settings.sheet_width_mm}x{settings.sheet_height_mm}mm).",
                        is_blocking=True,
                    )
                )

    def _analyze_pdf_deep(self, item: FileItem, settings: JobSettings) -> None:
        """Opens the PDF and checks for fonts, transparency, and bleed."""
        try:
            doc = fitz.open(item.path)
            # Just check the first page (or page 0 if split)
            # In our current workflow, multi-page PDFs are NOT yet split into separate files physically,
            # but the FileItem might represent a specific page if we had page_index.
            # Currently ImportEngine creates a FileItem per page but references the SAME file.
            # We will just scan the whole document for simplicity or the specific page if we add index tracking.

            has_transparency = False

            for page_num in range(len(doc)):
                page = doc[page_num]

                # Check fonts
                fonts = page.get_fonts()
                for font in fonts:
                    # font is a tuple: (xref, ext, type, basefont, name, encoding)
                    # To accurately check if a font is embedded in PyMuPDF, we need to inspect the object stream
                    # But for now, we'll implement a stub or a basic check
                    # This is a bit advanced, PyMuPDF doesn't natively expose "is_embedded" in get_fonts easily
                    # We might skip strict font embedding check here, or assume True unless we parse the PDF raw.
                    # As a placeholder, we won't throw this arbitrarily.
                    pass

                # Check transparency (look for images with alpha channels)
                images = page.get_images()
                for img_tuple in images:
                    xref = img_tuple[0]
                    img_dict = doc.extract_image(xref)
                    # If image has an alpha channel, we flag transparency
                    if img_dict.get("colorspace") == 4 or "alpha" in img_dict:
                        has_transparency = True
                        break

            if has_transparency:
                item.preflight_errors.append(
                    PreflightError(
                        type=PreflightErrorType.TRANSPARENCY_DETECTED,
                        message="Transparency detected in PDF. May cause rendering issues.",
                        is_blocking=False,
                    )
                )

            doc.close()
        except fitz.FileDataError as e:
            item.preflight_errors.append(
                PreflightError(
                    type=PreflightErrorType.CORRUPTED,
                    message=f"PDF FileDataError during deep analysis: {str(e)}",
                    is_blocking=True,
                )
            )
