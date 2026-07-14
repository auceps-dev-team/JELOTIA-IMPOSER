import logging
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_MM_TO_PT = 72.0 / 25.4
_MAX_UNDO = 10


class PdfEditError(Exception):
    """Raised when a PDF edit operation can't be performed."""


def repair_pdf(src: Path, dest: Path) -> Path:
    """Rewrites a damaged or non-conforming PDF through pikepdf (qpdf): the
    xref is rebuilt, objects are normalized and the structure is made
    standard-compliant — the tool of choice when a customer file won't open
    or a RIP rejects it. The source file is never modified."""
    try:
        import pikepdf
    except ImportError as e:  # pragma: no cover - declared dependency
        raise PdfEditError("pikepdf est requis pour la réparation.") from e

    src, dest = Path(src), Path(dest)
    if src.resolve() == dest.resolve():
        raise PdfEditError("Choisissez un fichier de sortie différent de l'original.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pikepdf.open(str(src)) as pdf:
            pdf.save(str(dest))
    except Exception as e:
        raise PdfEditError(f"Réparation impossible ({src.name}) : {e}") from e
    return dest


class PdfEditSession:
    """An in-memory PDF editing session: page-level operations (rotate,
    delete, move, duplicate, merge, extract) plus text/image stamping, with a
    bounded undo stack. Nothing touches the original file until save_as()."""

    def __init__(self):
        self.doc: Optional[fitz.Document] = None
        self.path: Optional[Path] = None
        self.modified = False
        self._undo_stack: List[bytes] = []

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_open(self) -> bool:
        return self.doc is not None

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc is not None else 0

    def open(self, path: Path) -> None:
        path = Path(path)
        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise PdfEditError(f"PDF illisible ({path.name}) : {e}") from e
        if doc.page_count == 0:
            doc.close()
            raise PdfEditError(f"{path.name} ne contient aucune page.")
        self.close()
        self.doc = doc
        self.path = path
        self.modified = False
        self._undo_stack = []

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.path = None
        self.modified = False
        self._undo_stack = []

    def _require_doc(self) -> fitz.Document:
        if self.doc is None:
            raise PdfEditError("Aucun PDF ouvert.")
        return self.doc

    def _check_index(self, index: int) -> None:
        if not 0 <= index < self.page_count:
            raise PdfEditError(f"Page {index + 1} inexistante.")

    # ------------------------------------------------------------------ #
    #  Undo                                                                #
    # ------------------------------------------------------------------ #

    def _snapshot(self) -> None:
        """Serializes the current state before a mutation. Bounded, so a huge
        file can't exhaust memory through repeated edits."""
        doc = self._require_doc()
        self._undo_stack.append(doc.tobytes())
        del self._undo_stack[:-_MAX_UNDO]

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        snapshot = self._undo_stack.pop()
        if self.doc is not None:
            self.doc.close()
        self.doc = fitz.open("pdf", snapshot)
        self.modified = True
        return True

    # ------------------------------------------------------------------ #
    #  Page operations                                                     #
    # ------------------------------------------------------------------ #

    def rotate_page(self, index: int, delta_degrees: int) -> None:
        doc = self._require_doc()
        self._check_index(index)
        self._snapshot()
        page = doc[index]
        page.set_rotation((page.rotation + delta_degrees) % 360)
        self.modified = True

    def delete_pages(self, indices: List[int]) -> None:
        doc = self._require_doc()
        indices = sorted(set(indices), reverse=True)
        for index in indices:
            self._check_index(index)
        if len(indices) >= self.page_count:
            raise PdfEditError(
                "Un PDF doit conserver au moins une page — ajoutez ou dupliquez "
                "une page avant de supprimer celle-ci."
            )
        self._snapshot()
        for index in indices:
            doc.delete_page(index)
        self.modified = True

    def move_page(self, src: int, dest: int) -> None:
        doc = self._require_doc()
        self._check_index(src)
        self._check_index(dest)
        if src == dest:
            return
        self._snapshot()
        # fitz semantics (probed): move_page(src, to) re-inserts the page
        # BEFORE position `to` counted in the ORIGINAL numbering; to=-1 means
        # "after the last page". Normalized so `dest` is always the moved
        # page's final index, in both directions.
        if dest < src:
            to = dest
        elif dest >= self.page_count - 1:
            to = -1
        else:
            to = dest + 1
        doc.move_page(src, to)
        self.modified = True

    def duplicate_page(self, index: int) -> None:
        doc = self._require_doc()
        self._check_index(index)
        self._snapshot()
        # fitz semantics (probed): fullcopy_page's `to` must be an EXISTING
        # page number — index+1 raises on the last page (so duplication of a
        # single-page document always failed). -1 appends at the end.
        to = index + 1 if index + 1 < self.page_count else -1
        doc.fullcopy_page(index, to)
        self.modified = True

    def insert_blank_page(self, after_index: int) -> None:
        """Inserts a blank page right after `after_index`, matching that
        page's displayed size (rotation taken into account)."""
        doc = self._require_doc()
        self._check_index(after_index)
        self._snapshot()
        w_mm, h_mm = self.page_size_mm(after_index)
        doc.new_page(
            pno=after_index + 1, width=w_mm * _MM_TO_PT, height=h_mm * _MM_TO_PT
        )
        self.modified = True

    def merge_pdf(self, path: Path, at: Optional[int] = None) -> int:
        """Inserts every page of `path` (at the end by default). Returns the
        number of pages added."""
        doc = self._require_doc()
        path = Path(path)
        try:
            src = fitz.open(str(path))
        except Exception as e:
            raise PdfEditError(f"PDF illisible ({path.name}) : {e}") from e
        try:
            added = src.page_count
            if added == 0:
                raise PdfEditError(f"{path.name} ne contient aucune page.")
            self._snapshot()
            if at is None:
                doc.insert_pdf(src)
            else:
                doc.insert_pdf(src, start_at=at)
        finally:
            src.close()
        self.modified = True
        return added

    def extract_pages(self, indices: List[int], out_path: Path) -> Path:
        """Writes the selected pages (in ascending order) to a new PDF."""
        doc = self._require_doc()
        indices = sorted(set(indices))
        for index in indices:
            self._check_index(index)
        if not indices:
            raise PdfEditError("Aucune page sélectionnée.")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = fitz.open()
        try:
            for index in indices:
                out.insert_pdf(doc, from_page=index, to_page=index)
            out.save(str(out_path))
        finally:
            out.close()
        return out_path

    # ------------------------------------------------------------------ #
    #  Stamping                                                            #
    # ------------------------------------------------------------------ #

    def add_text(
        self,
        index: int,
        x_mm: float,
        y_mm: float,
        text: str,
        font_size_pt: float = 12.0,
        color: str = "#000000",
        bold: bool = False,
        bg_color: Optional[str] = None,
    ) -> None:
        """Stamps text at (x_mm, y_mm). With `bg_color`, an opaque rectangle is
        painted underneath first — the field technique for retouching scanned
        pages, where the old value can only be covered, not removed."""
        doc = self._require_doc()
        self._check_index(index)
        if not text.strip():
            raise PdfEditError("Texte vide.")
        self._snapshot()
        page = doc[index]
        rgb = _hex_to_rgb01(color)
        if bg_color:
            fontname = "hebo" if bold else "helv"
            width_pt = fitz.get_text_length(text, fontname=fontname, fontsize=font_size_pt)
            pad = font_size_pt * 0.18
            rect = fitz.Rect(
                x_mm * _MM_TO_PT - pad,
                y_mm * _MM_TO_PT - pad,
                x_mm * _MM_TO_PT + width_pt + pad,
                y_mm * _MM_TO_PT + font_size_pt * 1.05 + pad,
            )
            if page.rotation:
                rect = (rect * page.derotation_matrix).normalize()
            page.draw_rect(rect, color=None, fill=_hex_to_rgb01(bg_color))
        # Coordinates arrive in DISPLAYED space (what the preview shows);
        # insert_text expects the unrotated page space — derotate, and pass
        # rotate= so the glyphs stay upright on a rotated page.
        baseline = fitz.Point(x_mm * _MM_TO_PT, y_mm * _MM_TO_PT + font_size_pt * 0.8)
        if page.rotation:
            baseline = baseline * page.derotation_matrix
        page.insert_text(
            baseline, text, fontsize=font_size_pt,
            fontname="hebo" if bold else "helv", color=rgb,
            rotate=page.rotation,
        )
        self.modified = True

    def add_image(
        self, index: int, x_mm: float, y_mm: float, width_mm: float, image_path: Path
    ) -> None:
        doc = self._require_doc()
        self._check_index(index)
        image_path = Path(image_path)
        try:
            pix = fitz.Pixmap(str(image_path))
        except Exception as e:
            raise PdfEditError(f"Image illisible ({image_path.name}) : {e}") from e
        if pix.width == 0:
            raise PdfEditError(f"Image vide : {image_path.name}")
        height_mm = width_mm * pix.height / pix.width
        self._snapshot()
        page = doc[index]
        rect = fitz.Rect(
            x_mm * _MM_TO_PT,
            y_mm * _MM_TO_PT,
            (x_mm + width_mm) * _MM_TO_PT,
            (y_mm + height_mm) * _MM_TO_PT,
        )
        if page.rotation:
            # Displayed space -> unrotated page space (see add_text).
            rect = (rect * page.derotation_matrix).normalize()
        page.insert_image(rect, filename=str(image_path), rotate=page.rotation)
        self.modified = True

    # ------------------------------------------------------------------ #
    #  Text search & replace (redact + reinsert)                           #
    # ------------------------------------------------------------------ #

    def page_text_diagnosis(self, index: int) -> str:
        """Why (or whether) text search can work on this page:
        - "has_text": real extractable text exists;
        - "scanned_image": no text at all, the page is raster imagery (scan /
          full-page export) — text lives inside the pixels;
        - "vector_only": no text but vector drawings — text was converted to
          outlines by the authoring tool;
        - "empty": nothing detectable."""
        doc = self._require_doc()
        self._check_index(index)
        page = doc[index]
        if page.get_text().strip():
            return "has_text"
        if page.get_images(full=True):
            return "scanned_image"
        if page.get_drawings():
            return "vector_only"
        return "empty"

    def find_text(self, index: int, needle: str) -> List[fitz.Rect]:
        """Occurrence rectangles of `needle` on the page (empty list if none,
        or if the 'text' is actually vector shapes — the known PDF limit)."""
        doc = self._require_doc()
        self._check_index(index)
        if not needle.strip():
            return []
        return doc[index].search_for(needle)

    def text_style_at(self, index: int, rect: fitz.Rect) -> dict:
        """Font size / color / boldness of the text span under `rect`, so the
        replacement can mimic the original. Falls back to sane defaults."""
        doc = self._require_doc()
        self._check_index(index)
        style = {"font_size_pt": 11.0, "color": "#000000", "bold": False}
        data = doc[index].get_text("dict", clip=rect)
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    style["font_size_pt"] = round(float(span.get("size", 11.0)), 1)
                    style["color"] = f"#{span.get('color', 0) & 0xFFFFFF:06x}"
                    style["bold"] = bool(span.get("flags", 0) & 16)
                    return style
        return style

    @staticmethod
    def _apply_text_replacement(
        page: fitz.Page,
        rects: List[fitz.Rect],
        new_text: str,
        font_size_pt: float,
        color: str,
        bold: bool,
    ) -> None:
        """Redacts the given rectangles then re-inserts `new_text` in each, in
        Helvetica at the requested size/color. Images and vector art are
        explicitly protected from the redaction pass."""
        for rect in rects:
            page.add_redact_annot(rect)
        try:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            )
        except TypeError:  # older PyMuPDF without the graphics parameter
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        if not new_text.strip():
            return  # replacement by nothing = plain removal
        rgb = _hex_to_rgb01(color)
        for rect in rects:
            baseline = fitz.Point(rect.x0, rect.y1 - font_size_pt * 0.22)
            page.insert_text(
                baseline, new_text, fontsize=font_size_pt,
                fontname="hebo" if bold else "helv", color=rgb,
                rotate=page.rotation,
            )

    def replace_text(
        self,
        index: int,
        rects: List[fitz.Rect],
        new_text: str,
        font_size_pt: float = 11.0,
        color: str = "#000000",
        bold: bool = False,
    ) -> None:
        """Replaces the text under each rect (one undo step for the whole
        operation). An empty `new_text` simply erases the occurrences."""
        doc = self._require_doc()
        self._check_index(index)
        if not rects:
            raise PdfEditError("Aucune occurrence à remplacer.")
        self._snapshot()
        self._apply_text_replacement(doc[index], rects, new_text, font_size_pt, color, bold)
        self.modified = True

    def preview_replace_text(
        self,
        index: int,
        rects: List[fitz.Rect],
        new_text: str,
        font_size_pt: float = 11.0,
        color: str = "#000000",
        bold: bool = False,
        target_width_px: int = 460,
    ) -> fitz.Pixmap:
        """Renders what the page WOULD look like after the replacement, on a
        throwaway clone — the session document is never touched."""
        doc = self._require_doc()
        self._check_index(index)
        clone = fitz.open("pdf", doc.tobytes())
        try:
            page = clone[index]
            self._apply_text_replacement(page, rects, new_text, font_size_pt, color, bold)
            zoom = max(0.05, target_width_px / max(1.0, page.rect.width))
            return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        finally:
            clone.close()

    # ------------------------------------------------------------------ #
    #  Images (list / replace / delete by xref)                            #
    # ------------------------------------------------------------------ #

    def list_images(self, index: int) -> List[dict]:
        """Every image occurrence on the page: {xref, rect (pt), width, height,
        name}. One xref may appear several times (one entry per placement)."""
        doc = self._require_doc()
        self._check_index(index)
        page = doc[index]
        results: List[dict] = []
        for item in page.get_images(full=True):
            xref = item[0]
            for rect in page.get_image_rects(item):
                results.append(
                    {
                        "xref": xref,
                        "rect": rect,
                        "width": item[2],
                        "height": item[3],
                        "name": item[7] or f"img{xref}",
                    }
                )
        return results

    def image_preview(self, xref: int) -> Optional[fitz.Pixmap]:
        """RGB thumbnail-ready pixmap of the image object, or None if it can't
        be decoded (e.g. pure stencil masks)."""
        doc = self._require_doc()
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.colorspace is None:
                return None
            if pix.alpha or pix.colorspace.n > 3 or pix.colorspace.name != fitz.csRGB.name:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            return pix
        except Exception:
            return None

    def replace_image(self, index: int, xref: int, image_path: Path) -> None:
        """Swaps the image OBJECT `xref` for the given file: every placement
        keeps its exact position and frame (the new image is stretched into
        the old rectangle). Affects all occurrences of that xref, document-wide
        — that's the xref-level contract that guarantees layout preservation."""
        doc = self._require_doc()
        self._check_index(index)
        image_path = Path(image_path)
        try:
            fitz.Pixmap(str(image_path))  # validates the file before mutating
        except Exception as e:
            raise PdfEditError(f"Image illisible ({image_path.name}) : {e}") from e
        self._snapshot()
        try:
            doc[index].replace_image(xref, filename=str(image_path))
        except Exception as e:
            raise PdfEditError(f"Remplacement impossible (xref {xref}) : {e}") from e
        self.modified = True

    def delete_image(self, index: int, xref: int) -> None:
        """Blanks the image object (its frame stays empty at the same spot)."""
        doc = self._require_doc()
        self._check_index(index)
        self._snapshot()
        try:
            doc[index].delete_image(xref)
        except Exception as e:
            raise PdfEditError(f"Suppression impossible (xref {xref}) : {e}") from e
        self.modified = True

    # ------------------------------------------------------------------ #
    #  Rendering & info                                                    #
    # ------------------------------------------------------------------ #

    def page_size_mm(self, index: int) -> tuple:
        """Displayed size (what the preview renders). fitz's page.rect already
        reflects the rotation (probed: 200x300 rotated 90° reports 300x200),
        so no swap is needed here — but insert_text/insert_image work in the
        UNROTATED space, hence the derotation in add_text/add_image."""
        doc = self._require_doc()
        self._check_index(index)
        rect = doc[index].rect
        return (rect.width / _MM_TO_PT, rect.height / _MM_TO_PT)

    def render_page(self, index: int, target_width_px: int = 900) -> fitz.Pixmap:
        """Rasterizes one page, scaled so its width is ~target_width_px."""
        doc = self._require_doc()
        self._check_index(index)
        page = doc[index]
        width = max(1.0, page.rect.width)
        zoom = max(0.05, target_width_px / width)
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

    # ------------------------------------------------------------------ #
    #  Save                                                                #
    # ------------------------------------------------------------------ #

    def save_as(self, out_path: Path) -> Path:
        doc = self._require_doc()
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # garbage/deflate compact away deleted objects from removed pages.
        doc.save(str(out_path), garbage=3, deflate=True)
        self.modified = False
        return out_path


def _hex_to_rgb01(color: str) -> tuple:
    color = (color or "#000000").lstrip("#")
    if len(color) != 6:
        return (0.0, 0.0, 0.0)
    return tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
