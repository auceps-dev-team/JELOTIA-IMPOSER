from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.engines.pdf_editor import PdfEditError, PdfEditSession
from src.ui.theme import ThemeManager

_T = ThemeManager
_THUMB_W = 104
_PREVIEW_W = 980
_MM_PER_PT = 25.4 / 72.0


def _pixmap_from_fitz(pix: fitz.Pixmap) -> QPixmap:
    image = QImage(
        pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
    ).copy()
    return QPixmap.fromImage(image)


@dataclass
class _Stamp:
    """A pending text/image overlay: it lives as a movable object on the
    preview until the document is saved (only then is it flattened into the
    PDF), so the operator can drag, re-edit or remove it freely."""

    kind: str  # "text" | "image"
    page: int
    x_mm: float
    y_mm: float
    data: dict = field(default_factory=dict)


class _StampTextDialog(QDialog):
    """Content/size/bold/color for a text stamp (creation and re-edit)."""

    def __init__(self, parent=None, stamp: Optional[_Stamp] = None):
        super().__init__(parent)
        self.setWindowTitle("Texte du tampon")
        data = stamp.data if stamp else {}
        self.color = data.get("color", "#000000")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.text_input = QLineEdit(data.get("text", ""))
        self.text_input.setPlaceholderText("Ex : BON À TIRER")
        form.addRow("Texte :", self.text_input)
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(4.0, 96.0)
        self.spin_size.setValue(data.get("font_size_pt", 14.0))
        self.spin_size.setSuffix(" pt")
        form.addRow("Taille :", self.spin_size)
        self.chk_bold = QCheckBox("Gras")
        self.chk_bold.setChecked(data.get("bold", False))
        form.addRow("", self.chk_bold)
        self.btn_color = QPushButton(self.color.upper())
        self.btn_color.clicked.connect(self._pick_color)
        form.addRow("Couleur :", self.btn_color)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self.color), self, "Couleur du texte")
        if color.isValid():
            self.color = color.name()
            self.btn_color.setText(self.color.upper())

    def values(self) -> dict:
        return {
            "text": self.text_input.text(),
            "font_size_pt": self.spin_size.value(),
            "bold": self.chk_bold.isChecked(),
            "color": self.color,
        }


class _TextStampItem(QGraphicsSimpleTextItem):
    """Movable text overlay; position syncs back to the _Stamp in mm."""

    def __init__(self, stamp: _Stamp, editor: "PdfEditorWidget", px_per_mm: float):
        super().__init__()
        self.stamp = stamp
        self._editor = editor
        self._px_per_mm = px_per_mm
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(10)
        self.refresh()
        self.setPos(stamp.x_mm * px_per_mm, stamp.y_mm * px_per_mm)

    def refresh(self):
        data = self.stamp.data
        font = QFont("Helvetica")
        size_px = max(1, round(data["font_size_pt"] * _MM_PER_PT * self._px_per_mm))
        font.setPixelSize(size_px)
        font.setBold(data.get("bold", False))
        self.setFont(font)
        self.setText(data.get("text") or " ")
        self.setBrush(QBrush(QColor(data.get("color", "#000000"))))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.stamp.x_mm = self.pos().x() / self._px_per_mm
            self.stamp.y_mm = self.pos().y() / self._px_per_mm
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self._editor.edit_stamp(self.stamp)


class _ImageStampItem(QGraphicsPixmapItem):
    """Movable image overlay; position syncs back to the _Stamp in mm."""

    def __init__(self, stamp: _Stamp, editor: "PdfEditorWidget", px_per_mm: float):
        super().__init__()
        self.stamp = stamp
        self._editor = editor
        self._px_per_mm = px_per_mm
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(10)
        self.refresh()
        self.setPos(stamp.x_mm * px_per_mm, stamp.y_mm * px_per_mm)

    def refresh(self):
        source = QPixmap(str(self.stamp.data["path"]))
        if source.isNull():
            return
        width_px = max(1, round(self.stamp.data["width_mm"] * self._px_per_mm))
        self.setPixmap(
            source.scaledToWidth(width_px, Qt.TransformationMode.SmoothTransformation)
        )

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.stamp.x_mm = self.pos().x() / self._px_per_mm
            self.stamp.y_mm = self.pos().y() / self._px_per_mm
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self._editor.edit_stamp(self.stamp)


class _PageView(QGraphicsView):
    """Preview view; Delete/Backspace removes the selected pending stamps."""

    delete_pressed = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            return
        super().keyPressEvent(event)


class PdfEditorWidget(QWidget):
    """F6·PDF — atelier de retouche des fichiers clients : pages (rotation,
    suppression, déplacement, duplication, page vierge), fusion, extraction,
    et tampons texte/image déplaçables (aplatis à l'enregistrement)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = PdfEditSession()
        self.current_index = 0
        self.stamps: list[_Stamp] = []
        self._stamp_items: list = []
        self.setup_ui()
        self._refresh_all()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Top toolbar ------------------------------------------------ #
        top = QFrame()
        top.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border-bottom:1px solid {_T.BORDER}; }}"
        )
        bar = QHBoxLayout(top)
        bar.setContentsMargins(16, 10, 16, 10)
        bar.setSpacing(8)

        self.btn_open = QPushButton("[OUVRIR PDF…]")
        self.btn_open.clicked.connect(self._open_pdf)
        self.btn_merge = QPushButton("[+ FUSIONNER…]")
        self.btn_merge.clicked.connect(self._merge_pdf)
        self.btn_undo = QPushButton("ANNULER")
        self.btn_undo.clicked.connect(self._undo)
        self.info_label = QLabel("Aucun PDF ouvert")
        self.info_label.setMinimumWidth(120)
        self.info_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; border:none;")
        self.btn_save = QPushButton("[ENREGISTRER SOUS…]")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save_as)

        bar.addWidget(self.btn_open)
        bar.addWidget(self.btn_merge)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.info_label, 1)
        bar.addWidget(self.btn_save)
        root.addWidget(top)

        # --- Page operations row ---------------------------------------- #
        ops = QFrame()
        ops.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border-bottom:1px solid {_T.BORDER}; }}"
        )
        ops_bar = QHBoxLayout(ops)
        ops_bar.setContentsMargins(16, 8, 16, 8)
        ops_bar.setSpacing(8)

        self.btn_rot_left = QPushButton("PIVOTER -90°")
        self.btn_rot_right = QPushButton("PIVOTER +90°")
        self.btn_add_page = QPushButton("+ PAGE")
        self.btn_duplicate = QPushButton("DUPLIQUER")
        self.btn_delete = QPushButton("SUPPRIMER")
        self.btn_move_left = QPushButton("◀ DÉPLACER")
        self.btn_move_right = QPushButton("DÉPLACER ▶")
        self.btn_extract = QPushButton("[EXTRAIRE…]")
        self.btn_text = QPushButton("[+ TEXTE]")
        self.btn_image = QPushButton("[+ IMAGE]")

        self.btn_rot_left.clicked.connect(lambda: self._rotate(-90))
        self.btn_rot_right.clicked.connect(lambda: self._rotate(90))
        self.btn_add_page.clicked.connect(self._add_page)
        self.btn_duplicate.clicked.connect(self._duplicate)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_move_left.clicked.connect(lambda: self._move(-1))
        self.btn_move_right.clicked.connect(lambda: self._move(1))
        self.btn_extract.clicked.connect(self._extract)
        self.btn_text.clicked.connect(self._add_text_stamp)
        self.btn_image.clicked.connect(self._add_image_stamp)

        for btn in (
            self.btn_rot_left, self.btn_rot_right, self.btn_add_page,
            self.btn_duplicate, self.btn_delete, self.btn_move_left, self.btn_move_right,
        ):
            ops_bar.addWidget(btn)
        ops_bar.addStretch()
        for btn in (self.btn_extract, self.btn_text, self.btn_image):
            ops_bar.addWidget(btn)
        root.addWidget(ops)

        # --- Body: thumbnails + preview ---------------------------------- #
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.thumb_list = QListWidget()
        self.thumb_list.setFixedWidth(170)
        self.thumb_list.setIconSize(QSize(_THUMB_W, int(_THUMB_W * 1.45)))
        self.thumb_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        self.thumb_list.setStyleSheet(
            f"QListWidget {{ background-color:{_T.BG_PANEL}; "
            f"border-right:1px solid {_T.BORDER}; }}"
        )
        body.addWidget(self.thumb_list)

        self.scene = QGraphicsScene(self)
        self.view = _PageView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setBackgroundBrush(QColor(_T.BG_APP))
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.delete_pressed.connect(self._delete_selected_stamps)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        body.addWidget(self.view, 1)

        root.addLayout(body, 1)

        # --- Status ------------------------------------------------------- #
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"color:{_T.ACCENT_TEXT}; font-size:11px; border:none; "
            f"background-color:{_T.BG_PANEL}; padding:6px 16px;"
        )
        root.addWidget(self.status_label)

    # ------------------------------------------------------------------ #
    #  Refresh                                                             #
    # ------------------------------------------------------------------ #

    def _refresh_all(self, keep_index: Optional[int] = None):
        open_ = self.session.is_open
        for btn in (
            self.btn_merge, self.btn_save, self.btn_rot_left, self.btn_rot_right,
            self.btn_add_page, self.btn_duplicate, self.btn_delete,
            self.btn_move_left, self.btn_move_right, self.btn_extract,
            self.btn_text, self.btn_image,
        ):
            btn.setEnabled(open_)
        self.btn_undo.setEnabled(open_ and self.session.can_undo)

        if not open_:
            self.thumb_list.clear()
            self._clear_stamp_items()
            self.pixmap_item.setPixmap(QPixmap())
            self.info_label.setText("Aucun PDF ouvert")
            return

        if keep_index is None:
            keep_index = self.current_index
        keep_index = max(0, min(keep_index, self.session.page_count - 1))

        self._rebuild_thumbnails()
        self.thumb_list.setCurrentRow(keep_index)
        self._show_page(keep_index)

        name = self.session.path.name if self.session.path else "(sans nom)"
        modified = self.session.modified or bool(self.stamps)
        parts = [name, f"{self.session.page_count} page(s)"]
        if self.stamps:
            parts.append(f"{len(self.stamps)} tampon(s) en attente")
        if modified:
            parts.append("modifié")
        self.info_label.setText("  ·  ".join(parts))

    def _rebuild_thumbnails(self):
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        for index in range(self.session.page_count):
            pix = self.session.render_page(index, target_width_px=_THUMB_W)
            item = QListWidgetItem(QIcon(_pixmap_from_fitz(pix)), f"Page {index + 1}")
            self.thumb_list.addItem(item)
        self.thumb_list.blockSignals(False)

    def _clear_stamp_items(self):
        for item in self._stamp_items:
            self.scene.removeItem(item)
        self._stamp_items = []

    def _show_page(self, index: int):
        self.current_index = index
        pix = self.session.render_page(index, target_width_px=_PREVIEW_W)
        pixmap = _pixmap_from_fitz(pix)
        self.pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())

        # Pending stamps of this page, as movable overlay objects.
        self._clear_stamp_items()
        px_per_mm = self._px_per_mm()
        if px_per_mm > 0:
            for stamp in self.stamps:
                if stamp.page != index:
                    continue
                cls = _TextStampItem if stamp.kind == "text" else _ImageStampItem
                item = cls(stamp, self, px_per_mm)
                self.scene.addItem(item)
                self._stamp_items.append(item)

        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _px_per_mm(self) -> float:
        pixmap_width = self.pixmap_item.pixmap().width()
        if pixmap_width <= 0 or not self.session.is_open:
            return 0.0
        page_w_mm, _ = self.session.page_size_mm(self.current_index)
        return pixmap_width / page_w_mm if page_w_mm > 0 else 0.0

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.session.is_open:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _selected_indices(self) -> list:
        rows = sorted({i.row() for i in self.thumb_list.selectedIndexes()})
        return rows or ([self.current_index] if self.session.is_open else [])

    def _on_thumb_selected(self, row: int):
        if row >= 0 and self.session.is_open:
            self._show_page(row)

    # ------------------------------------------------------------------ #
    #  Pending stamps                                                      #
    # ------------------------------------------------------------------ #

    def _add_text_stamp(self):
        dialog = _StampTextDialog(self)
        if not dialog.exec() or not dialog.text_input.text().strip():
            return
        self._place_stamp(_Stamp(kind="text", page=self.current_index,
                                 x_mm=0, y_mm=0, data=dialog.values()))

    def _add_image_stamp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif)"
        )
        if not path:
            return
        width_mm, ok = QInputDialog.getDouble(
            self, "Largeur de l'image", "Largeur sur la page (mm) :", 30.0, 1.0, 1000.0, 1
        )
        if not ok:
            return
        self._place_stamp(_Stamp(kind="image", page=self.current_index, x_mm=0, y_mm=0,
                                 data={"path": Path(path), "width_mm": width_mm}))

    def _place_stamp(self, stamp: _Stamp):
        """Drops the new stamp at the center of the current page, selected and
        ready to drag."""
        page_w_mm, page_h_mm = self.session.page_size_mm(self.current_index)
        stamp.x_mm = page_w_mm * 0.35
        stamp.y_mm = page_h_mm * 0.45
        self.stamps.append(stamp)
        self._refresh_all()
        for item in self._stamp_items:
            if getattr(item, "stamp", None) is stamp:
                item.setSelected(True)
        self.status_label.setText(
            "Tampon posé — déplacez-le à la souris, double-clic pour le modifier, "
            "Suppr pour le retirer. Il sera gravé dans le PDF à l'enregistrement."
        )

    def edit_stamp(self, stamp: _Stamp):
        """Double-click re-edit: text stamps reopen the full dialog, image
        stamps re-ask their printed width."""
        if stamp.kind == "text":
            dialog = _StampTextDialog(self, stamp=stamp)
            if not dialog.exec() or not dialog.text_input.text().strip():
                return
            stamp.data = dialog.values()
        else:
            width_mm, ok = QInputDialog.getDouble(
                self, "Largeur de l'image", "Largeur sur la page (mm) :",
                stamp.data.get("width_mm", 30.0), 1.0, 1000.0, 1,
            )
            if not ok:
                return
            stamp.data["width_mm"] = width_mm
        for item in self._stamp_items:
            if getattr(item, "stamp", None) is stamp:
                item.refresh()

    def _delete_selected_stamps(self):
        selected = [i for i in self._stamp_items if i.isSelected()]
        if not selected:
            return
        doomed = {id(item.stamp) for item in selected}
        self.stamps = [s for s in self.stamps if id(s) not in doomed]
        self._refresh_all()
        self.status_label.setText(f"{len(selected)} tampon(s) retiré(s)")

    def _apply_stamps(self) -> bool:
        """Flattens every pending stamp into the PDF (called before saving and
        before any page-structure operation, so page indices never drift)."""
        if not self.stamps:
            return True
        for stamp in list(self.stamps):
            try:
                if stamp.kind == "text":
                    self.session.add_text(
                        stamp.page, stamp.x_mm, stamp.y_mm, stamp.data["text"],
                        font_size_pt=stamp.data["font_size_pt"],
                        color=stamp.data["color"], bold=stamp.data["bold"],
                    )
                else:
                    self.session.add_image(
                        stamp.page, stamp.x_mm, stamp.y_mm,
                        stamp.data["width_mm"], stamp.data["path"],
                    )
            except PdfEditError as e:
                QMessageBox.warning(self, "Tampon non appliqué", str(e))
                return False
            self.stamps.remove(stamp)
        return True

    # ------------------------------------------------------------------ #
    #  File operations                                                     #
    # ------------------------------------------------------------------ #

    def _open_pdf(self):
        if self.session.modified or self.stamps:
            reply = QMessageBox.question(
                self, "Modifications non enregistrées",
                "Le PDF en cours a des modifications non enregistrées. Continuer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            self.session.open(Path(path))
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.stamps = []
        self.status_label.setText("")
        self._refresh_all(keep_index=0)

    def _merge_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Fusionner un PDF", "", "PDF (*.pdf)")
        if not path:
            return
        if not self._apply_stamps():
            return
        try:
            added = self.session.merge_pdf(Path(path))
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.status_label.setText(f"{added} page(s) ajoutée(s) depuis {Path(path).name}")
        self._refresh_all(keep_index=self.session.page_count - 1)

    def _save_as(self):
        if not self._apply_stamps():
            return
        default = self.session.path.name if self.session.path else "document.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", default, "PDF (*.pdf)")
        if not path:
            return
        try:
            self.session.save_as(Path(path))
        except (PdfEditError, OSError) as e:
            QMessageBox.warning(self, "Erreur", f"Enregistrement impossible : {e}")
            return
        self.status_label.setText(f"Enregistré : {path}")
        self._refresh_all()

    def _undo(self):
        if self.session.undo():
            self.status_label.setText("Dernière opération annulée")
            self._refresh_all()

    # ------------------------------------------------------------------ #
    #  Page operations                                                     #
    # ------------------------------------------------------------------ #

    def _guarded(self, action, keep_index: Optional[int] = None):
        """Runs a page-structure operation. Pending stamps are flattened first
        so their page indices can't be invalidated by the reorganization."""
        if not self._apply_stamps():
            return
        try:
            action()
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self._refresh_all(keep_index=keep_index)

    def _rotate(self, degrees: int):
        self._guarded(lambda: self.session.rotate_page(self.current_index, degrees))

    def _add_page(self):
        index = self.current_index
        self._guarded(
            lambda: self.session.insert_blank_page(index), keep_index=index + 1
        )

    def _duplicate(self):
        self._guarded(lambda: self.session.duplicate_page(self.current_index))

    def _delete(self):
        indices = self._selected_indices()
        self._guarded(
            lambda: self.session.delete_pages(indices),
            keep_index=min(indices) if indices else 0,
        )

    def _move(self, delta: int):
        src = self.current_index
        dest = src + delta
        if not (0 <= dest < self.session.page_count):
            return
        self._guarded(lambda: self.session.move_page(src, dest), keep_index=dest)

    def _extract(self):
        indices = self._selected_indices()
        if not indices:
            return
        if not self._apply_stamps():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Extraire les pages sélectionnées", "extrait.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            self.session.extract_pages(indices, Path(path))
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.status_label.setText(f"{len(indices)} page(s) extraite(s) vers {path}")
