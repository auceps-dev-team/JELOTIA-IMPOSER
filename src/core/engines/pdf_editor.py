import logging
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_MM_TO_PT = 72.0 / 25.4
_MAX_UNDO = 10


class PdfEditError(Exception):
    """Raised when a PDF edit operation can't be performed."""


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
            raise PdfEditError("Impossible de supprimer toutes les pages.")
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
        doc.fullcopy_page(index, index + 1)
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
    ) -> None:
        doc = self._require_doc()
        self._check_index(index)
        if not text.strip():
            raise PdfEditError("Texte vide.")
        self._snapshot()
        page = doc[index]
        rgb = _hex_to_rgb01(color)
        baseline = fitz.Point(x_mm * _MM_TO_PT, y_mm * _MM_TO_PT + font_size_pt * 0.8)
        page.insert_text(
            baseline, text, fontsize=font_size_pt,
            fontname="hebo" if bold else "helv", color=rgb,
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
        rect = fitz.Rect(
            x_mm * _MM_TO_PT,
            y_mm * _MM_TO_PT,
            (x_mm + width_mm) * _MM_TO_PT,
            (y_mm + height_mm) * _MM_TO_PT,
        )
        doc[index].insert_image(rect, filename=str(image_path))
        self.modified = True

    # ------------------------------------------------------------------ #
    #  Rendering & info                                                    #
    # ------------------------------------------------------------------ #

    def page_size_mm(self, index: int) -> tuple:
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
