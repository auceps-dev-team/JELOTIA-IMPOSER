import logging
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF

from src.core.engines.qr_engine import QREngine, QRGenerationError
from src.core.models.domain import CardTemplate, QRCodeSettings

logger = logging.getLogger(__name__)

_MM_TO_PT = 72.0 / 25.4

# Standard print formats (width_mm, height_mm) offered when creating a template.
STANDARD_FORMATS: Dict[str, tuple] = {
    "Carte de visite (85×55)": (85.0, 55.0),
    "Carte QR (54×85)": (54.0, 85.0),
    "Vignette (50×50)": (50.0, 50.0),
    "A7 (74×105)": (74.0, 105.0),
    "A6 (105×148)": (105.0, 148.0),
    "A5 (148×210)": (148.0, 210.0),
    "A4 (210×297)": (210.0, 297.0),
}


def substitute_placeholders(text: str, row: Optional[dict]) -> str:
    """Replaces every {Colonne} placeholder with the row's value for that
    column. Unknown placeholders are left as-is (visible, so a typo in the
    template is noticed instead of silently vanishing)."""
    if not row:
        return text
    for key, value in row.items():
        text = text.replace("{" + str(key) + "}", str(value))
    return text


def _hex_to_rgb01(color: str) -> tuple:
    color = (color or "#000000").lstrip("#")
    if len(color) != 6:
        return (0.0, 0.0, 0.0)
    return tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


class TemplateComposer:
    """Renders a CardTemplate into a final PDF: background artwork (if any),
    a vector QR code at the template's QR zone, and the text zones with
    per-row placeholder substitution. Output stays fully vector."""

    def __init__(self):
        self.qr_engine = QREngine()

    def compose(
        self,
        template: CardTemplate,
        qr_data: str,
        settings: QRCodeSettings,
        out_path: Path,
        row: Optional[dict] = None,
    ) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        w_pt = template.width_mm * _MM_TO_PT
        h_pt = template.height_mm * _MM_TO_PT

        doc = fitz.open()
        page = doc.new_page(width=w_pt, height=h_pt)
        # Source docs of show_pdf_page must stay open until the target is
        # saved (PyMuPDF holds references into them) — collected here and
        # closed after doc.save().
        sources: list = []

        try:
            # 1. Background artwork, scaled to fill the card.
            if template.base_pdf:
                base = Path(template.base_pdf)
                if base.exists():
                    try:
                        src = fitz.open(str(base))
                        sources.append(src)
                        page.show_pdf_page(page.rect, src, 0)
                    except Exception as e:
                        logger.warning(f"Fond de modèle illisible ({base}): {e}")
                else:
                    logger.warning(f"Fond de modèle introuvable: {base}")

            # 2. Vector QR overlay (rendered by the same engine as everywhere
            # else, so batch cards and single exports look identical). The
            # temp file is read into memory and deleted right away — only the
            # in-memory copy has to survive until save().
            zone = template.qr_zone
            qr_settings = settings.model_copy(update={"size_mm": zone.size_mm})
            tmp_qr = out_path.parent / f".qr_tmp_{uuid.uuid4().hex}.pdf"
            try:
                self.qr_engine.render_pdf(qr_data, qr_settings, tmp_qr)
                qr_bytes = tmp_qr.read_bytes()
            finally:
                tmp_qr.unlink(missing_ok=True)
            qr_doc = fitz.open("pdf", qr_bytes)
            sources.append(qr_doc)
            rect = fitz.Rect(
                zone.x_mm * _MM_TO_PT,
                zone.y_mm * _MM_TO_PT,
                (zone.x_mm + zone.size_mm) * _MM_TO_PT,
                (zone.y_mm + zone.size_mm) * _MM_TO_PT,
            )
            page.show_pdf_page(rect, qr_doc, 0)

            # 3. Text zones (y is the top of the line; insert_text wants a
            # baseline, approximated at 80% of the font size below the top).
            for text_zone in template.texts:
                content = substitute_placeholders(text_zone.text, row)
                if not content.strip():
                    continue
                baseline = fitz.Point(
                    text_zone.x_mm * _MM_TO_PT,
                    text_zone.y_mm * _MM_TO_PT + text_zone.font_size_pt * 0.8,
                )
                page.insert_text(
                    baseline,
                    content,
                    fontsize=text_zone.font_size_pt,
                    fontname="hebo" if text_zone.bold else "helv",
                    color=_hex_to_rgb01(text_zone.color),
                )

            doc.save(str(out_path))
        finally:
            for src in sources:
                src.close()
            doc.close()
        return out_path


class TemplateStore:
    """JSON persistence for CardTemplates under <HotFolder>/Templates. An
    imported background PDF is copied into the store so the template keeps
    working even if the original file moves."""

    def __init__(self, directory: Optional[Path] = None):
        if directory is None:
            from src.utils.config import config

            directory = Path(config.base_dir) / "Templates"
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _json_path(self, template_id) -> Path:
        return self.directory / f"{template_id}.json"

    def save(self, template: CardTemplate) -> CardTemplate:
        if template.base_pdf:
            base = Path(template.base_pdf)
            if base.exists() and base.parent.resolve() != self.directory.resolve():
                dest = self.directory / f"{template.id}_fond{base.suffix.lower()}"
                try:
                    shutil.copy2(str(base), str(dest))
                    template.base_pdf = dest
                except OSError as e:
                    raise QRGenerationError(f"Copie du fond impossible : {e}") from e

        self._json_path(template.id).write_text(
            template.model_dump_json(indent=2), encoding="utf-8"
        )
        return template

    def load(self, template_id) -> CardTemplate:
        raw = self._json_path(template_id).read_text(encoding="utf-8")
        return CardTemplate.model_validate_json(raw)

    def list(self, include_archived: bool = False) -> List[CardTemplate]:
        templates: List[CardTemplate] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                templates.append(
                    CardTemplate.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except Exception as e:
                logger.warning(f"Modèle illisible ({path.name}): {e}")
        if not include_archived:
            templates = [t for t in templates if not t.archived]
        return sorted(templates, key=lambda t: t.name.lower())

    def set_archived(self, template_id, archived: bool) -> None:
        """Hides (or restores) a template from pickers, keeping it on disk."""
        template = self.load(template_id)
        template.archived = archived
        self.save(template)

    def delete(self, template_id) -> None:
        self._json_path(template_id).unlink(missing_ok=True)
        for leftover in self.directory.glob(f"{template_id}_fond.*"):
            leftover.unlink(missing_ok=True)
