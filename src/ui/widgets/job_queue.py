from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from src.ui.widgets.job_dialog import JobDialog

class JobsWidget(QWidget):
    view_details_requested = Signal(str) # Emits job name
    cancel_job_requested = Signal(str)
    resume_job_requested = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True) # Enable Drag & Drop
        self.job_uuid_map = {} # uuid_str -> group_name
        self.setup_ui()
        
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        # Header / Title
        title = QLabel("Gestion des Jobs")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.main_layout.addWidget(title)
        
        # Toolbar (Search, Filter, New Job)
        self.setup_toolbar()
        
        # Table
        self.setup_table()
        
    def setup_toolbar(self):
        self.toolbar_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher un job...")
        self.search_input.setFixedWidth(250)
        self.search_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D97A27;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Tous les statuts", "PENDING", "PROCESSING", "DONE", "ERROR"])
        self.status_filter.setStyleSheet("""
            QComboBox {
                border: 1px solid #D97A27;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        
        self.btn_new_job = QPushButton("+ Nouveau Job")
        self.btn_new_job.setStyleSheet("""
            QPushButton {
                background-color: #D97A27;
                color: #FFFFFF;
                font-weight: bold;
                padding: 8px 15px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #A05A1C;
            }
        """)
        self.btn_new_job.clicked.connect(self.open_new_job_dialog)
        
        self.toolbar_layout.addWidget(self.search_input)
        self.toolbar_layout.addWidget(self.status_filter)
        self.toolbar_layout.addStretch()
        self.toolbar_layout.addWidget(self.btn_new_job)
        
        self.main_layout.addLayout(self.toolbar_layout)
        
    def setup_table(self):
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Nom du Job", "Statut", "Fichiers", "Planches", "Date", "Actions"])
        
        # Table Styling
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #D97A27;
            }
            QHeaderView::section {
                font-weight: bold;
                border: none;
                border-bottom: 2px solid #D97A27;
                padding: 5px;
            }
        """)
        
        # Stretch columns
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        self.main_layout.addWidget(self.table)
        
        # Add some mock data
        self.add_mock_job("JOB-1A2B3C", "DONE", 12, 3, "2026-07-02 10:15")
        self.add_mock_job("JOB-XYZ789", "PROCESSING", 45, 0, "2026-07-02 11:30")
        
    def add_mock_job(self, name, status, files, sheets, date):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        self.table.setItem(row, 0, QTableWidgetItem(name))
        
        # Colored status
        status_item = QTableWidgetItem(status)
        if status == "DONE":
            status_item.setForeground(Qt.green)
        elif status == "PROCESSING":
            status_item.setForeground(Qt.yellow)
        elif status == "ERROR":
            status_item.setForeground(Qt.red)
            
        self.table.setItem(row, 1, status_item)
        self.table.setItem(row, 2, QTableWidgetItem(str(files)))
        self.table.setItem(row, 3, QTableWidgetItem(str(sheets)))
        self.table.setItem(row, 4, QTableWidgetItem(date))
        
        # Action button placeholder
        btn_action = QPushButton("Détails")
        btn_action.setStyleSheet("padding: 4px; border-radius: 2px;")
        btn_action.clicked.connect(lambda: self.view_details_requested.emit(name))
        self.table.setCellWidget(row, 5, btn_action)
        
    def add_job(self, name, file_path, status, progress="0%"):
        # For simplicity, we just use add_mock_job to inject it into the table.
        # Ideally we'd store the file_path in a hidden column or data model.
        import datetime
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.add_mock_job(name, status, 1, 0, date_str)
        
    def _find_row_by_name(self, job_name):
        items = self.table.findItems(job_name, Qt.MatchExactly)
        if items:
            return items[0].row()
        return -1

    def update_job_status(self, job_id_str, status, sheets_count=None):
        job_name = self.job_uuid_map.get(job_id_str, job_id_str)
        row = self._find_row_by_name(job_name)
        if row != -1:
            status_item = self.table.item(row, 1)
            status_item.setText(status)
            if status == "DONE":
                status_item.setForeground(Qt.green)
            elif status == "PROCESSING":
                status_item.setForeground(Qt.yellow)
            elif status == "ERROR":
                status_item.setForeground(Qt.red)
                
            if sheets_count is not None:
                self.table.item(row, 3).setText(str(sheets_count))
        
    def open_new_job_dialog(self, files=None):
        dialog = JobDialog(self, files)
        if dialog.exec():
            data = dialog.get_job_data()
            self.add_mock_job(data["name"], "PENDING", len(data.get("files", [])), 0, "Maintenant")
            
    # Drag and Drop Methods
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event: QDropEvent):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        if files:
            self.open_new_job_dialog(files=files)

    def show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.table.itemAt(pos)
        if not item:
            return
            
        row = item.row()
        job_name = self.table.item(row, 0).text()
        status = self.table.item(row, 1).text()
        
        menu = QMenu(self)
        
        if status in ["PENDING", "PROCESSING"]:
            action_cancel = menu.addAction("Annuler le Job")
            action_cancel.triggered.connect(lambda: self.cancel_job(job_name, row))
        elif status == "ERROR":
            action_resume = menu.addAction("Reprendre le Job")
            action_resume.triggered.connect(lambda: self.resume_job(job_name, row))
            action_errors = menu.addAction("Voir les erreurs")
            action_errors.triggered.connect(lambda: QMessageBox.information(self, "Erreurs", f"Erreurs pour {job_name}"))
            
        menu.exec_(self.table.viewport().mapToGlobal(pos))
        
    def cancel_job(self, job_name, row):
        status_item = self.table.item(row, 1)
        status_item.setText("CANCELLED")
        status_item.setForeground(Qt.darkGray)
        self.cancel_job_requested.emit(job_name)
        
    def resume_job(self, job_name, row):
        status_item = self.table.item(row, 1)
        status_item.setText("PENDING")
        status_item.setForeground(Qt.white)
        self.resume_job_requested.emit(job_name)
