import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import ThemeManager
from src.ui.widgets.common import status_bracket_text, status_color
from src.ui.widgets.job_dialog import JobDialog

_T = ThemeManager
_COL_NUM, _COL_NAME, _COL_STATUS, _COL_FILES, _COL_SHEETS, _COL_DATE, _COL_ACTIONS = range(7)


class JobsWidget(QWidget):
    view_details_requested = Signal(str)   # emits job_name
    cancel_job_requested = Signal(str)
    resume_job_requested = Signal(str)
    job_created = Signal(str, list, dict)  # emits (job_name, file_paths:list[str], overrides:dict)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.job_uuid_map: dict[str, str] = {}  # uuid_str → job_name
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(18, 18, 18, 18)
        self.main_layout.setSpacing(14)

        self.setup_toolbar()
        self.setup_table()
        self.setup_stats_row()

    def setup_toolbar(self):
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("> RECHERCHER_JOB…")
        self.search_input.textChanged.connect(self._filter_table)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["Tous les statuts", "PENDING", "PROCESSING", "DONE", "ERROR"])
        self.status_filter.currentTextChanged.connect(self._filter_table)

        self.btn_new_job = QPushButton("[+ NOUVEAU JOB]")
        self.btn_new_job.setObjectName("primary")
        self.btn_new_job.clicked.connect(self.open_new_job_dialog)

        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.status_filter)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_new_job)
        self.main_layout.addLayout(toolbar)

    def setup_table(self):
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["NUM", "NOM.JOB", "STATUT", "FICH.", "PLANCHES", "HORODATAGE", "ACTION"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_NUM, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ACTIONS, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.main_layout.addWidget(self.table, 1)

        drop_hint = QLabel("⤓ DROP PDF ICI → CRÉATION JOB MANUEL")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint.setStyleSheet(
            f"color:{_T.TEXT_MUTE}; padding:14px; border-top:1px dashed {_T.BORDER_FIELD}; letter-spacing:1px;"
        )
        self.main_layout.addWidget(drop_hint)

    def setup_stats_row(self):
        row = QHBoxLayout()
        row.setSpacing(14)
        self.lbl_total = self._stat_chip("")
        self.lbl_files = self._stat_chip("")
        self.lbl_queue = self._stat_chip("")
        for lbl in (self.lbl_total, self.lbl_files, self.lbl_queue):
            row.addWidget(lbl)
        row.addStretch()
        self.main_layout.addLayout(row)
        self._update_stats()

    def _stat_chip(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"background-color:{_T.BG_PANEL}; border:1px solid {_T.BORDER}; "
            f"color:{_T.TEXT_MUTE}; padding:8px 14px; font-size:11px;"
        )
        return lbl

    # ------------------------------------------------------------------ #
    #  Job management                                                      #
    # ------------------------------------------------------------------ #

    def add_job(self, name: str, files_count: int, status: str = "PENDING", date_str=None) -> int:
        """Add a real job row. Returns the new row index.

        `date_str` may be omitted (defaults to now), a pre-formatted string,
        or a datetime (e.g. a persisted job's original created_at when
        reloading job history on startup)."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        if date_str is None:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        elif isinstance(date_str, datetime.datetime):
            date_str = date_str.strftime("%Y-%m-%d %H:%M")

        num_item = QTableWidgetItem(f"{row + 1:02d}")
        num_item.setForeground(QColor(_T.TEXT_MUTE))
        self.table.setItem(row, _COL_NUM, num_item)
        self.table.setItem(row, _COL_NAME, QTableWidgetItem(name))
        self._set_status_item(row, status)
        self.table.setItem(row, _COL_FILES, QTableWidgetItem(str(files_count)))
        self.table.setItem(row, _COL_SHEETS, QTableWidgetItem("0"))
        self.table.setItem(row, _COL_DATE, QTableWidgetItem(date_str))

        btn = QPushButton("DÉTAILS →")
        btn.setObjectName("details_btn")
        btn.setStyleSheet(f"border:none; color:{_T.ACCENT_TEXT}; font-weight:600;")
        btn.clicked.connect(lambda: self.view_details_requested.emit(name))
        self.table.setCellWidget(row, _COL_ACTIONS, btn)

        self._update_stats()
        return row

    def _set_status_item(self, row: int, status: str) -> None:
        item = QTableWidgetItem(status_bracket_text(status))
        item.setData(Qt.ItemDataRole.UserRole, status)
        item.setForeground(QColor(status_color(status)))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.table.setItem(row, _COL_STATUS, item)

    def update_job_status(self, job_id_str: str, status: str, sheets_count: int = None):
        job_name = self.job_uuid_map.get(job_id_str, job_id_str)
        row = self._find_row_by_name(job_name)
        if row == -1:
            return
        self._set_status_item(row, status)
        if sheets_count is not None:
            self.table.setItem(row, _COL_SHEETS, QTableWidgetItem(str(sheets_count)))
        self._update_stats()

    def _find_row_by_name(self, name: str) -> int:
        items = self.table.findItems(name, Qt.MatchFlag.MatchExactly)
        for item in items:
            if item.column() == _COL_NAME:
                return item.row()
        return -1

    def _update_stats(self) -> None:
        total = self.table.rowCount()
        files_sum = 0
        queue_count = 0
        for row in range(total):
            files_item = self.table.item(row, _COL_FILES)
            if files_item and files_item.text().isdigit():
                files_sum += int(files_item.text())
            status_item = self.table.item(row, _COL_STATUS)
            if status_item and status_item.data(Qt.ItemDataRole.UserRole) == "PENDING":
                queue_count += 1
        self.lbl_total.setText(f"TOTAL: {total} JOBS")
        self.lbl_files.setText(f"FICHIERS: {files_sum}")
        self.lbl_queue.setText(f"FILE D'ATTENTE: {queue_count}")

    # ------------------------------------------------------------------ #
    #  Job dialog                                                          #
    # ------------------------------------------------------------------ #

    def open_new_job_dialog(self, files=None):
        dialog = JobDialog(self, files)
        if not dialog.exec():
            return
        data = dialog.get_job_data()
        name = data["name"]
        file_paths = data["files"]
        self.add_job(name, len(file_paths), "PENDING")
        self.job_created.emit(name, file_paths, data["overrides"])

    # ------------------------------------------------------------------ #
    #  Drag & Drop                                                         #
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        if files:
            self.open_new_job_dialog(files=files)

    # ------------------------------------------------------------------ #
    #  Search / filter                                                     #
    # ------------------------------------------------------------------ #

    def _filter_table(self):
        search = self.search_input.text().lower()
        status_flt = self.status_filter.currentText()

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, _COL_NAME)
            status_item = self.table.item(row, _COL_STATUS)
            if name_item is None:
                continue
            name_match = search in name_item.text().lower()
            status_match = (
                status_flt == "Tous les statuts"
                or (status_item and status_item.data(Qt.ItemDataRole.UserRole) == status_flt)
            )
            self.table.setRowHidden(row, not (name_match and status_match))

    # ------------------------------------------------------------------ #
    #  Context menu                                                        #
    # ------------------------------------------------------------------ #

    def show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        job_name = self.table.item(row, _COL_NAME).text()
        status_item = self.table.item(row, _COL_STATUS)
        status = status_item.data(Qt.ItemDataRole.UserRole) if status_item else ""

        menu = QMenu(self)
        if status in ("PENDING", "PROCESSING"):
            a = menu.addAction("Annuler le Job")
            a.triggered.connect(lambda: self._cancel_job(job_name, row))
        elif status == "ERROR":
            a = menu.addAction("Reprendre le Job")
            a.triggered.connect(lambda: self._resume_job(job_name, row))
            b = menu.addAction("Voir les erreurs")
            b.triggered.connect(
                lambda: QMessageBox.information(self, "Erreurs", f"Erreurs pour {job_name}")
            )
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _cancel_job(self, job_name: str, row: int):
        self._set_status_item(row, "CANCELLED")
        self._update_stats()
        self.cancel_job_requested.emit(job_name)

    def _resume_job(self, job_name: str, row: int):
        self._set_status_item(row, "PENDING")
        self._update_stats()
        self.resume_job_requested.emit(job_name)
