import io
import logging
from datetime import datetime
from pathlib import Path
from typing import List
from uuid import UUID

import fitz  # PyMuPDF
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from src.core.models.domain import Sheet, JobSettings

logger = logging.getLogger(__name__)


class LayoutEngine:
    """
    LayoutEngine generates the final imposed PDF sheet.
    It combines ReportLab for vector drawing (crop marks, cutlines, metadata)
    and PyMuPDF for embedding the source artwork.
    """

    def generate_sheet_pdf(self, job_id: UUID, sheet: Sheet, settings: JobSettings, export_dir: Path) -> Path:
        """
        Generates the PDF for a specific sheet.
        """
        # 1. Generate the base canvas with ReportLab in memory
        packet = io.BytesIO()
        
        # ReportLab canvas uses points (1/72 inch). 1 mm = 2.83465 points
        # ReportLab coordinates: (0,0) is bottom-left
        c = canvas.Canvas(packet, pagesize=(sheet.width_mm * mm, sheet.height_mm * mm))

        # Draw Job Metadata (Top Left corner)
        c.setFont("Helvetica", 10)
        c.drawString(10 * mm, (sheet.height_mm - 15) * mm, f"Job: {job_id}")
        c.drawString(10 * mm, (sheet.height_mm - 20) * mm, f"Sheet: {sheet.sheet_number}")
        c.drawString(10 * mm, (sheet.height_mm - 25) * mm, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        c.drawString(10 * mm, (sheet.height_mm - 30) * mm, f"Fill Rate: {sheet.fill_rate:.2f}%")

        # Draw marks for each placed item
        crop_mark_length = 5 * mm
        crop_mark_offset = 2 * mm

        for item in sheet.items:
            # item coordinates are in mm from bottom-left (since we defined it that way, 
            # wait, rectpack puts (0,0) at bottom-left, so we can map directly)
            x_pt = item.x_mm * mm
            y_pt = item.y_mm * mm
            w_pt = item.width_mm * mm
            h_pt = item.height_mm * mm

            # Draw Cutlines if enabled
            if settings.draw_cutlines:
                c.setStrokeColorRGB(1, 0, 0) # Red
                c.setLineWidth(0.5)
                c.rect(x_pt, y_pt, w_pt, h_pt)

            # Draw Crop marks (Hirondelles)
            if settings.add_crop_marks:
                c.setStrokeColorRGB(0, 0, 0) # Registration Black ideally, but standard black is fine for now
                c.setLineWidth(0.3)
                
                # Bottom-Left corner
                c.line(x_pt - crop_mark_offset, y_pt, x_pt - crop_mark_offset - crop_mark_length, y_pt) # Horiz
                c.line(x_pt, y_pt - crop_mark_offset, x_pt, y_pt - crop_mark_offset - crop_mark_length) # Vert
                
                # Bottom-Right corner
                c.line(x_pt + w_pt + crop_mark_offset, y_pt, x_pt + w_pt + crop_mark_offset + crop_mark_length, y_pt) # Horiz
                c.line(x_pt + w_pt, y_pt - crop_mark_offset, x_pt + w_pt, y_pt - crop_mark_offset - crop_mark_length) # Vert

                # Top-Left corner
                c.line(x_pt - crop_mark_offset, y_pt + h_pt, x_pt - crop_mark_offset - crop_mark_length, y_pt + h_pt) # Horiz
                c.line(x_pt, y_pt + h_pt + crop_mark_offset, x_pt, y_pt + h_pt + crop_mark_offset + crop_mark_length) # Vert

                # Top-Right corner
                c.line(x_pt + w_pt + crop_mark_offset, y_pt + h_pt, x_pt + w_pt + crop_mark_offset + crop_mark_length, y_pt + h_pt) # Horiz
                c.line(x_pt + w_pt, y_pt + h_pt + crop_mark_offset, x_pt + w_pt, y_pt + h_pt + crop_mark_offset + crop_mark_length) # Vert

        c.save()
        packet.seek(0)

        # 2. Merge artwork using PyMuPDF
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"job_{str(job_id)[:8]}_sheet_{sheet.sheet_number}.pdf"

        # Load the base canvas we just created
        base_pdf = fitz.open("pdf", packet)
        base_page = base_pdf[0]

        # PyMuPDF coordinates: (0,0) is TOP-LEFT. 
        # So we need to convert Y coordinate from bottom-left to top-left.
        for item in sheet.items:
            src_doc = fitz.open(str(item.source_path))
            # PyMuPDF uses rects (x0, y0, x1, y1) in top-left origin
            # Calculate top-left for placing:
            # y_bottom_left = item.y_mm
            # top_left_y = sheet.height_mm - (item.y_mm + item.height_mm)
            
            x0_pt = item.x_mm * 2.83465
            y0_pt = (sheet.height_mm - (item.y_mm + item.height_mm)) * 2.83465
            x1_pt = x0_pt + (item.width_mm * 2.83465)
            y1_pt = y0_pt + (item.height_mm * 2.83465)

            target_rect = fitz.Rect(x0_pt, y0_pt, x1_pt, y1_pt)

            # Rotation mapping (rectpack rotation is typically 90 degrees if rotated)
            rotation = 90 if item.rotated else 0

            # Stamp the page
            base_page.show_pdf_page(
                target_rect, 
                src_doc, 
                0, 
                keep_proportion=True, 
                rotate=rotation
            )
            src_doc.close()

        base_pdf.save(str(export_path))
        base_pdf.close()

        logger.info(f"Generated sheet PDF at {export_path}")
        return export_path

    def process_job_layout(self, job_id: UUID, sheets: List[Sheet], settings: JobSettings, export_dir: Path) -> List[Sheet]:
        """
        Processes all sheets for a job and updates their export_path.
        """
        for sheet in sheets:
            pdf_path = self.generate_sheet_pdf(job_id, sheet, settings, export_dir)
            sheet.export_path = pdf_path
            
        return sheets
