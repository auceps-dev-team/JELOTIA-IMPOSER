from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.models.domain import FileItem, JobSettings, PlacedItem, PreflightStatus, Sheet
from src.ui.theme import ThemeManager

_T = ThemeManager

_ITEM_BRUSH = QBrush(QColor(255, 122, 26, 150))
_ITEM_PEN = QPen(QColor(_T.BORDER_FIELD))
_ITEM_PEN.setWidthF(0.6)
_OVERLAP_PEN = QPen(QColor(_T.STATE_ERR))
_OVERLAP_PEN.setWidthF(1.2)
_LABEL_BACKDROP = QBrush(QColor(0, 0, 0, 150))
_GRID_PEN = QPen(QColor(255, 255, 255, 40))
_GRID_PEN.setWidthF(0.3)

_SUPPORTED_FILES_FILTER = (
    "Fichiers supportés (*.pdf *.tiff *.tif *.png *.jpg *.jpeg)"
    ";;PDF (*.pdf)"
    ";;Images (*.tiff *.tif *.png *.jpg *.jpeg)"
    ";;Tous (*.*)"
)


def job_assets_dir(job_id) -> Path:
    """Permanent (never auto-cleaned) home for files added to a sheet after
    the job has already finished — unlike the ephemeral per-job folder under
    config.processing_dir (deleted by finalize_job_sheets once the initial
    sheet PDF is generated), this must survive indefinitely: manual sheet
    regeneration re-reads every item's source file from disk each time."""
    from src.utils.config import config

    path = config.output_dir / str(job_id) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _render_thumbnail(source_path: Path, rotated: bool, max_px: int = 220) -> Optional[QPixmap]:
    """Rasterizes the item's actual artwork (PDF page or raster image) so the
    editor shows the real element instead of a blank placeholder while it's
    being dragged."""
    try:
        doc = fitz.open(str(source_path))
        page = doc[0]
        page_w, page_h = page.rect.width, page.rect.height
        if page_w <= 0 or page_h <= 0:
            return None
        zoom = max_px / max(page_w, page_h)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        doc.close()
    except Exception:
        return None

    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        return None
    if rotated:
        pixmap = pixmap.transformed(QTransform().rotate(90), Qt.TransformationMode.SmoothTransformation)
    return pixmap


class _DraggableItem(QGraphicsRectItem):
    """A movable rectangle representing one PlacedItem on the sheet, in mm units."""

    def __init__(self, placed_item: PlacedItem, editor: "SheetEditorWidget"):
        super().__init__(0, 0, placed_item.width_mm, placed_item.height_mm)
        self.placed_item = placed_item
        self._editor = editor

        self.setPos(placed_item.x_mm, placed_item.y_mm)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setPen(_ITEM_PEN)

        self._build_children()

    def _build_children(self) -> None:
        """(Re)builds the thumbnail/label/backdrop child items from the
        PlacedItem's current width/height/rotation — called at construction
        time and again after a rotate or resize, since those change the
        artwork's on-sheet footprint."""
        for child in list(self.childItems()):
            child.setParentItem(None)
            if child.scene():
                child.scene().removeItem(child)

        w, h = self.placed_item.width_mm, self.placed_item.height_mm
        thumbnail = _render_thumbnail(Path(str(self.placed_item.source_path)), self.placed_item.rotated)
        has_thumbnail = thumbnail is not None and thumbnail.width() > 0 and thumbnail.height() > 0
        if has_thumbnail:
            self.setBrush(Qt.BrushStyle.NoBrush)
            pixmap_item = QGraphicsPixmapItem(thumbnail, self)
            pixmap_item.setTransform(QTransform().scale(w / thumbnail.width(), h / thumbnail.height()))
            pixmap_item.setZValue(-1)
        else:
            self.setBrush(_ITEM_BRUSH)

        label_text = f"{Path(str(self.placed_item.source_path)).name}\n{w:.0f}×{h:.0f}mm"
        font_size = max(3.0, min(h, w) * 0.12)

        if has_thumbnail:
            backdrop = QGraphicsRectItem(0, 0, w, font_size * 2.6, self)
            backdrop.setBrush(_LABEL_BACKDROP)
            backdrop.setPen(QPen(Qt.PenStyle.NoPen))
            backdrop.setZValue(0)

        label = QGraphicsSimpleTextItem(label_text, self)
        font = label.font()
        font.setPointSizeF(font_size)
        label.setFont(font)
        label.setPos(2, 2)
        label.setZValue(1)
        label.setBrush(QBrush(QColor(20, 10, 0)) if not has_thumbnail else QBrush(QColor(255, 255, 255)))

    def _clamp_to_sheet(self) -> None:
        """Re-clamps the current position against the (possibly just resized)
        rect and sheet bounds — used after rotate/resize, where the rect
        changes without going through itemChange's drag-driven clamp."""
        sheet = self._editor.sheet
        w, h = self.rect().width(), self.rect().height()
        x = min(max(0.0, self.pos().x()), max(0.0, sheet.width_mm - w))
        y = min(max(0.0, self.pos().y()), max(0.0, sheet.height_mm - h))
        self.setPos(x, y)

    def rotate_90(self) -> None:
        pi = self.placed_item
        pi.width_mm, pi.height_mm = pi.height_mm, pi.width_mm
        pi.rotated = not pi.rotated
        self.setRect(0, 0, pi.width_mm, pi.height_mm)
        self._build_children()
        self._clamp_to_sheet()

    def resize_to(self, width_mm: float, height_mm: float) -> None:
        pi = self.placed_item
        pi.width_mm, pi.height_mm = width_mm, height_mm
        self.setRect(0, 0, width_mm, height_mm)
        self._build_children()
        self._clamp_to_sheet()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            sheet = self._editor.sheet
            w, h = self.rect().width(), self.rect().height()
            x = min(max(0.0, value.x()), max(0.0, sheet.width_mm - w))
            y = min(max(0.0, value.y()), max(0.0, sheet.height_mm - h))

            grid = self._editor.snap_grid_mm
            if grid:
                x = round(x / grid) * grid
                y = round(y / grid) * grid
                x = min(max(0.0, x), max(0.0, sheet.width_mm - w))
                y = min(max(0.0, y), max(0.0, sheet.height_mm - h))

            return QPointF(x, y)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.placed_item.x_mm = self.pos().x()
            self.placed_item.y_mm = self.pos().y()
            self._editor.refresh_overlaps()

        return super().itemChange(change, value)


class _EditorView(QGraphicsView):
    """Plain QGraphicsView, except 'R' rotates the current selection —
    keyboard shortcuts on the editor widget itself never see key events once
    the view has focus (which it does as soon as the user clicks an item)."""

    def __init__(self, scene: QGraphicsScene, editor: "SheetEditorWidget"):
        super().__init__(scene)
        self._editor = editor

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_R:
            self._editor.rotate_selected()
            return
        super().keyPressEvent(event)


class SheetEditorWidget(QWidget):
    """Interactive drag-and-drop editor for a Sheet's item layout."""

    applied = Signal()
    cancelled = Signal()

    def __init__(self, sheet: Sheet, settings: JobSettings, parent=None):
        super().__init__(parent)
        self.sheet = sheet
        self.settings = settings

        self._original_items = list(sheet.items)
        self._original_states = {
            id(it): (it.x_mm, it.y_mm, it.width_mm, it.height_mm, it.rotated) for it in sheet.items
        }
        self._draggables: list[_DraggableItem] = []
        # New FileItems created via "+ Ajouter un fichier" this session — the
        # caller (SheetPreviewWidget._apply_edit) merges these into the job's
        # persisted file list on Appliquer; on Annuler they're discarded here.
        self.added_file_items: List[FileItem] = []
        self.snap_grid_mm: Optional[float] = None
        self._grid_lines: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scene = QGraphicsScene(0, 0, sheet.width_mm, sheet.height_mm)
        boundary = self.scene.addRect(
            0, 0, sheet.width_mm, sheet.height_mm,
            QPen(QColor(_T.ACCENT)), QBrush(QColor(_T.BG_APP)),
        )
        boundary.setZValue(-10)
        self.scene.selectionChanged.connect(self._on_selection_changed)

        for placed_item in sheet.items:
            draggable = _DraggableItem(placed_item, self)
            self.scene.addItem(draggable)
            self._draggables.append(draggable)

        self.view = _EditorView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QColor(_T.BG_PANEL))
        layout.addWidget(self.view)

        self._setup_tools_bar(layout)
        self._setup_bottom_bar(layout)

    def _setup_tools_bar(self, parent_layout: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)

        self.btn_add_file = QPushButton("[+ AJOUTER UN FICHIER]")
        self.btn_add_file.clicked.connect(self.add_file)

        self.btn_rotate = QPushButton("PIVOTER (R)")
        self.btn_rotate.clicked.connect(self.rotate_selected)

        self.chk_snap = QCheckBox("ALIGNER SUR GRILLE")
        self.chk_snap.toggled.connect(self._toggle_grid)
        self.spin_grid = QDoubleSpinBox()
        self.spin_grid.setRange(1.0, 200.0)
        self.spin_grid.setValue(5.0)
        self.spin_grid.setSuffix(" mm")
        self.spin_grid.valueChanged.connect(self._on_grid_size_changed)

        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(1.0, 5000.0)
        self.spin_width.setSuffix(" mm")
        self.spin_width.setToolTip(
            "Les PDF conservent leur ratio (mise en page centrée dans la nouvelle taille).\n"
            "Les images matricielles (JPEG/PNG/TIFF) sont étirées à la taille demandée."
        )
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(1.0, 5000.0)
        self.spin_height.setSuffix(" mm")
        self.spin_height.setToolTip(self.spin_width.toolTip())
        self.btn_resize = QPushButton("APPLIQUER LA TAILLE")
        self.btn_resize.clicked.connect(self._apply_resize)

        for w in (self.spin_width, self.spin_height, self.btn_resize):
            w.setEnabled(False)

        bar.addWidget(self.btn_add_file)
        bar.addWidget(self.btn_rotate)
        bar.addSpacing(20)
        bar.addWidget(self.chk_snap)
        bar.addWidget(self.spin_grid)
        bar.addStretch()
        bar.addWidget(QLabel("Taille :"))
        bar.addWidget(self.spin_width)
        bar.addWidget(QLabel("×"))
        bar.addWidget(self.spin_height)
        bar.addWidget(self.btn_resize)

        bar_widget = QWidget()
        bar_widget.setLayout(bar)
        parent_layout.addWidget(bar_widget)

    def _setup_bottom_bar(self, parent_layout: QVBoxLayout) -> None:
        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 10, 10, 10)
        self.hint_label = QLabel(
            "Glissez les éléments pour les repositionner. Sélectionnez un élément pour le "
            "pivoter ou changer sa taille."
        )
        self.btn_cancel = QPushButton("ANNULER")
        self.btn_apply = QPushButton("[APPLIQUER]")
        self.btn_apply.setObjectName("primary")
        bottom.addWidget(self.hint_label)
        bottom.addStretch()
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_apply)
        parent_layout.addLayout(bottom)

        self.btn_apply.clicked.connect(self.applied.emit)
        self.btn_cancel.clicked.connect(self._on_cancel)

    # ------------------------------------------------------------------ #
    #  Selection-driven tools: resize, rotate                             #
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self) -> None:
        selected = [d for d in self._draggables if d.isSelected()]
        if len(selected) == 1:
            pi = selected[0].placed_item
            for spin, value in ((self.spin_width, pi.width_mm), (self.spin_height, pi.height_mm)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
            enabled = True
        else:
            enabled = False
        for w in (self.spin_width, self.spin_height, self.btn_resize):
            w.setEnabled(enabled)

    def _apply_resize(self) -> None:
        selected = [d for d in self._draggables if d.isSelected()]
        if len(selected) != 1:
            return
        selected[0].resize_to(self.spin_width.value(), self.spin_height.value())
        self.refresh_overlaps()

    def rotate_selected(self) -> None:
        selected = [d for d in self._draggables if d.isSelected()]
        if not selected:
            return
        for draggable in selected:
            draggable.rotate_90()
        self.refresh_overlaps()
        self._on_selection_changed()  # spinboxes must reflect the swapped dimensions

    # ------------------------------------------------------------------ #
    #  Grid snap                                                           #
    # ------------------------------------------------------------------ #

    def _toggle_grid(self, checked: bool) -> None:
        self.snap_grid_mm = self.spin_grid.value() if checked else None
        self._draw_grid()

    def _on_grid_size_changed(self, _value: float) -> None:
        if self.chk_snap.isChecked():
            self.snap_grid_mm = self.spin_grid.value()
            self._draw_grid()

    def _draw_grid(self) -> None:
        for line in self._grid_lines:
            self.scene.removeItem(line)
        self._grid_lines = []

        if not self.snap_grid_mm:
            return

        step = self.snap_grid_mm
        x = step
        while x < self.sheet.width_mm:
            line = self.scene.addLine(x, 0, x, self.sheet.height_mm, _GRID_PEN)
            line.setZValue(-9)
            self._grid_lines.append(line)
            x += step
        y = step
        while y < self.sheet.height_mm:
            line = self.scene.addLine(0, y, self.sheet.width_mm, y, _GRID_PEN)
            line.setZValue(-9)
            self._grid_lines.append(line)
            y += step

    # ------------------------------------------------------------------ #
    #  Adding new files                                                    #
    # ------------------------------------------------------------------ #

    def add_file(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Ajouter des fichiers à la planche", "", _SUPPORTED_FILES_FILTER
        )
        if not file_paths:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from src.core.processors.job_processor import process_job_files

            assets_dir = job_assets_dir(self.sheet.job_id)
            file_items = process_job_files(
                self.sheet.job_id, [Path(p) for p in file_paths], self.settings, work_dir=assets_dir
            )
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Échec du traitement des fichiers : {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        errors = [it for it in file_items if it.preflight_status == PreflightStatus.ERROR]
        valid_items = [it for it in file_items if it.preflight_status != PreflightStatus.ERROR]

        if errors:
            details = "\n".join(
                f"- {Path(str(it.path)).name} : " + "; ".join(e.message for e in it.preflight_errors)
                for it in errors
            )
            QMessageBox.warning(
                self, "Fichiers rejetés",
                f"{len(errors)} fichier(s) n'ont pas pu être ajoutés :\n{details}",
            )

        for item in valid_items:
            self.added_file_items.append(item)
            placed = PlacedItem(
                file_item_id=item.id,
                source_path=item.path,
                x_mm=0.0,
                y_mm=0.0,
                width_mm=item.width_mm,
                height_mm=item.height_mm,
                rotated=False,
            )
            self.sheet.items.append(placed)
            draggable = _DraggableItem(placed, self)
            self.scene.addItem(draggable)
            self._draggables.append(draggable)

        self.refresh_overlaps()

    # ------------------------------------------------------------------ #
    #  Overlap detection, revert, teardown                                 #
    # ------------------------------------------------------------------ #

    def refresh_overlaps(self) -> None:
        for a in self._draggables:
            overlapping = any(
                a is not b and a.sceneBoundingRect().intersects(b.sceneBoundingRect())
                for b in self._draggables
            )
            a.setPen(_OVERLAP_PEN if overlapping else _ITEM_PEN)

    def has_overlaps(self) -> bool:
        return any(
            a is not b and a.sceneBoundingRect().intersects(b.sceneBoundingRect())
            for a in self._draggables
            for b in self._draggables
        )

    def revert(self) -> None:
        """Restores every original item's position/size/rotation to when the
        editor was opened, and discards any items added during this session
        (used when the parent is already handling teardown)."""
        self.sheet.items[:] = self._original_items
        for item in self._original_items:
            x, y, w, h, rotated = self._original_states[id(item)]
            item.x_mm, item.y_mm = x, y
            item.width_mm, item.height_mm = w, h
            item.rotated = rotated

        for file_item in self.added_file_items:
            try:
                Path(str(file_item.path)).unlink(missing_ok=True)
            except OSError:
                pass
        self.added_file_items = []

    def _on_cancel(self):
        self.revert()
        self.cancelled.emit()

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
