import io
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

import fitz  # PyMuPDF
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from src.core.models.domain import JobSettings, Sheet

logger = logging.getLogger(__name__)


class LayoutEngine:
    """
    Generates the final imposed PDF sheet combining ReportLab (vector marks, QR)
    and PyMuPDF (artwork embedding). Also produces thumbnails and optional cut layers.
    """

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def generate_sheet_pdf(
        self, job_id: UUID, sheet: Sheet, settings: JobSettings, export_dir: Path
    ) -> Path:
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"job_{str(job_id)[:8]}_sheet_{sheet.sheet_number}.pdf"

        # 1. Base canvas with ReportLab (marks, metadata, QR)
        packet = self._build_base_canvas(job_id, sheet, settings)

        # 2. Stamp artwork via PyMuPDF
        base_pdf = fitz.open("pdf", packet)
        base_page = base_pdf[0]
        self._stamp_artwork(base_page, sheet)

        # 3. CutContour spot overlay ON TOP of the artwork (RIPs extract the
        # spot; drawn under the artwork it would be partially covered). The
        # overlay doc must stay open until the target is saved (fitz rule).
        overlay_doc = None
        if settings.cut_contour_spot and sheet.items:
            overlay_doc = self._cut_contour_overlay(sheet)
            base_page.show_pdf_page(base_page.rect, overlay_doc, 0)

        base_pdf.save(str(export_path))
        base_pdf.close()
        if overlay_doc is not None:
            overlay_doc.close()

        logger.info(f"Generated sheet PDF: {export_path}")
        return export_path

    def process_job_layout(
        self, job_id: UUID, sheets: List[Sheet], settings: JobSettings, export_dir: Path
    ) -> List[Sheet]:
        for sheet in sheets:
            pdf_path = self.generate_sheet_pdf(job_id, sheet, settings, export_dir)
            sheet.export_path = pdf_path

            if settings.generate_thumbnail:
                sheet.thumbnail_path = self._generate_thumbnail(pdf_path, export_dir)

            if settings.separate_cut_layer:
                sheet.cut_layer_path = self._generate_cut_layer(
                    job_id, sheet, settings, export_dir
                )

        return sheets

    # ------------------------------------------------------------------ #
    #  ReportLab canvas                                                    #
    # ------------------------------------------------------------------ #

    def _build_base_canvas(
        self, job_id: UUID, sheet: Sheet, settings: JobSettings
    ) -> io.BytesIO:
        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(sheet.width_mm * mm, sheet.height_mm * mm))

        self._draw_metadata(c, job_id, sheet)
        self._draw_item_marks(c, sheet, settings)

        if settings.plotter_marks != "none":
            self._draw_plotter_marks(c, sheet, settings)

        if settings.add_qr_code:
            self._draw_qr_code(c, job_id, sheet, settings)

        c.save()
        packet.seek(0)
        return packet

    def _draw_metadata(self, c: canvas.Canvas, job_id: UUID, sheet: Sheet) -> None:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        top = sheet.height_mm
        c.drawString(10 * mm, (top - 10) * mm, f"Job: {str(job_id)[:8].upper()}")
        c.drawString(10 * mm, (top - 15) * mm, f"Planche: {sheet.sheet_number}")
        c.drawString(10 * mm, (top - 20) * mm, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        c.drawString(10 * mm, (top - 25) * mm, f"Remplissage: {sheet.fill_rate:.1f}%")
        c.drawString(10 * mm, (top - 30) * mm, f"Elements: {len(sheet.items)}")

    def _draw_item_marks(self, c: canvas.Canvas, sheet: Sheet, settings: JobSettings) -> None:
        crop_len = 5 * mm
        crop_off = 2 * mm

        for item in sheet.items:
            x = item.x_mm * mm
            y = item.y_mm * mm
            w = item.width_mm * mm
            h = item.height_mm * mm

            if settings.draw_cutlines:
                c.setStrokeColorRGB(1, 0, 0)
                c.setLineWidth(0.5)
                c.rect(x, y, w, h)

            if settings.add_crop_marks:
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(0.25)
                # Bottom-left
                c.line(x - crop_off, y, x - crop_off - crop_len, y)
                c.line(x, y - crop_off, x, y - crop_off - crop_len)
                # Bottom-right
                c.line(x + w + crop_off, y, x + w + crop_off + crop_len, y)
                c.line(x + w, y - crop_off, x + w, y - crop_off - crop_len)
                # Top-left
                c.line(x - crop_off, y + h, x - crop_off - crop_len, y + h)
                c.line(x, y + h + crop_off, x, y + h + crop_off + crop_len)
                # Top-right
                c.line(x + w + crop_off, y + h, x + w + crop_off + crop_len, y + h)
                c.line(x + w, y + h + crop_off, x + w, y + h + crop_off + crop_len)

    # ------------------------------------------------------------------ #
    #  Graphtec ARMS registration marks                                    #
    # ------------------------------------------------------------------ #

    def _draw_plotter_marks(
        self, c: canvas.Canvas, sheet: Sheet, settings: JobSettings
    ) -> None:
        """Four L-shaped corner marks for Graphtec ARMS sensing, in 100K black.

        Both arms of each L occupy the band [inset, inset + length] from the
        sheet edges; what differs between the two mark types is orientation:
        - graphtec1: the L's corner sits at (inset+length) and its arms point
          OUT toward the media corner;
        - graphtec2: the L's corner sits at (inset) and its arms point IN
          toward the artwork.
        The nesting reserves plotter_reserve_mm() so poses never touch them.
        """
        from reportlab.lib.colors import CMYKColor

        inset = settings.plotter_mark_margin_mm
        length = settings.plotter_mark_length_mm
        width_mm_ = sheet.width_mm
        height_mm_ = sheet.height_mm

        c.setStrokeColor(CMYKColor(0, 0, 0, 1))
        c.setLineWidth(settings.plotter_mark_thickness_mm * mm)
        c.setLineCap(0)  # butt caps: arm length stays exactly `length`

        outward = settings.plotter_marks == "graphtec1"
        # Corner definitions: (x_edge, y_edge, x_dir, y_dir) where dirs point
        # INTO the sheet from that corner.
        corners = (
            (0.0, 0.0, 1, 1),
            (width_mm_, 0.0, -1, 1),
            (0.0, height_mm_, 1, -1),
            (width_mm_, height_mm_, -1, -1),
        )
        for x_edge, y_edge, dx, dy in corners:
            near = inset          # arm end closest to the media corner
            far = inset + length  # arm end closest to the artwork
            # The L's corner point:
            cx = x_edge + dx * (far if outward else near)
            cy = y_edge + dy * (far if outward else near)
            # Arms run back toward the media corner (type 1) or into the
            # sheet (type 2) — both spanning [near, far].
            hx = x_edge + dx * (near if outward else far)
            vy = y_edge + dy * (near if outward else far)
            c.line(cx * mm, cy * mm, hx * mm, cy * mm)  # horizontal arm
            c.line(cx * mm, cy * mm, cx * mm, vy * mm)  # vertical arm

    # ------------------------------------------------------------------ #
    #  CutContour spot overlay                                             #
    # ------------------------------------------------------------------ #

    def _cut_contour_overlay(self, sheet: Sheet) -> fitz.Document:
        """A one-page PDF containing only the poses' outlines stroked in the
        'CutContour' separation (spot) color — the convention print & cut
        RIPs (VersaWorks, Onyx, Caldera, Cutting Master) extract as the cut
        path. Overlaid on top of the finished sheet by generate_sheet_pdf."""
        from reportlab.lib.colors import CMYKColorSep

        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(sheet.width_mm * mm, sheet.height_mm * mm))
        spot = CMYKColorSep(0, 1.0, 0, 0, spotName="CutContour")
        c.setStrokeColor(spot)
        c.setLineWidth(0.25)
        try:
            c.setStrokeOverprint(True)  # cut line must not knock out the print
        except AttributeError:  # very old reportlab
            pass
        for item in sheet.items:
            c.rect(item.x_mm * mm, item.y_mm * mm,
                   item.width_mm * mm, item.height_mm * mm)
        c.save()
        packet.seek(0)
        return fitz.open("pdf", packet.read())

    # ------------------------------------------------------------------ #
    #  QR Code                                                             #
    # ------------------------------------------------------------------ #

    def _draw_qr_code(
        self, c: canvas.Canvas, job_id: UUID, sheet: Sheet, settings: JobSettings
    ) -> None:
        try:
            import qrcode as qr_lib

            qr_data = (
                f"JELOTIA|JOB:{str(job_id)[:8].upper()}"
                f"|SHEET:{sheet.sheet_number}"
                f"|ITEMS:{len(sheet.items)}"
                f"|FILL:{sheet.fill_rate:.1f}%"
            )
            qr = qr_lib.QRCode(version=1, box_size=10, border=1)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            size_pt = settings.qr_code_size_mm * mm
            x_pt = (sheet.width_mm - settings.qr_code_size_mm - 5) * mm
            y_pt = 5 * mm

            c.drawImage(ImageReader(buf), x_pt, y_pt, width=size_pt, height=size_pt)
            logger.debug(f"QR code drawn for job {job_id} sheet {sheet.sheet_number}")
        except ImportError:
            logger.warning("qrcode package not installed — QR code skipped")
        except Exception as e:
            logger.warning(f"QR code generation failed: {e}")

    # ------------------------------------------------------------------ #
    #  Artwork stamping (PyMuPDF)                                          #
    # ------------------------------------------------------------------ #

    def _stamp_artwork(self, base_page: fitz.Page, sheet: Sheet) -> None:
        sheet_h_pt = sheet.height_mm * 2.83465

        for item in sheet.items:
            x0 = item.x_mm * 2.83465
            y0 = sheet_h_pt - (item.y_mm + item.height_mm) * 2.83465
            x1 = x0 + item.width_mm * 2.83465
            y1 = y0 + item.height_mm * 2.83465
            rect = fitz.Rect(x0, y0, x1, y1)
            rotation = 90 if item.rotated else 0

            try:
                src = fitz.open(str(item.source_path))
                if src.is_pdf:
                    base_page.show_pdf_page(rect, src, 0, keep_proportion=True, rotate=rotation)
                else:
                    base_page.insert_image(rect, filename=str(item.source_path), rotate=rotation)
                src.close()
            except Exception as e:
                logger.error(f"Could not stamp artwork {item.source_path}: {e}")

    # ------------------------------------------------------------------ #
    #  Thumbnail                                                           #
    # ------------------------------------------------------------------ #

    def _generate_thumbnail(self, pdf_path: Path, export_dir: Path) -> Optional[Path]:
        try:
            doc = fitz.open(str(pdf_path))
            page = doc[0]
            # Scale to max 400px wide for a decent low-res preview
            scale = min(400 / page.rect.width, 1.0)
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            thumb_path = export_dir / (pdf_path.stem + "_thumb.png")
            pix.save(str(thumb_path))
            doc.close()
            logger.debug(f"Thumbnail generated: {thumb_path}")
            return thumb_path
        except Exception as e:
            logger.warning(f"Thumbnail generation failed for {pdf_path}: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Cut layer (separate PDF with only cut marks)                        #
    # ------------------------------------------------------------------ #

    def _generate_cut_layer(
        self, job_id: UUID, sheet: Sheet, settings: JobSettings, export_dir: Path
    ) -> Optional[Path]:
        try:
            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=(sheet.width_mm * mm, sheet.height_mm * mm))

            crop_len = 5 * mm
            crop_off = 2 * mm

            for item in sheet.items:
                x = item.x_mm * mm
                y = item.y_mm * mm
                w = item.width_mm * mm
                h = item.height_mm * mm

                # Cut path in red
                c.setStrokeColorRGB(1, 0, 0)
                c.setLineWidth(0.5)
                c.rect(x, y, w, h)

                # Crop marks in black
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(0.25)
                c.line(x - crop_off, y, x - crop_off - crop_len, y)
                c.line(x, y - crop_off, x, y - crop_off - crop_len)
                c.line(x + w + crop_off, y, x + w + crop_off + crop_len, y)
                c.line(x + w, y - crop_off, x + w, y - crop_off - crop_len)
                c.line(x - crop_off, y + h, x - crop_off - crop_len, y + h)
                c.line(x, y + h + crop_off, x, y + h + crop_off + crop_len)
                c.line(x + w + crop_off, y + h, x + w + crop_off + crop_len, y + h)
                c.line(x + w, y + h + crop_off, x + w, y + h + crop_off + crop_len)

            c.save()
            packet.seek(0)

            cut_path = (
                export_dir / f"job_{str(job_id)[:8]}_sheet_{sheet.sheet_number}_cutlayer.pdf"
            )
            cut_path.write_bytes(packet.read())
            logger.debug(f"Cut layer generated: {cut_path}")
            return cut_path
        except Exception as e:
            logger.warning(f"Cut layer generation failed: {e}")
            return None
