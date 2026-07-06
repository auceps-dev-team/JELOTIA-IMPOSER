import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
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

from src.ui.widgets.job_dialog import JobDialog


class JobsWidget(QWidget):
    view_details_requested = Signal(str)   # emits job_name
    cancel_job_requested = Signal(str)
    resume_job_requested = Signal(str)
    job_created = Signal(str, list)        # emits (job_name, file_paths:list[str])

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.job_uuid_map: dict[str, str] = {}  # uuid_str → job_name
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        title = QLabel("Gestion des Jobs")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.main_layout.addWidget(title)

        self.setup_toolbar()
        self.setup_table()

    def setup_toolbar(self):
        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher un job...")
        self.search_input.setFixedWidth(250)
        self.search_input.textChanged.connect(self._filter_table)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["Tous les statuts", "PENDING", "PROCESSING", "DONE", "ERROR"])
        self.status_filter.currentTextChanged.connect(self._filter_table)

        self.btn_new_job = QPushButton("+ Nouveau Job")
        self.btn_new_job.setObjectName("primary")
        self.btn_new_job.clicked.connect(self.open_new_job_dialog)

        toolbar.addWidget(self.search_input)
        toolbar.addWidget(self.status_filter)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_new_job)
        self.main_layout.addLayout(toolbar)

    def setup_table(self):
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Nom du Job", "Statut", "Fichiers", "Planches", "Date", "Actions"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.main_layout.addWidget(self.table)

    # ------------------------------------------------------------------ #
    #  Job management                                                      #
    # ------------------------------------------------------------------ #

    def add_job(self, name: str, files_count: int, status: str = "PENDING") -> int:
        """Add a real job row. Returns the new row index."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self._set_status_item(row, status)
        self.table.setItem(row, 2, QTableWidgetItem(str(files_count)))
        self.table.setItem(row, 3, QTableWidgetItem("0"))
        self.table.setItem(row, 4, QTableWidgetItem(date_str))

        btn = QPushButton("Détails")
        btn.setObjectName("details_btn")
        btn.clicked.connect(lambda: self.view_details_requested.emit(name))
        self.table.setCellWidget(row, 5, btn)
        return row

    def _set_status_item(self, row: int, status: str) -> None:
        item = QTableWidgetItem(status)
        colors = {
            "DONE": Qt.GlobalColor.green,
            "PROCESSING": Qt.GlobalColor.yellow,
            "ERROR": Qt.GlobalColor.red,
            "PENDING": Qt.GlobalColor.white,
            "CANCELLED": Qt.GlobalColor.darkGray,
        }
        item.setForeground(colors.get(status, Qt.GlobalColor.white))
        self.table.setItem(row, 1, item)

    def update_job_status(self, job_id_str: str, status: str, sheets_count: int = None):
        job_name = self.job_uuid_map.get(job_id_str, job_id_str)
        row = self._find_row_by_name(job_name)
        if row == -1:
            return
        self._set_status_item(row, status)
        if sheets_count is not None:
            self.table.setItem(row, 3, QTableWidgetItem(str(sheets_count)))

    def _find_row_by_name(self, name: str) -> int:
        items = self.table.findItems(name, Qt.MatchFlag.MatchExactly)
        return items[0].row() if items else -1

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
        self.job_created.emit(name, file_paths)

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
            name_item = self.table.item(row, 0)
            status_item = self.table.item(row, 1)
            if name_item is None:
                continue
            name_match = search in name_item.text().lower()
            status_match = (
                status_flt == "Tous les statuts"
                or (status_item and status_item.text() == status_flt)
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
        job_name = self.table.item(row, 0).text()
        status_item = self.table.item(row, 1)
        status = status_item.text() if status_item else ""

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
        self.cancel_job_requested.emit(job_name)

    def _resume_job(self, job_name: str, row: int):
        self._set_status_item(row, "PENDING")
        self.resume_job_requested.emit(job_name)
