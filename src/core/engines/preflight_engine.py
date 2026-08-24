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

    @staticmethod
    def _image_has_alpha(img_dict: dict) -> bool:
        """True when an extracted image really carries transparency.

        PyMuPDF exposes the soft mask under `smask` (an xref, 0 when absent) —
        never under `alpha`. Testing `colorspace == 4` is worse than useless
        here: 4 means four components, i.e. CMYK, so it flagged every correct
        production file as transparent and taught operators to ignore preflight.
        `alpha` is still honoured in case a future version starts emitting it.
        """
        return bool(img_dict.get("smask")) or img_dict.get("alpha") in (True, 1)

    @staticmethod
    def _font_is_embedded(font_tuple: tuple) -> bool:
        """True when a `page.get_fonts()` entry describes an embedded font.

        The tuple is (xref, ext, type, basefont, name, encoding, referencer).
        The field that tells embedding apart is `ext` (index 1): it names the
        embedded file's format ("ttf", "cff"…) and is the literal "n/a" when the
        font is only referenced. `type` (index 2) is the PDF font type — always
        "Type1"/"Type0"/"TrueType" — and never distinguishes the two cases.
        """
        return len(font_tuple) > 1 and font_tuple[1] != "n/a"

    def _analyze_pdf_deep(self, item: FileItem, settings: JobSettings) -> None:
        """Opens the PDF and checks embedded fonts and transparency.

        Scans every page: ImportEngine currently creates one FileItem per page
        but they all reference the same file, so there is no page index to
        narrow this down to.
        """
        doc = None
        try:
            doc = fitz.open(item.path)

            has_transparency = False
            missing_fonts: list[str] = []

            for page in doc:
                for font_tuple in page.get_fonts():
                    if not self._font_is_embedded(font_tuple):
                        # index 3 = basefont, the name the operator recognises
                        name = font_tuple[3] if len(font_tuple) > 3 else "?"
                        if name not in missing_fonts:
                            missing_fonts.append(name)

                if not has_transparency:
                    for img_tuple in page.get_images():
                        if self._image_has_alpha(doc.extract_image(img_tuple[0])):
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

            if missing_fonts:
                item.preflight_errors.append(
                    PreflightError(
                        type=PreflightErrorType.FONTS_NOT_EMBEDDED,
                        message=(
                            "Police(s) non embarquée(s) : "
                            + ", ".join(missing_fonts)
                            + " — le RIP les remplacera."
                        ),
                        is_blocking=False,
                    )
                )
        except fitz.FileDataError as e:
            item.preflight_errors.append(
                PreflightError(
                    type=PreflightErrorType.CORRUPTED,
                    message=f"PDF FileDataError during deep analysis: {str(e)}",
                    is_blocking=True,
                )
            )
        finally:
            # Closed here rather than after the checks: an exception mid-scan
            # would otherwise leak the open document.
            if doc is not None:
                doc.close()
