import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

import fitz  # PyMuPDF
import pikepdf
from PIL import Image

from src.core.models.domain import JobSettings, Sheet

_RASTER_EXTS = {".tiff", ".tif", ".jpg", ".jpeg"}

logger = logging.getLogger(__name__)


def _software_tag() -> str:
    """Value for the TIFF Software tag. Names this application honestly — some
    RIPs log it, and claiming to be another vendor's product would be a lie
    about the file's provenance."""
    try:
        from src._version import __version__

        return f"Jelotia Imposer {__version__}"
    except Exception:
        return "Jelotia Imposer"


def _slugify(name: str) -> str:
    """Lowercase, filesystem-safe slug: spaces/special chars collapse to '_'."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    return slug or "job"


class ExportEngine:
    """
    ExportEngine post-processes the base PDF sheet to the final targeted output format (PDF/X, TIFF, JPEG).
    """

    def export_sheet(
        self,
        job_id: UUID,
        sheet: Sheet,
        base_pdf_path: Path,
        settings: JobSettings,
        output_dir: Path,
        job_name: str | None = None,
    ) -> Path:
        """
        Exports the base PDF sheet according to JobSettings.
        Returns the path to the newly created exported file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        job_id_str = str(job_id)[:8]

        # Decide extension based on format
        fmt = settings.export_format.upper()
        ext = ".pdf"
        if fmt == "TIFF":
            # Three letters, like Photoshop: legacy import filters (Maintop and
            # other older RIPs) match on "*.tif" and never see a ".tiff" file.
            ext = ".tif"
        elif fmt == "JPEG":
            ext = ".jpg"

        base_name = _slugify(job_name) if job_name else job_id_str
        final_filename = f"{base_name}_planche_{sheet.sheet_number:02d}{ext}"
        final_path = output_dir / final_filename

        try:
            if fmt in ["PDF/X-1A", "PDF/X-4", "PDF"]:
                if getattr(settings, "pdf_rasterize", False):
                    # Render as CMYK raster and wrap for older RIPs (removes transparencies)
                    tmp_raster = output_dir / f"temp_raster_{job_id_str}_{sheet.sheet_number:02d}.tiff"
                    self._export_raster(base_pdf_path, tmp_raster, "TIFF", settings.export_dpi, settings)
                    wrapped = self._wrap_raster_as_pdf(tmp_raster, sheet)
                    self._export_pdfx(wrapped, final_path, fmt, settings)
                    tmp_raster.unlink(missing_ok=True)
                    wrapped.unlink(missing_ok=True)
                else:
                    self._export_pdfx(base_pdf_path, final_path, fmt, settings)
            elif fmt in ["TIFF", "JPEG"]:
                self._export_raster(base_pdf_path, final_path, fmt, settings.export_dpi, settings)
            else:
                logger.warning(f"Unknown export format {fmt}. Defaulting to standard copy.")
                final_path.write_bytes(base_pdf_path.read_bytes())
                
            return final_path
        except Exception as e:
            logger.error(f"Error during export of {base_pdf_path} to {fmt}: {e}")
            raise

    def convert_existing(
        self,
        job_id: UUID,
        sheet: Sheet,
        existing_path: Path,
        settings: JobSettings,
        output_dir: Path,
        job_name: Optional[str] = None,
    ) -> Path:
        """
        Converts an already-rendered sheet export (PDF, TIFF or JPEG) to the
        format in `settings.export_format`, without touching the original
        artwork. Use this instead of re-stamping from PlacedItem source files
        when the layout hasn't changed (grouped export, quick format export) —
        those source files are often ephemeral (deleted once the job's own
        export completes) while `existing_path` (the job's own output) is not.
        """
        fmt = settings.export_format.upper()
        existing_is_raster = existing_path.suffix.lower() in _RASTER_EXTS

        if existing_is_raster and fmt in ("TIFF", "JPEG"):
            return self._convert_raster_to_raster(sheet, existing_path, settings, output_dir, job_name)

        wrapped_pdf = None
        try:
            base_pdf_path = existing_path
            if existing_is_raster:
                wrapped_pdf = self._wrap_raster_as_pdf(existing_path, sheet)
                base_pdf_path = wrapped_pdf
            return self.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir, job_name=job_name)
        finally:
            if wrapped_pdf is not None:
                wrapped_pdf.unlink(missing_ok=True)

    def _convert_raster_to_raster(
        self, sheet: Sheet, existing_path: Path, settings: JobSettings, output_dir: Path, job_name: Optional[str]
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        fmt = settings.export_format.upper()
        ext = ".tif" if fmt == "TIFF" else ".jpg"
        base_name = _slugify(job_name) if job_name else str(sheet.job_id)[:8]
        final_path = output_dir / f"{base_name}_planche_{sheet.sheet_number:02d}{ext}"

        profile = self._resolve_cmyk_profile(settings)
        with Image.open(existing_path) as img:
            if img.mode != "CMYK":
                # Same rule as _render_cmyk: colorimetric when a profile exists,
                # never the naive convert() which floods blacks with ink.
                if profile is not None:
                    from src.core.engines.icc_engine import convert_image_to_cmyk

                    try:
                        img = convert_image_to_cmyk(img, profile)
                    except Exception as e:
                        logger.error(f"Conversion ICC échouée : {e} — repli approximatif.")
                        img = img.convert("CMYK")
                else:
                    logger.warning("Conversion CMJN sans profil ICC : fichier non balisé.")
                    img = img.convert("CMYK")
            elif profile is not None and not img.info.get("icc_profile"):
                # Already CMYK but untagged — declare the space without re-converting.
                img.info["icc_profile"] = Path(profile).read_bytes()
            self._save_raster(img, final_path, fmt, settings.export_dpi, settings)

        logger.info(f"Converted {existing_path.name} -> {fmt} at {final_path}")
        return final_path

    def _wrap_raster_as_pdf(self, image_path: Path, sheet: Sheet) -> Path:
        """Embeds a raster image (TIFF/JPEG) into a minimal one-page PDF sized
        to the sheet, so the rest of the pipeline (PDF/X metadata, rasterization
        to another format) can operate uniformly regardless of the original
        export format."""
        doc = fitz.open()
        page = doc.new_page(width=sheet.width_mm * 2.83465, height=sheet.height_mm * 2.83465)
        page.insert_image(page.rect, filename=str(image_path))

        fd, tmp_name = tempfile.mkstemp(suffix=".pdf", prefix="wrapped_")
        os.close(fd)
        tmp_path = Path(tmp_name)
        doc.save(str(tmp_path))
        doc.close()
        return tmp_path

    def _export_pdfx(
        self,
        input_path: Path,
        output_path: Path,
        format_type: str,
        settings: Optional[JobSettings] = None,
    ):
        """
        Modifies the base PDF to include PDF/X metadata using pikepdf.
        Note: Perfect transparency flattening for PDF/X-1a is complex and not fully implemented here.
        We focus on OutputIntents and basic metadata conformance.
        """
        try:
            with pikepdf.Pdf.open(input_path) as pdf:
                # Add basic metadata
                with pdf.open_metadata() as meta:
                    meta["dc:title"] = f"Sheet Export {output_path.stem}"
                    meta["dc:creator"] = ["Jelotia Imposer"]
                    meta["xmp:CreateDate"] = datetime.now().isoformat()

                # Setup OutputIntent for PDF/X
                output_intents = pikepdf.Array()

                profile = self._resolve_cmyk_profile(settings)
                condition, info = self._output_condition(profile)
                intent_dict = pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/OutputIntent"),
                    "/S": pikepdf.Name("/GTS_PDFX"),
                    "/OutputConditionIdentifier": condition,
                    "/RegistryName": "http://www.color.org",
                    "/Info": info,
                })
                # PDF/X requires the output condition's ICC profile to be
                # EMBEDDED as /DestOutputProfile. Declaring a condition without
                # shipping the profile makes the file non-conformant, and
                # preflight tools and RIPs reject it on that alone.
                if profile is not None:
                    try:
                        stream = pdf.make_stream(Path(profile).read_bytes())
                        stream["/N"] = 4  # CMYK components
                        intent_dict["/DestOutputProfile"] = stream
                    except Exception as e:
                        logger.error(f"Profil ICC non embarqué dans le PDF/X : {e}")
                else:
                    logger.warning(
                        "PDF/X sans profil ICC embarqué : fichier non conforme. "
                        "Choisissez un profil CMJN dans F6·CONFIG."
                    )
                output_intents.append(intent_dict)
                pdf.Root.OutputIntents = output_intents

                # Set PDF/X version string in the document's real Info dictionary
                # (trailer /Info via pikepdf's docinfo), not on the Catalog — a RIP
                # or preflight tool looks for GTS_PDFXVersion there and will reject
                # the file as non-conformant if it's missing.
                if format_type == "PDF/X-1A":
                    pdf.docinfo["/GTS_PDFXVersion"] = pikepdf.String("PDF/X-1a:2001")
                elif format_type == "PDF/X-4":
                    pdf.docinfo["/GTS_PDFXVersion"] = pikepdf.String("PDF/X-4")

                pdf.save(output_path)
            logger.info(f"Exported {format_type} to {output_path}")
        except Exception as e:
            logger.error(f"PDF/X export failed: {e}")
            raise

    def _resolve_cmyk_profile(self, settings: Optional[JobSettings]) -> Optional[Path]:
        """The CMYK profile to convert to AND embed in the exported raster.

        The operator's configured profile wins; otherwise the first CMYK profile
        installed on the machine. Falling back matters: an untagged CMYK TIFF has
        no declared colour space, and print software / RIPs reject or mis-read it.
        """
        configured = getattr(settings, "icc_profile_path", "") or ""
        if configured and Path(configured).is_file():
            return Path(configured)
        try:
            from src.core.engines.icc_engine import discover_profiles

            found = discover_profiles(cmyk_only=True)
            if found:
                logger.info(f"Aucun profil configuré, repli sur {found[0].name}")
                return found[0].path
        except Exception as e:  # profile discovery must never break an export
            logger.debug(f"Découverte de profils ICC impossible : {e}")
        return None

    def _output_condition(self, profile: Optional[Path]) -> tuple:
        """(OutputConditionIdentifier, /Info) describing the intended press.

        Derived from the profile actually used, so the PDF stops claiming
        FOGRA39 when the operator selected something else entirely.
        """
        if profile is not None:
            try:
                from src.core.engines.icc_engine import read_profile

                info = read_profile(Path(profile))
                if info is not None and info.name:
                    return info.name, info.name
            except Exception as e:
                logger.debug(f"Description du profil illisible : {e}")
            return Path(profile).stem, Path(profile).stem
        return "FOGRA39", "FOGRA39 (ISO 12647-2:2004)"

    def _render_cmyk(self, page, mat, profile: Optional[Path]):
        """Page -> CMYK PIL image, colour-managed when a profile is available.

        PyMuPDF's csCMYK (like Pillow's convert) is the naive formula: it turns a
        pure black into ~295 % total ink instead of a clean 100 % K, which a RIP
        refuses. Going through littleCMS with a real profile fixes both the ink
        load and the missing colour-space tag.
        """
        if profile is not None:
            from src.core.engines.icc_engine import convert_image_to_cmyk

            try:
                pix = page.get_pixmap(matrix=mat, alpha=False)  # RGB
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                return convert_image_to_cmyk(img, profile)
            except Exception as e:
                logger.error(
                    f"Conversion ICC échouée ({Path(profile).name}) : {e} — "
                    "repli sur la conversion approximative."
                )

        logger.warning(
            "Export CMJN sans profil ICC : fichier non balisé et encrage "
            "approximatif. Choisissez un profil CMJN dans F6·CONFIG."
        )
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csCMYK, alpha=False)
        return Image.frombytes("CMYK", [pix.width, pix.height], pix.samples)

    def _export_raster(
        self,
        input_path: Path,
        output_path: Path,
        format_type: str,
        dpi: int,
        settings: Optional[JobSettings] = None,
    ):
        """
        Rasterizes the PDF to TIFF or JPEG at the requested DPI in CMYK, colour
        managed through the destination ICC profile and tagged with it.
        """
        doc = None
        try:
            doc = fitz.open(str(input_path))
            if len(doc) == 0:
                raise ValueError("Source PDF has no pages")

            page = doc[0]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)

            profile = self._resolve_cmyk_profile(settings)
            img = self._render_cmyk(page, mat, profile)
            self._save_raster(img, output_path, format_type, dpi, settings)

            logger.info(f"Exported {format_type} ({dpi} dpi) to {output_path}")
        except Exception as e:
            logger.error(f"Raster export failed: {e}")
            raise
        finally:
            if doc is not None:
                doc.close()

    def _save_raster(self, img, output_path: Path, format_type: str, dpi: int, settings: Optional[JobSettings] = None):
        """Writes the image, embedding its ICC profile so the colour space is
        declared — the tag print software looks for."""
        options = {"dpi": (dpi, dpi)}
        icc = img.info.get("icc_profile")
        if icc:
            options["icc_profile"] = icc
            
        if format_type == "TIFF":
            from src.core.engines.photoshop_tiff import save_tiff

            compression = getattr(settings, "tiff_compression", "tiff_lzw") if settings else "tiff_lzw"
            # Compat mode drops the ICC tag for decoders that choke on it; the
            # baseline CMYK tags (InkSet/NumberOfInks) are always written.
            photoshop_compat = getattr(settings, "tiff_photoshop_compat", False) if settings else False
            save_tiff(
                img,
                output_path,
                dpi,
                compression=compression,
                software=_software_tag(),
                icc_profile=None if photoshop_compat else icc,
            )
        elif format_type == "JPEG":
            jpeg_color = getattr(settings, "jpeg_color_mode", "CMYK") if settings else "CMYK"
            if jpeg_color == "RGB" and img.mode == "CMYK":
                img = img.convert("RGB")
                options.pop("icc_profile", None)  # RGB doesn't use the CMYK profile
            img.save(str(output_path), format="JPEG", quality=95, **options)
