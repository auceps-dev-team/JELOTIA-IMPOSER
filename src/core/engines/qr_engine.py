import logging
import re
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

import qrcode
import qrcode.image.svg
from PIL import Image
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from src.core.models.domain import QRCodeSettings, QRErrorCorrection, QRItem

logger = logging.getLogger(__name__)

_ECC_MAP = {
    QRErrorCorrection.L: ERROR_CORRECT_L,
    QRErrorCorrection.M: ERROR_CORRECT_M,
    QRErrorCorrection.Q: ERROR_CORRECT_Q,
    QRErrorCorrection.H: ERROR_CORRECT_H,
}

_SUPPORTED_FORMATS = ("PNG", "SVG", "PDF")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class QRGenerationError(Exception):
    """Raised when a QR code can't be produced (empty data, unreadable logo,
    unsupported export format, ...)."""


def safe_filename(name: str) -> str:
    """Strips characters Windows forbids in filenames and trims trailing dots/
    spaces, so a name coming from an arbitrary import column can't produce an
    invalid or path-traversing output file."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name or "").strip().strip(".")
    return cleaned


def is_valid_url(data: str) -> bool:
    """Syntactic URL check (scheme + host) — no network request. Network
    reachability is a separate, optional, slow verification step."""
    try:
        parsed = urlparse((data or "").strip())
    except ValueError:
        return False
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


class QREngine:
    """Generates QR codes from arbitrary text/URLs in raster (PNG) and vector
    (SVG, PDF) formats, with optional centered logo. The PDF output is true
    vector (the module grid is drawn as filled rectangles), so it scales to any
    print size without pixelation — which is what feeds the imposition pipeline.
    """

    def _build_qr(self, data: str, settings: QRCodeSettings) -> qrcode.QRCode:
        if not data or not str(data).strip():
            raise QRGenerationError("Le contenu du QR code est vide.")

        # A centered logo hides part of the code, so force maximum redundancy
        # (H ≈ 30%) whenever one is embedded, regardless of the chosen level.
        ecc = QRErrorCorrection.H if settings.logo_path else settings.ecc
        qr = qrcode.QRCode(
            error_correction=_ECC_MAP[ecc],
            box_size=max(1, settings.box_size),
            border=max(0, settings.border),
        )
        qr.add_data(str(data))
        qr.make(fit=True)
        return qr

    # ------------------------------------------------------------------ #
    #  Raster (PNG)                                                        #
    # ------------------------------------------------------------------ #

    def generate_image(self, data: str, settings: QRCodeSettings) -> Image.Image:
        """Returns the QR as a PIL RGB image at the raw module resolution
        (box_size px per module), logo already embedded if configured."""
        qr = self._build_qr(data, settings)
        img = qr.make_image(
            fill_color=settings.fill_color, back_color=settings.back_color
        ).convert("RGB")
        if settings.logo_path:
            img = self._embed_logo(img, settings)
        return img

    def _embed_logo(self, img: Image.Image, settings: QRCodeSettings) -> Image.Image:
        try:
            logo = Image.open(str(settings.logo_path)).convert("RGBA")
        except OSError as e:
            raise QRGenerationError(f"Logo illisible ({settings.logo_path}) : {e}") from e

        qr_w, qr_h = img.size
        target = max(1, int(min(qr_w, qr_h) * settings.logo_scale))
        logo.thumbnail((target, target), Image.LANCZOS)

        # White rounded-free backing pad keeps the logo legible against the
        # module grid and preserves scannability.
        pad = int(target * 0.12)
        backing_size = (logo.width + 2 * pad, logo.height + 2 * pad)
        backing = Image.new("RGBA", backing_size, (255, 255, 255, 255))
        backing.paste(logo, (pad, pad), logo)

        base = img.convert("RGBA")
        pos = ((qr_w - backing.width) // 2, (qr_h - backing.height) // 2)
        base.paste(backing, pos, backing)
        return base.convert("RGB")

    def render_png(self, data: str, settings: QRCodeSettings, out_path: Path) -> Path:
        """Writes a PNG scaled to the requested physical size (size_mm @ dpi),
        using nearest-neighbour so module edges stay crisp."""
        img = self.generate_image(data, settings)
        if settings.size_mm > 0 and settings.dpi > 0:
            target_px = max(1, round(settings.size_mm / 25.4 * settings.dpi))
            img = img.resize((target_px, target_px), Image.NEAREST)

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path), format="PNG", dpi=(settings.dpi, settings.dpi))
        return out_path

    # ------------------------------------------------------------------ #
    #  Vector (SVG, PDF)                                                   #
    # ------------------------------------------------------------------ #

    def render_svg(self, data: str, settings: QRCodeSettings, out_path: Path) -> Path:
        """Writes a vector SVG. Modules use fill_color; background stays
        transparent (typical for overlaying on artwork). Logo embedding in SVG
        is not supported yet — raise rather than silently drop it."""
        if settings.logo_path:
            raise QRGenerationError(
                "L'incrustation de logo n'est pas encore supportée en SVG "
                "(utilisez PNG ou PDF)."
            )
        qr = self._build_qr(data, settings)
        img = qr.make_image(image_factory=qrcode.image.svg.SvgPathFillImage)

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))

        # SvgPathFillImage hardcodes a black fill; recolor if requested.
        if settings.fill_color.lower() not in ("#000000", "black"):
            text = out_path.read_text(encoding="utf-8")
            text = text.replace("#000000", settings.fill_color).replace(
                'fill:black', f"fill:{settings.fill_color}"
            )
            out_path.write_text(text, encoding="utf-8")
        return out_path

    def render_pdf(self, data: str, settings: QRCodeSettings, out_path: Path) -> Path:
        """Writes a true-vector PDF sized to size_mm: the module matrix is
        drawn as filled rectangles (crisp at any scale). This is the format
        the imposition pipeline consumes."""
        qr = self._build_qr(data, settings)
        matrix = qr.get_matrix()
        n = len(matrix)
        if n == 0:
            raise QRGenerationError("Matrice QR vide.")

        size_pt = settings.size_mm * mm
        module = size_pt / n

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(out_path), pagesize=(size_pt, size_pt))

        c.setFillColor(HexColor(settings.back_color))
        c.rect(0, 0, size_pt, size_pt, fill=1, stroke=0)

        c.setFillColor(HexColor(settings.fill_color))
        for r, row in enumerate(matrix):
            for col, is_dark in enumerate(row):
                if is_dark:
                    x = col * module
                    y = size_pt - (r + 1) * module  # PDF origin is bottom-left
                    c.rect(x, y, module, module, fill=1, stroke=0)

        if settings.logo_path:
            self._draw_pdf_logo(c, settings, size_pt)

        c.showPage()
        c.save()
        return out_path

    def _draw_pdf_logo(self, c: canvas.Canvas, settings: QRCodeSettings, size_pt: float) -> None:
        from reportlab.lib.utils import ImageReader

        try:
            logo = ImageReader(str(settings.logo_path))
        except Exception as e:  # ImageReader raises bare Exception on bad files
            raise QRGenerationError(f"Logo illisible ({settings.logo_path}) : {e}") from e

        side = size_pt * settings.logo_scale
        pad = side * 0.12
        box = side + 2 * pad
        origin = (size_pt - box) / 2
        c.setFillColor(HexColor("#FFFFFF"))
        c.rect(origin, origin, box, box, fill=1, stroke=0)
        c.drawImage(
            logo, origin + pad, origin + pad, side, side,
            preserveAspectRatio=True, mask="auto",
        )

    # ------------------------------------------------------------------ #
    #  Batch                                                               #
    # ------------------------------------------------------------------ #

    def generate_item(
        self, item: QRItem, settings: QRCodeSettings, out_dir: Path, formats: List[str]
    ) -> Dict[str, Path]:
        """Produces one QRItem in every requested format, named after the
        item's filename (falling back to a short id). Returns {FORMAT: path}."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = safe_filename(item.filename) or str(item.id)[:8]

        renderers = {
            "PNG": self.render_png,
            "SVG": self.render_svg,
            "PDF": self.render_pdf,
        }
        results: Dict[str, Path] = {}
        for fmt in formats:
            fmt_up = fmt.upper()
            if fmt_up not in renderers:
                raise QRGenerationError(f"Format d'export non supporté : {fmt}")
            out = out_dir / f"{base}.{fmt_up.lower()}"
            results[fmt_up] = renderers[fmt_up](item.data, settings, out)
        return results
