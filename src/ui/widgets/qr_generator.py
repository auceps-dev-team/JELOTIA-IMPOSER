from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.engines.qr_engine import QREngine, QRGenerationError, is_valid_url, safe_filename
from src.core.models.domain import QRCodeSettings, QRErrorCorrection
from src.ui.theme import ThemeManager

_T = ThemeManager
_PREVIEW_PX = 360


class QRGeneratorWidget(QWidget):
    """F5·QR — single QR generation with a live preview and PNG/SVG/PDF export.
    Batch/Excel import and the imposition hand-off are separate increments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = QREngine()
        self.fill_color = "#141517"  # near-black, matches the Workbench ink
        self.back_color = "#FFFFFF"
        self.logo_path: Optional[Path] = None
        self.setup_ui()
        self._update_preview()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_form_panel())
        root.addWidget(self._build_preview_panel(), 1)

    def _build_form_panel(self) -> QFrame:
        panel = QFrame()
        panel.setFixedWidth(380)
        panel.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border-right:1px solid {_T.BORDER}; }}"
        )
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(18)

        # --- Contenu -------------------------------------------------- #
        outer.addWidget(self._section_title("CONTENU"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://jelotia.com/...")
        self.url_input.textChanged.connect(self._update_preview)
        outer.addWidget(self.url_input)

        # --- Style ---------------------------------------------------- #
        outer.addWidget(self._section_title("STYLE"))
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.ecc_combo = self._make_combo(["L (7%)", "M (15%)", "Q (25%)", "H (30%)"], 1)
        self.ecc_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Correction :", self.ecc_combo)

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(5.0, 1000.0)
        self.size_spin.setValue(30.0)
        self.size_spin.setSuffix(" mm")
        self.size_spin.valueChanged.connect(self._update_preview)
        form.addRow("Taille :", self.size_spin)

        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 20)
        self.border_spin.setValue(4)
        self.border_spin.setSuffix(" mod.")
        self.border_spin.valueChanged.connect(self._update_preview)
        form.addRow("Marge :", self.border_spin)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setSuffix(" dpi")
        form.addRow("Résolution :", self.dpi_spin)

        self.btn_fill = self._make_color_button(self.fill_color, self._pick_fill)
        form.addRow("Couleur :", self.btn_fill)
        self.btn_back = self._make_color_button(self.back_color, self._pick_back)
        form.addRow("Fond :", self.btn_back)
        outer.addLayout(form)

        # --- Logo ----------------------------------------------------- #
        outer.addWidget(self._section_title("LOGO"))
        logo_row = QHBoxLayout()
        self.btn_logo = QPushButton("Choisir…")
        self.btn_logo.clicked.connect(self._pick_logo)
        self.btn_logo_clear = QPushButton("Retirer")
        self.btn_logo_clear.clicked.connect(self._clear_logo)
        self.btn_logo_clear.setEnabled(False)
        logo_row.addWidget(self.btn_logo)
        logo_row.addWidget(self.btn_logo_clear)
        outer.addLayout(logo_row)
        self.logo_label = QLabel("Aucun logo")
        self.logo_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:11px; border:none;")
        outer.addWidget(self.logo_label)

        outer.addStretch()
        return panel

    def _build_preview_panel(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Preview surface
        surface = QFrame()
        surface.setStyleSheet(f"QFrame {{ background-color:{_T.BG_APP}; border:none; }}")
        surf_layout = QVBoxLayout(surface)
        surf_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(_PREVIEW_PX, _PREVIEW_PX)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(f"background-color:white; border:1px solid {_T.BORDER};")
        surf_layout.addWidget(self.preview_label)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(
            f"color:{_T.TEXT_MUTE}; font-size:11px; border:none; margin-top:12px;"
        )
        surf_layout.addWidget(self.status_label)

        layout.addWidget(surface, 1)

        # Export toolbar
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border-top:1px solid {_T.BORDER}; }}"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 12, 16, 12)
        bar_layout.setSpacing(10)
        bar_layout.addStretch()
        self.btn_png = QPushButton("[EXPORT PNG]")
        self.btn_svg = QPushButton("[EXPORT SVG]")
        self.btn_pdf = QPushButton("[EXPORT PDF]")
        self.btn_pdf.setObjectName("primary")
        self.btn_png.clicked.connect(lambda: self._export("PNG"))
        self.btn_svg.clicked.connect(lambda: self._export("SVG"))
        self.btn_pdf.clicked.connect(lambda: self._export("PDF"))
        for b in (self.btn_png, self.btn_svg, self.btn_pdf):
            bar_layout.addWidget(b)
        layout.addWidget(bar)
        return wrapper

    # ------------------------------------------------------------------ #
    #  Small widget builders                                               #
    # ------------------------------------------------------------------ #

    def _section_title(self, name: str) -> QLabel:
        lbl = QLabel(f"┌─[ {name} ]──")
        lbl.setStyleSheet(
            f"color:{_T.ACCENT_TEXT}; font-weight:600; font-size:12px; "
            f"letter-spacing:2px; border:none;"
        )
        return lbl

    def _make_combo(self, items, default_index):
        from PySide6.QtWidgets import QComboBox

        combo = QComboBox()
        combo.addItems(items)
        combo.setCurrentIndex(default_index)
        return combo

    def _make_color_button(self, color_hex: str, handler) -> QPushButton:
        btn = QPushButton(color_hex.upper())
        btn.clicked.connect(handler)
        self._style_color_button(btn, color_hex)
        return btn

    def _style_color_button(self, btn: QPushButton, color_hex: str) -> None:
        # Readable label whichever swatch it sits on.
        text_color = "#000000" if QColor(color_hex).lightnessF() > 0.5 else "#FFFFFF"
        btn.setText(color_hex.upper())
        btn.setStyleSheet(
            f"background-color:{color_hex}; color:{text_color}; "
            f"border:1px solid {_T.BORDER_FIELD}; padding:6px 10px;"
        )

    # ------------------------------------------------------------------ #
    #  Settings from controls                                              #
    # ------------------------------------------------------------------ #

    def _current_settings(self) -> QRCodeSettings:
        ecc = [
            QRErrorCorrection.L, QRErrorCorrection.M,
            QRErrorCorrection.Q, QRErrorCorrection.H,
        ][self.ecc_combo.currentIndex()]
        return QRCodeSettings(
            ecc=ecc,
            border=self.border_spin.value(),
            fill_color=self.fill_color,
            back_color=self.back_color,
            size_mm=self.size_spin.value(),
            dpi=self.dpi_spin.value(),
            logo_path=self.logo_path,
        )

    # ------------------------------------------------------------------ #
    #  Live preview                                                        #
    # ------------------------------------------------------------------ #

    def _update_preview(self):
        data = self.url_input.text().strip()
        if not data:
            self.preview_label.clear()
            self.preview_label.setText("Saisissez un lien\npour générer l'aperçu")
            self.preview_label.setStyleSheet(
                f"background-color:white; color:{_T.TEXT_DIM}; border:1px solid {_T.BORDER};"
            )
            self.status_label.setText("")
            self._set_exports_enabled(False)
            return

        settings = self._current_settings()
        try:
            img = self.engine.generate_image(data, settings)
        except QRGenerationError as e:
            self.status_label.setText(str(e))
            self._set_exports_enabled(False)
            return

        img = img.convert("RGB")
        preview = img.resize((_PREVIEW_PX, _PREVIEW_PX), Image_NEAREST())
        qimg = QImage(
            preview.tobytes("raw", "RGB"), preview.width, preview.height,
            preview.width * 3, QImage.Format.Format_RGB888,
        ).copy()
        self.preview_label.setStyleSheet(f"background-color:white; border:1px solid {_T.BORDER};")
        self.preview_label.setPixmap(QPixmap.fromImage(qimg))

        valid = is_valid_url(data)
        hint = "" if valid else "  ⚠ lien non standard (ni http ni https)"
        modules = max(1, img.width // max(1, settings.box_size))
        self.status_label.setText(
            f"{modules}×{modules} modules · {settings.size_mm:.0f} mm @ {settings.dpi} dpi{hint}"
        )
        self.status_label.setStyleSheet(
            f"color:{_T.STATE_WARN if not valid else _T.TEXT_MUTE}; font-size:11px; "
            f"border:none; margin-top:12px;"
        )
        self._set_exports_enabled(True)

    def _set_exports_enabled(self, enabled: bool):
        for b in (self.btn_png, self.btn_svg, self.btn_pdf):
            b.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    #  Color / logo pickers                                                #
    # ------------------------------------------------------------------ #

    def _pick_fill(self):
        color = QColorDialog.getColor(QColor(self.fill_color), self, "Couleur des modules")
        if color.isValid():
            self.fill_color = color.name()
            self._style_color_button(self.btn_fill, self.fill_color)
            self._update_preview()

    def _pick_back(self):
        color = QColorDialog.getColor(QColor(self.back_color), self, "Couleur de fond")
        if color.isValid():
            self.back_color = color.name()
            self._style_color_button(self.btn_back, self.back_color)
            self._update_preview()

    def _pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un logo", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.logo_path = Path(path)
            self.logo_label.setText(self.logo_path.name)
            self.btn_logo_clear.setEnabled(True)
            self._update_preview()

    def _clear_logo(self):
        self.logo_path = None
        self.logo_label.setText("Aucun logo")
        self.btn_logo_clear.setEnabled(False)
        self._update_preview()

    # ------------------------------------------------------------------ #
    #  Export                                                              #
    # ------------------------------------------------------------------ #

    _FILTERS = {
        "PNG": ("PNG (*.png)", ".png"),
        "SVG": ("SVG (*.svg)", ".svg"),
        "PDF": ("PDF (*.pdf)", ".pdf"),
    }

    def _export(self, fmt: str):
        data = self.url_input.text().strip()
        if not data:
            return
        file_filter, ext = self._FILTERS[fmt]
        suggested = (safe_filename(data.split("//")[-1].replace("/", "_")) or "qrcode")[:60]
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exporter en {fmt}", f"{suggested}{ext}", file_filter
        )
        if not path:
            return
        if Path(path).suffix.lower() != ext:
            path = str(Path(path).with_suffix(ext))

        settings = self._current_settings()
        try:
            renderer = {
                "PNG": self.engine.render_png,
                "SVG": self.engine.render_svg,
                "PDF": self.engine.render_pdf,
            }[fmt]
            renderer(data, settings, Path(path))
        except QRGenerationError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            return
        except Exception as e:  # pragma: no cover - unexpected I/O
            QMessageBox.warning(self, "Erreur", f"Échec de l'export : {e}")
            return
        QMessageBox.information(self, "Succès", f"QR code exporté :\n{path}")


def Image_NEAREST():
    """Lazy import of PIL's NEAREST resample enum, kept out of module import
    time so the widget module doesn't hard-depend on Pillow being importable
    just to be referenced."""
    from PIL import Image

    return Image.NEAREST
