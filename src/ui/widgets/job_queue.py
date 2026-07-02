from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QFrame, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from src.ui.widgets.job_dialog import JobDialog

class JobsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True) # Enable Drag & Drop
        self.setup_ui()
        
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        # Header / Title
        title = QLabel("Gestion des Jobs")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
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
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Tous les statuts", "PENDING", "PROCESSING", "DONE", "ERROR"])
        self.status_filter.setStyleSheet("""
            QComboBox {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        
        self.btn_new_job = QPushButton("+ Nouveau Job")
        self.btn_new_job.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                font-weight: bold;
                padding: 8px 15px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #b4befe;
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
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                gridline-color: #313244;
                selection-background-color: #313244;
            }
            QHeaderView::section {
                background-color: #11111b;
                color: #a6adc8;
                font-weight: bold;
                border: none;
                border-bottom: 2px solid #313244;
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
        btn_action.setStyleSheet("background-color: #313244; padding: 4px; border-radius: 2px;")
        self.table.setCellWidget(row, 5, btn_action)
        
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
