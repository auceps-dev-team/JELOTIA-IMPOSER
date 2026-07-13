from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
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


def _pixmap_from_fitz(pix: fitz.Pixmap) -> QPixmap:
    image = QImage(
        pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
    ).copy()
    return QPixmap.fromImage(image)


class _StampTextDialog(QDialog):
    """Content/size/bold/color for a text stamp; placement happens with the
    next click on the page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter un texte")
        self.color = "#000000"

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Ex : BON À TIRER")
        form.addRow("Texte :", self.text_input)
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(4.0, 96.0)
        self.spin_size.setValue(14.0)
        self.spin_size.setSuffix(" pt")
        form.addRow("Taille :", self.spin_size)
        self.chk_bold = QCheckBox("Gras")
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


class _ClickablePageView(QGraphicsView):
    """Page preview that reports clicks in scene coordinates (used to place
    text/image stamps at the clicked spot)."""

    clicked = Signal(float, float)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            self.clicked.emit(pos.x(), pos.y())
        super().mousePressEvent(event)


class PdfEditorWidget(QWidget):
    """F6·PDF — atelier de retouche des fichiers clients : pages (rotation,
    suppression, déplacement, duplication), fusion, extraction, tampons texte
    et image, avec annulation et enregistrement sous."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = PdfEditSession()
        self.current_index = 0
        self._pending_stamp: Optional[tuple] = None
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
        self.btn_duplicate = QPushButton("DUPLIQUER")
        self.btn_delete = QPushButton("SUPPRIMER")
        self.btn_move_left = QPushButton("◀ DÉPLACER")
        self.btn_move_right = QPushButton("DÉPLACER ▶")
        self.btn_extract = QPushButton("[EXTRAIRE…]")
        self.btn_text = QPushButton("[+ TEXTE]")
        self.btn_image = QPushButton("[+ IMAGE]")

        self.btn_rot_left.clicked.connect(lambda: self._rotate(-90))
        self.btn_rot_right.clicked.connect(lambda: self._rotate(90))
        self.btn_duplicate.clicked.connect(self._duplicate)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_move_left.clicked.connect(lambda: self._move(-1))
        self.btn_move_right.clicked.connect(lambda: self._move(1))
        self.btn_extract.clicked.connect(self._extract)
        self.btn_text.clicked.connect(self._start_text_stamp)
        self.btn_image.clicked.connect(self._start_image_stamp)

        for btn in (
            self.btn_rot_left, self.btn_rot_right, self.btn_duplicate, self.btn_delete,
            self.btn_move_left, self.btn_move_right,
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
        self.view = _ClickablePageView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setBackgroundBrush(QColor(_T.BG_APP))
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.clicked.connect(self._on_page_clicked)
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
            self.btn_duplicate, self.btn_delete, self.btn_move_left,
            self.btn_move_right, self.btn_extract, self.btn_text, self.btn_image,
        ):
            btn.setEnabled(open_)
        self.btn_undo.setEnabled(open_ and self.session.can_undo)

        if not open_:
            self.thumb_list.clear()
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
        flag = "  ·  modifié" if self.session.modified else ""
        self.info_label.setText(f"{name}  ·  {self.session.page_count} page(s){flag}")

    def _rebuild_thumbnails(self):
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        for index in range(self.session.page_count):
            pix = self.session.render_page(index, target_width_px=_THUMB_W)
            item = QListWidgetItem(QIcon(_pixmap_from_fitz(pix)), f"Page {index + 1}")
            self.thumb_list.addItem(item)
        self.thumb_list.blockSignals(False)

    def _show_page(self, index: int):
        self.current_index = index
        pix = self.session.render_page(index, target_width_px=_PREVIEW_W)
        pixmap = _pixmap_from_fitz(pix)
        self.pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

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
    #  File operations                                                     #
    # ------------------------------------------------------------------ #

    def _open_pdf(self):
        if self.session.modified:
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
        self._pending_stamp = None
        self.status_label.setText("")
        self._refresh_all(keep_index=0)

    def _merge_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Fusionner un PDF", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            added = self.session.merge_pdf(Path(path))
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.status_label.setText(f"{added} page(s) ajoutée(s) depuis {Path(path).name}")
        self._refresh_all(keep_index=self.session.page_count - 1)

    def _save_as(self):
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
        try:
            action()
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self._refresh_all(keep_index=keep_index)

    def _rotate(self, degrees: int):
        self._guarded(lambda: self.session.rotate_page(self.current_index, degrees))

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

    # ------------------------------------------------------------------ #
    #  Stamps (click-to-place)                                             #
    # ------------------------------------------------------------------ #

    def _start_text_stamp(self):
        dialog = _StampTextDialog(self)
        if not dialog.exec() or not dialog.text_input.text().strip():
            return
        self._pending_stamp = (
            "text",
            {
                "text": dialog.text_input.text(),
                "font_size_pt": dialog.spin_size.value(),
                "bold": dialog.chk_bold.isChecked(),
                "color": dialog.color,
            },
        )
        self.status_label.setText("Cliquez sur la page pour placer le texte…")

    def _start_image_stamp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif)"
        )
        if not path:
            return
        from PySide6.QtWidgets import QInputDialog

        width_mm, ok = QInputDialog.getDouble(
            self, "Largeur de l'image", "Largeur sur la page (mm) :", 30.0, 1.0, 1000.0, 1
        )
        if not ok:
            return
        self._pending_stamp = ("image", {"path": Path(path), "width_mm": width_mm})
        self.status_label.setText("Cliquez sur la page pour placer l'image…")

    def _on_page_clicked(self, x_scene: float, y_scene: float):
        if self._pending_stamp is None or not self.session.is_open:
            return
        pixmap_width = self.pixmap_item.pixmap().width()
        if pixmap_width <= 0:
            return
        page_w_mm, page_h_mm = self.session.page_size_mm(self.current_index)
        x_mm = x_scene / pixmap_width * page_w_mm
        y_mm = y_scene / self.pixmap_item.pixmap().height() * page_h_mm
        if not (0 <= x_mm <= page_w_mm and 0 <= y_mm <= page_h_mm):
            return

        kind, data = self._pending_stamp
        self._pending_stamp = None
        try:
            if kind == "text":
                self.session.add_text(
                    self.current_index, x_mm, y_mm, data["text"],
                    font_size_pt=data["font_size_pt"], color=data["color"],
                    bold=data["bold"],
                )
            else:
                self.session.add_image(
                    self.current_index, x_mm, y_mm, data["width_mm"], data["path"]
                )
        except PdfEditError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        self.status_label.setText("")
        self._refresh_all()
