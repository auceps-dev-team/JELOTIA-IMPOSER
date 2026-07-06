from pathlib import Path
from typing import List, Union
from uuid import UUID

import fitz
from loguru import logger
from PIL import Image, UnidentifiedImageError

from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    PreflightError,
    PreflightErrorType,
    PreflightStatus,
)


class ImportEngine:
    """Handles parsing input files and extracting metadata into FileItems."""

    def process_file(
        self, job_id: UUID, file_path: Union[str, Path], min_dpi: int = 300
    ) -> List[FileItem]:
        """
        Detects file type and processes it into one or multiple FileItems.
        Multi-page PDFs return multiple items.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return self._create_corrupted_item(job_id, file_path, "File not found")

        ext = file_path.suffix.lower()
        try:
            if ext == ".pdf":
                return self._process_pdf(job_id, file_path, min_dpi)
            elif ext in [".png", ".jpg", ".jpeg", ".tif", ".tiff"]:
                return self._process_image(job_id, file_path)
            else:
                return self._create_corrupted_item(job_id, file_path, f"Unsupported format: {ext}")
        except Exception as e:
            logger.exception(f"Error processing file {file_path}: {e}")
            return self._create_corrupted_item(job_id, file_path, str(e))

    def _process_pdf(self, job_id: UUID, file_path: Path, min_dpi: int) -> List[FileItem]:
        items = []
        try:
            doc = fitz.open(file_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                rect = page.rect

                # Dimensions in points (1/72 inch). 1 inch = 25.4 mm
                width_mm = (rect.width / 72.0) * 25.4
                height_mm = (rect.height / 72.0) * 25.4

                color_mode, effective_dpi = self._inspect_page_images(page, min_dpi)

                item = FileItem(
                    job_id=job_id,
                    path=file_path,
                    format=FileFormat.PDF,
                    width_mm=round(width_mm, 2),
                    height_mm=round(height_mm, 2),
                    dpi=effective_dpi,
                    color_mode=color_mode,
                    quantity=1,
                )
                items.append(item)
            doc.close()
        except fitz.FileDataError as e:
            raise Exception(f"PDF FileDataError: {str(e)}")

        return items

    def _inspect_page_images(self, page, default_dpi: int) -> tuple:
        """Inspects embedded raster images on a PDF page to determine the real
        (worst-case) color mode and effective resolution. Pages with no raster
        images (pure vector) fall back to CMYK/default_dpi, since there is no
        source-color or resampling concern for vector content."""
        color_mode = ColorMode.CMYK
        lowest_dpi = None

        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            width_px, height_px = info.get("width", 0), info.get("height", 0)
            if not bbox or not width_px or not height_px:
                continue

            cs_name = info.get("cs-name", "")
            if cs_name == "DeviceRGB":
                color_mode = ColorMode.RGB
            elif cs_name == "DeviceGray" and color_mode == ColorMode.CMYK:
                color_mode = ColorMode.GRAY

            # Effective DPI from the actual placed size, not the (often bogus)
            # embedded xres/yres metadata.
            bbox_width_in = (bbox[2] - bbox[0]) / 72.0
            bbox_height_in = (bbox[3] - bbox[1]) / 72.0
            if bbox_width_in > 0 and bbox_height_in > 0:
                image_dpi = min(width_px / bbox_width_in, height_px / bbox_height_in)
                if lowest_dpi is None or image_dpi < lowest_dpi:
                    lowest_dpi = image_dpi

        if lowest_dpi is None:
            return color_mode, default_dpi
        return color_mode, round(lowest_dpi)

    def _process_image(self, job_id: UUID, file_path: Path) -> List[FileItem]:
        items = []
        try:
            with Image.open(file_path) as img:
                ext = file_path.suffix.lower()
                if ext in [".tif", ".tiff"]:
                    fmt = FileFormat.TIFF
                elif ext in [".jpg", ".jpeg"]:
                    fmt = FileFormat.JPEG
                else:
                    fmt = FileFormat.PNG

                dpi_tuple = img.info.get("dpi", (72, 72))
                dpi = int(dpi_tuple[0]) if isinstance(dpi_tuple, tuple) else int(dpi_tuple)

                width_px, height_px = img.size
                width_mm = (width_px / dpi) * 25.4
                height_mm = (height_px / dpi) * 25.4

                mode = img.mode
                if mode == "CMYK":
                    color_mode = ColorMode.CMYK
                elif mode in ["L", "1"]:
                    color_mode = ColorMode.GRAY
                else:
                    color_mode = ColorMode.RGB

                item = FileItem(
                    job_id=job_id,
                    path=file_path,
                    format=fmt,
                    width_mm=round(width_mm, 2),
                    height_mm=round(height_mm, 2),
                    dpi=dpi,
                    color_mode=color_mode,
                    quantity=1,
                )
                items.append(item)
        except UnidentifiedImageError:
            raise Exception("Cannot identify image file")

        return items

    def _create_corrupted_item(self, job_id: UUID, file_path: Path, message: str) -> List[FileItem]:
        err = PreflightError(type=PreflightErrorType.CORRUPTED, message=message, is_blocking=True)

        item = FileItem(
            job_id=job_id,
            path=file_path,
            format=FileFormat.PDF,
            width_mm=0.0,
            height_mm=0.0,
            dpi=0,
            color_mode=ColorMode.RGB,
            preflight_status=PreflightStatus.ERROR,
            preflight_errors=[err],
        )
        return [item]
