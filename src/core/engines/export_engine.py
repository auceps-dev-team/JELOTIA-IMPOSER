import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

import fitz  # PyMuPDF
import pikepdf
from PIL import Image

from src.core.models.domain import JobSettings, Sheet

logger = logging.getLogger(__name__)


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
            ext = ".tiff"
        elif fmt == "JPEG":
            ext = ".jpg"

        base_name = _slugify(job_name) if job_name else job_id_str
        final_filename = f"{base_name}_planche_{sheet.sheet_number:02d}{ext}"
        final_path = output_dir / final_filename

        try:
            if fmt in ["PDF/X-1A", "PDF/X-4", "PDF"]:
                self._export_pdfx(base_pdf_path, final_path, fmt)
            elif fmt in ["TIFF", "JPEG"]:
                self._export_raster(base_pdf_path, final_path, fmt, settings.export_dpi)
            else:
                logger.warning(f"Unknown export format {fmt}. Defaulting to standard copy.")
                final_path.write_bytes(base_pdf_path.read_bytes())
                
            return final_path
        except Exception as e:
            logger.error(f"Error during export of {base_pdf_path} to {fmt}: {e}")
            raise

    def _export_pdfx(self, input_path: Path, output_path: Path, format_type: str):
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
                
                intent_dict = pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/OutputIntent"),
                    "/S": pikepdf.Name("/GTS_PDFX"),
                    "/OutputConditionIdentifier": "FOGRA39",
                    "/RegistryName": "http://www.color.org",
                    "/Info": "FOGRA39 (ISO 12647-2:2004)"
                })
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

    def _export_raster(self, input_path: Path, output_path: Path, format_type: str, dpi: int):
        """
        Rasterizes the PDF to TIFF or JPEG at the requested DPI in CMYK.
        """
        try:
            doc = fitz.open(str(input_path))
            if len(doc) == 0:
                raise ValueError("Source PDF has no pages")
                
            page = doc[0]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csCMYK, alpha=False)
            img = Image.frombytes("CMYK", [pix.width, pix.height], pix.samples)
            
            if format_type == "TIFF":
                img.save(str(output_path), format="TIFF", compression="tiff_lzw", dpi=(dpi, dpi))
            elif format_type == "JPEG":
                img.save(str(output_path), format="JPEG", quality=95, dpi=(dpi, dpi))
                
            doc.close()
            logger.info(f"Exported {format_type} ({dpi} dpi) to {output_path}")
        except Exception as e:
            logger.error(f"Raster export failed: {e}")
            raise
