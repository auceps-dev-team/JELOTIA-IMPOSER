from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import ThemeManager

_T = ThemeManager

STATUS_COLORS = {
    "OK": _T.STATE_OK,
    "DONE": _T.STATE_OK,
    "RUNNING": _T.ACCENT_TEXT,
    "PROCESSING": _T.ACCENT_TEXT,
    "PENDING": _T.STATE_WARN,
    "QUEUE": _T.STATE_WARN,
    "ERROR": _T.STATE_ERR,
    "STOP": _T.STATE_ERR,
}


def status_bracket_text(status: str) -> str:
    """`RUNNING` -> `[RUNNING]`, matching the design system's bracketed state labels."""
    return f"[{status}]"


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status.upper(), _T.TEXT_MUTE)


class LedDot(QFrame):
    """Small colored status dot, optionally with a soft glow — matches the
    design system's LED indicators (green=ok, orange=running, red=error)."""

    def __init__(self, color: str, size: int = 8, glow: bool = True, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._apply_color(color, glow)

    def _apply_color(self, color: str, glow: bool) -> None:
        self.setStyleSheet(
            f"background-color:{color}; border-radius:{self._size // 2}px; border:none;"
        )
        if glow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setColor(QColor(color))
            effect.setBlurRadius(self._size)
            effect.setOffset(0, 0)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def set_color(self, color: str, glow: bool = True) -> None:
        self._apply_color(color, glow)


class StripedBar(QWidget):
    """Vertical bar filled with the design system's diagonal-free horizontal
    stripe motif (repeating 6px accent / 2px shade bands), used by the
    production chart. Height is driven by set_fill_ratio (0..1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio = 0.0
        self.setMinimumWidth(4)

    def set_fill_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        full_h = self.height()
        fill_h = round(full_h * self._ratio)
        top = full_h - fill_h
        band = 8
        stripe = 6
        y = top
        while y < full_h:
            band_h = min(stripe, full_h - y)
            painter.fillRect(0, y, self.width(), band_h, QColor(_T.ACCENT))
            y += stripe
            if y < full_h:
                shade_h = min(band - stripe, full_h - y)
                painter.fillRect(0, y, self.width(), shade_h, QColor("#D96010"))
                y += band - stripe
        painter.end()


class StatCard(QFrame):
    """KPI tile: LED + uppercase label, big mono value, small trend/context
    line, optional thin progress bar. Set highlight=True for the one
    "emphasized" tile per screen (orange border, orange value)."""

    def __init__(
        self,
        label: str,
        value: str = "0",
        led_color: Optional[str] = None,
        highlight: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._highlight = highlight
        border_color = _T.ACCENT if highlight else _T.BORDER
        self.setStyleSheet(
            f"StatCard {{ background-color:{_T.BG_PANEL}; border:1px solid {border_color}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        if led_color:
            self.led = LedDot(led_color)
            header.addWidget(self.led)
        else:
            self.led = None
        self.label_widget = QLabel(label.upper())
        self.label_widget.setStyleSheet(
            f"color:{_T.TEXT_MUTE}; font-size:11px; letter-spacing:1.5px; border:none; background:transparent;"
        )
        header.addWidget(self.label_widget)
        header.addStretch()
        layout.addLayout(header)

        value_color = _T.ACCENT_TEXT if highlight else _T.TEXT_1
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            f"color:{value_color}; font-size:32px; font-weight:600; border:none; background:transparent; margin-top:6px;"
        )
        layout.addWidget(self.value_label)

        self.trend_label = QLabel("")
        self.trend_label.setStyleSheet(
            f"color:{_T.TEXT_MUTE}; font-size:11px; border:none; background:transparent;"
        )
        layout.addWidget(self.trend_label)

        self.progress: Optional[QProgressBar] = None

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_trend(self, text: str, color: Optional[str] = None) -> None:
        self.trend_label.setText(text)
        if color:
            self.trend_label.setStyleSheet(
                f"color:{color}; font-size:11px; border:none; background:transparent;"
            )

    def add_progress_bar(self, value: float) -> None:
        """Adds (or updates) a thin flat progress bar under the trend line."""
        if self.progress is None:
            self.progress = QProgressBar()
            self.progress.setFixedHeight(6)
            self.progress.setTextVisible(False)
            self.progress.setRange(0, 100)
            self.layout().addWidget(self.progress)
        self.progress.setValue(round(value))
