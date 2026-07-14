import importlib.metadata
import os
import platform
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import ThemeManager
from src.ui.widgets.common import LedDot

_T = ThemeManager

_PACKAGES = ("pymupdf", "pikepdf", "pyside6", "qrcode", "openpyxl", "reportlab")


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except Exception:
        return "—"


def _app_version() -> str:
    """The uv project is 'virtual' (never installed as a package), so package
    metadata doesn't exist — read pyproject.toml when running from source."""
    version = _version("jelotia-imposer")
    if version != "—":
        return version
    try:
        import re

        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.M)
        return match.group(1) if match else "—"
    except Exception:
        return "—"


class SystemInfoWidget(QWidget):
    """F7·INFO SYSTÈME — état de l'installation en un coup d'œil : version de
    l'application, environnement technique, dossiers de travail (avec témoin
    d'existence) et volumétrie de la base. Rafraîchi à chaque affichage."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._rows: dict[str, QLabel] = {}
        self._leds: dict[str, LedDot] = {}
        self.setup_ui()

    # ------------------------------------------------------------------ #

    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(14)

        # -- Application ---------------------------------------------------
        app_form = self._panel(grid, 0, 0, "APPLICATION")
        self._add_row(app_form, "app_version", "Version")
        self._add_row(app_form, "app_mode", "Mode")
        self._add_row(app_form, "app_python", "Python")
        self._add_row(app_form, "app_os", "Système")
        self._add_row(app_form, "app_cpu", "Processeurs")

        # -- Bibliothèques ---------------------------------------------------
        lib_form = self._panel(grid, 0, 1, "BIBLIOTHÈQUES")
        for package in _PACKAGES:
            self._add_row(lib_form, f"lib_{package}", package)

        # -- Dossiers de travail ---------------------------------------------
        dir_form = self._panel(grid, 1, 0, "DOSSIERS DE TRAVAIL")
        for key, label in (
            ("input_dir", "Entrée (hot folder)"),
            ("processing_dir", "Traitement"),
            ("output_dir", "Sortie"),
            ("archive_dir", "Archives"),
            ("log_dir", "Journaux"),
            ("db_path", "Base de données"),
        ):
            self._add_row(dir_form, f"dir_{key}", label, led=True)

        # -- Base de données --------------------------------------------------
        db_form = self._panel(grid, 1, 1, "BASE DE DONNÉES")
        self._add_row(db_form, "db_jobs", "Jobs")
        self._add_row(db_form, "db_archived", "…dont archivés")
        self._add_row(db_form, "db_files", "Fichiers suivis")
        self._add_row(db_form, "db_sheets", "Planches")
        self._add_row(db_form, "db_size", "Taille du fichier")

        outer.addLayout(grid, 1)

        actions = QHBoxLayout()
        self.btn_open_folder = QPushButton("[OUVRIR LE DOSSIER HOTFOLDER]")
        self.btn_open_folder.clicked.connect(self._open_base_dir)
        self.btn_refresh = QPushButton("RAFRAÎCHIR")
        self.btn_refresh.clicked.connect(self.refresh)
        actions.addWidget(self.btn_open_folder)
        actions.addStretch()
        actions.addWidget(self.btn_refresh)
        outer.addLayout(actions)

    def _panel(self, grid: QGridLayout, row: int, col: int, title: str) -> QFormLayout:
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border:1px solid {_T.BORDER}; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        head = QLabel(f"┌ {title}")
        head.setStyleSheet(
            f"color:{_T.TEXT_2}; font-weight:600; font-size:12px; "
            f"letter-spacing:1.5px; border:none;"
        )
        layout.addWidget(head)
        form = QFormLayout()
        form.setContentsMargins(0, 10, 0, 0)
        form.setSpacing(8)
        layout.addLayout(form)
        layout.addStretch()
        grid.addWidget(panel, row, col)
        return form

    def _add_row(self, form: QFormLayout, key: str, label: str, led: bool = False):
        caption = QLabel(label)
        caption.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:12px; border:none;")
        value = QLabel("—")
        value.setStyleSheet(f"color:{_T.TEXT_1}; font-size:12px; border:none;")
        value.setWordWrap(True)
        self._rows[key] = value
        if led:
            cell = QWidget()
            row_layout = QHBoxLayout(cell)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            dot = LedDot(_T.TEXT_DIM, size=7, glow=False)
            self._leds[key] = dot
            row_layout.addWidget(dot)
            row_layout.addWidget(value, 1)
            form.addRow(caption, cell)
        else:
            form.addRow(caption, value)

    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        from src.utils.config import config

        self._rows["app_version"].setText(_app_version())
        self._rows["app_mode"].setText(
            "Exécutable (build PyInstaller)" if getattr(sys, "frozen", False)
            else "Développement (source)"
        )
        self._rows["app_python"].setText(platform.python_version())
        self._rows["app_os"].setText(platform.platform())
        self._rows["app_cpu"].setText(str(os.cpu_count() or "—"))

        for package in _PACKAGES:
            self._rows[f"lib_{package}"].setText(_version(package))

        for key in ("input_dir", "processing_dir", "output_dir", "archive_dir",
                    "log_dir", "db_path"):
            path = Path(getattr(config, key))
            self._rows[f"dir_{key}"].setText(str(path))
            exists = path.exists()
            self._leds[f"dir_{key}"].set_color(
                _T.STATE_OK if exists else _T.STATE_ERR, glow=False
            )

        try:
            counts = self.db.get_system_counts()
        except Exception:
            counts = {"jobs": 0, "jobs_archived": 0, "files": 0, "sheets": 0}
        self._rows["db_jobs"].setText(str(counts["jobs"]))
        self._rows["db_archived"].setText(str(counts["jobs_archived"]))
        self._rows["db_files"].setText(str(counts["files"]))
        self._rows["db_sheets"].setText(str(counts["sheets"]))
        db_path = Path(config.db_path)
        size = db_path.stat().st_size / 1024 if db_path.exists() else 0
        self._rows["db_size"].setText(f"{size:,.0f} Ko".replace(",", " "))

    def _open_base_dir(self):
        from src.utils.config import config

        try:
            os.startfile(str(config.base_dir))  # noqa: S606 - local folder open
        except OSError:
            pass
