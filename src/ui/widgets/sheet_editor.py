from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.models.domain import PlacedItem, Sheet

_ITEM_BRUSH = QBrush(QColor(217, 122, 39, 160))
_ITEM_PEN = QPen(QColor(60, 30, 0, 220))
_ITEM_PEN.setWidthF(0.6)
_OVERLAP_PEN = QPen(QColor(220, 30, 30))
_OVERLAP_PEN.setWidthF(1.2)
_LABEL_BACKDROP = QBrush(QColor(0, 0, 0, 150))


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

        thumbnail = _render_thumbnail(Path(str(placed_item.source_path)), placed_item.rotated)
        has_thumbnail = thumbnail is not None and thumbnail.width() > 0 and thumbnail.height() > 0
        if has_thumbnail:
            self.setBrush(Qt.BrushStyle.NoBrush)
            pixmap_item = QGraphicsPixmapItem(thumbnail, self)
            pixmap_item.setTransform(
                QTransform().scale(
                    placed_item.width_mm / thumbnail.width(),
                    placed_item.height_mm / thumbnail.height(),
                )
            )
            pixmap_item.setZValue(-1)
        else:
            self.setBrush(_ITEM_BRUSH)

        label_text = f"{Path(str(placed_item.source_path)).name}\n{placed_item.width_mm:.0f}×{placed_item.height_mm:.0f}mm"
        font_size = max(3.0, min(placed_item.height_mm, placed_item.width_mm) * 0.12)

        if has_thumbnail:
            backdrop = QGraphicsRectItem(0, 0, placed_item.width_mm, font_size * 2.6, self)
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

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            sheet = self._editor.sheet
            w, h = self.rect().width(), self.rect().height()
            x = min(max(0.0, value.x()), max(0.0, sheet.width_mm - w))
            y = min(max(0.0, value.y()), max(0.0, sheet.height_mm - h))
            return QPointF(x, y)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.placed_item.x_mm = self.pos().x()
            self.placed_item.y_mm = self.pos().y()
            self._editor.refresh_overlaps()

        return super().itemChange(change, value)


class SheetEditorWidget(QWidget):
    """Interactive drag-and-drop editor for a Sheet's item layout."""

    applied = Signal()
    cancelled = Signal()

    def __init__(self, sheet: Sheet, parent=None):
        super().__init__(parent)
        self.sheet = sheet
        self._original_positions = [(it.x_mm, it.y_mm) for it in sheet.items]
        self._draggables: list[_DraggableItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scene = QGraphicsScene(0, 0, sheet.width_mm, sheet.height_mm)
        boundary = self.scene.addRect(
            0, 0, sheet.width_mm, sheet.height_mm,
            QPen(QColor(255, 255, 255, 120)), QBrush(QColor(45, 45, 45)),
        )
        boundary.setZValue(-10)

        for placed_item in sheet.items:
            draggable = _DraggableItem(placed_item, self)
            self.scene.addItem(draggable)
            self._draggables.append(draggable)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(Qt.GlobalColor.darkGray)
        layout.addWidget(self.view)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 10, 10, 10)
        self.hint_label = QLabel("Glissez les éléments pour les repositionner sur la planche.")
        self.btn_cancel = QPushButton("Annuler")
        self.btn_apply = QPushButton("Appliquer")
        self.btn_apply.setObjectName("primary")
        bottom.addWidget(self.hint_label)
        bottom.addStretch()
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_apply)
        layout.addLayout(bottom)

        self.btn_apply.clicked.connect(self.applied.emit)
        self.btn_cancel.clicked.connect(self._on_cancel)

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
        """Restores every item to its position when the editor was opened, without
        emitting any signal (used when the parent is already handling teardown)."""
        for placed_item, (x, y) in zip(self.sheet.items, self._original_positions):
            placed_item.x_mm, placed_item.y_mm = x, y

    def _on_cancel(self):
        self.revert()
        self.cancelled.emit()

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
