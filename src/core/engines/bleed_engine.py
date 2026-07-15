"""Automatic bleed generation.

Print shops receive artwork trimmed exactly at the finished size. Cut a stack
of those and the slightest drift shows a white sliver on the edge. The fix is
bleed: extend the artwork a few mm beyond the trim line, so the blade always
cuts inside the ink.

Strategy per source type:
- PDF already carrying a real bleed (BleedBox larger than TrimBox): nothing to
  invent — the extra area is used as-is.
- PDF without bleed: the outer strip of each edge is STRETCHED outwards. It
  stays vector (no rasterization), which matters for print. PyMuPDF cannot
  mirror a page (probed: an inverted rect raises), and `show_pdf_page` centers
  the clip unless `keep_proportion=False` is passed — that flag is what turns
  "centered strip with white padding" into a real stretch.
- Raster images: edges are MIRRORED (better looking than a stretch, and free
  with Pillow).
"""

import logging
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_MM_TO_PT = 72.0 / 25.4
# Thickness of the source strip pulled outwards. Small enough to only sample
# the very edge, thick enough to survive anti-aliasing.
_STRIP_PT = 2.0
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
# PDF box values round-trip through points: a 3 mm bleed reads back as
# 2.999998 mm. Comparing bleed with a floating-point epsilon would rebuild
# artwork that is already correct — 10 µm is far below anything printable.
_TOLERANCE_MM = 0.01


class BleedError(Exception):
    """Raised when bleed can't be produced for a source file."""


def available_bleed_mm(path: Path) -> float:
    """Bleed already present in a PDF (smallest margin between BleedBox and
    TrimBox), in mm. 0 for rasters or PDFs trimmed at the finished size."""
    path = Path(path)
    if path.suffix.lower() not in (".pdf",):
        return 0.0
    try:
        doc = fitz.open(str(path))
        page = doc[0]
        trim, bleed = page.trimbox, page.bleedbox
        doc.close()
    except Exception:
        return 0.0
    margins = (
        trim.x0 - bleed.x0,
        trim.y0 - bleed.y0,
        bleed.x1 - trim.x1,
        bleed.y1 - trim.y1,
    )
    return max(0.0, min(margins) / _MM_TO_PT)


def add_bleed(src: Path, bleed_mm: float, out_path: Path) -> Path:
    """Writes a copy of `src` extended by `bleed_mm` on all four sides.

    The returned artwork is (w + 2*bleed) × (h + 2*bleed): the imposition must
    place it at that size and keep cutting at the original trim rectangle,
    inset by `bleed_mm` (see LayoutEngine).
    """
    src, out_path = Path(src), Path(out_path)
    if bleed_mm <= 0:
        raise BleedError("Le fond perdu doit être supérieur à 0.")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() in _RASTER_SUFFIXES:
        return _add_bleed_raster(src, bleed_mm, out_path)
    return _add_bleed_pdf(src, bleed_mm, out_path)


# --------------------------------------------------------------------------- #
#  PDF                                                                         #
# --------------------------------------------------------------------------- #

def _add_bleed_pdf(src: Path, bleed_mm: float, out_path: Path) -> Path:
    try:
        source = fitz.open(str(src))
    except Exception as e:
        raise BleedError(f"PDF illisible ({src.name}) : {e}") from e

    try:
        page = source[0]
        rect = page.rect
        bleed_pt = bleed_mm * _MM_TO_PT
        width, height = rect.width, rect.height

        out = fitz.open()
        new_page = out.new_page(width=width + 2 * bleed_pt, height=height + 2 * bleed_pt)
        inner = fitz.Rect(bleed_pt, bleed_pt, bleed_pt + width, bleed_pt + height)

        strip = min(_STRIP_PT, width / 2, height / 2)
        # Corners first, then edges, then the artwork on top: each layer covers
        # the previous one's overshoot, so no seam shows.
        _stretch_corners(new_page, source, inner, bleed_pt, rect, strip)
        _stretch_edges(new_page, source, inner, bleed_pt, rect, strip)
        new_page.show_pdf_page(inner, source, 0, keep_proportion=False)

        out.save(str(out_path))
        out.close()
    finally:
        source.close()
    return out_path


def _stretch_edges(page, source, inner, bleed_pt, rect, strip) -> None:
    """Each edge strip of the source, stretched outwards into the bleed band.
    keep_proportion=False is mandatory: otherwise the strip is centered in the
    band and leaves white padding (probed)."""
    bands = (
        # (target band, source strip)
        (fitz.Rect(0, inner.y0, inner.x0, inner.y1),
         fitz.Rect(rect.x0, rect.y0, rect.x0 + strip, rect.y1)),                 # left
        (fitz.Rect(inner.x1, inner.y0, inner.x1 + bleed_pt, inner.y1),
         fitz.Rect(rect.x1 - strip, rect.y0, rect.x1, rect.y1)),                 # right
        (fitz.Rect(inner.x0, 0, inner.x1, inner.y0),
         fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + strip)),                 # top
        (fitz.Rect(inner.x0, inner.y1, inner.x1, inner.y1 + bleed_pt),
         fitz.Rect(rect.x0, rect.y1 - strip, rect.x1, rect.y1)),                 # bottom
    )
    for target, clip in bands:
        page.show_pdf_page(target, source, 0, clip=clip, keep_proportion=False)


def _stretch_corners(page, source, inner, bleed_pt, rect, strip) -> None:
    """The four corner squares, pulled from the matching corner of the source."""
    corners = (
        (fitz.Rect(0, 0, inner.x0, inner.y0),
         fitz.Rect(rect.x0, rect.y0, rect.x0 + strip, rect.y0 + strip)),
        (fitz.Rect(inner.x1, 0, inner.x1 + bleed_pt, inner.y0),
         fitz.Rect(rect.x1 - strip, rect.y0, rect.x1, rect.y0 + strip)),
        (fitz.Rect(0, inner.y1, inner.x0, inner.y1 + bleed_pt),
         fitz.Rect(rect.x0, rect.y1 - strip, rect.x0 + strip, rect.y1)),
        (fitz.Rect(inner.x1, inner.y1, inner.x1 + bleed_pt, inner.y1 + bleed_pt),
         fitz.Rect(rect.x1 - strip, rect.y1 - strip, rect.x1, rect.y1)),
    )
    for target, clip in corners:
        page.show_pdf_page(target, source, 0, clip=clip, keep_proportion=False)


# --------------------------------------------------------------------------- #
#  Raster                                                                      #
# --------------------------------------------------------------------------- #

def _add_bleed_raster(src: Path, bleed_mm: float, out_path: Path) -> Path:
    """Mirrors the edges outwards — the classic technique, and the best looking
    for photographic artwork."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(str(src))
        image.load()
    except Exception as e:
        raise BleedError(f"Image illisible ({src.name}) : {e}") from e

    dpi = image.info.get("dpi", (300, 300))
    dpi_x = float(dpi[0]) or 300.0
    dpi_y = float(dpi[1] if len(dpi) > 1 else dpi[0]) or 300.0
    bx = max(1, round(bleed_mm / 25.4 * dpi_x))
    by = max(1, round(bleed_mm / 25.4 * dpi_y))
    # Can't mirror more than what exists.
    bx, by = min(bx, image.width), min(by, image.height)

    canvas = Image.new(image.mode, (image.width + 2 * bx, image.height + 2 * by))
    canvas.paste(image, (bx, by))

    left = ImageOps.mirror(image.crop((0, 0, bx, image.height)))
    right = ImageOps.mirror(image.crop((image.width - bx, 0, image.width, image.height)))
    canvas.paste(left, (0, by))
    canvas.paste(right, (image.width + bx, by))

    band = canvas.crop((0, by, canvas.width, by + by))
    canvas.paste(ImageOps.flip(band), (0, 0))
    band = canvas.crop((0, image.height, canvas.width, image.height + by))
    canvas.paste(ImageOps.flip(band), (0, image.height + by))

    canvas.save(str(out_path), dpi=(dpi_x, dpi_y))
    image.close()
    return out_path


def ensure_bleed(
    src: Path, bleed_mm: float, out_dir: Path, name_hint: Optional[str] = None
) -> tuple:
    """Guarantees `bleed_mm` of bleed around `src`.

    Returns (path, applied_mm): the original path and 0.0 when the file already
    carries enough bleed (nothing is rewritten), otherwise the extended copy.
    """
    src = Path(src)
    if bleed_mm <= 0:
        return src, 0.0
    existing = available_bleed_mm(src)
    if existing + _TOLERANCE_MM >= bleed_mm:
        logger.debug(f"{src.name}: fond perdu déjà présent ({existing:.1f} mm)")
        return src, 0.0

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name_hint or src.stem
    out_path = out_dir / f"{stem}_bleed{src.suffix.lower()}"
    return add_bleed(src, bleed_mm, out_path), bleed_mm
