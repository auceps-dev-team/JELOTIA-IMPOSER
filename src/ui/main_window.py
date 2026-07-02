import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QFrame, QPushButton, QStackedWidget, QLabel, 
    QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JELOTIA IMPOSER")
        self.resize(1200, 800)
        
        # Central widget and main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.setup_sidebar()
        self.setup_stacked_widget()
        self.setup_status_bar()
        self.setup_system_tray()
        self.setup_hot_folder_monitor()
        
    def setup_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(250)
        
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 20, 0, 0)
        self.sidebar_layout.setSpacing(5)
        
        # Application Title / Logo Placeholder
        title_label = QLabel("JELOTIA IMPOSER")
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; padding: 10px 20px;")
        self.sidebar_layout.addWidget(title_label)
        self.sidebar_layout.addSpacing(20)
        
        # Navigation Buttons
        self.btn_dashboard = QPushButton("Dashboard")
        self.btn_dashboard.setCheckable(True)
        self.btn_dashboard.setChecked(True)
        
        self.btn_jobs = QPushButton("Jobs & Files")
        self.btn_jobs.setCheckable(True)
        
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setCheckable(True)
        
        self.sidebar_layout.addWidget(self.btn_dashboard)
        self.sidebar_layout.addWidget(self.btn_jobs)
        self.sidebar_layout.addWidget(self.btn_settings)
        self.sidebar_layout.addStretch()
        
        self.main_layout.addWidget(self.sidebar)
        
        # Connect buttons to stacked widget change
        self.btn_dashboard.clicked.connect(lambda: self.switch_view(0, self.btn_dashboard))
        self.btn_jobs.clicked.connect(lambda: self.switch_view(1, self.btn_jobs))
        self.btn_settings.clicked.connect(lambda: self.switch_view(3, self.btn_settings))
        
    def setup_stacked_widget(self):
        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget)
        
        # Dashboard view
        from src.ui.widgets.dashboard import DashboardWidget
        self.dashboard_view = DashboardWidget()
        
        # Jobs view
        from src.ui.widgets.job_queue import JobsWidget
        self.jobs_view = JobsWidget()
        
        # Sheet Preview view
        from src.ui.widgets.sheet_preview import SheetPreviewWidget
        self.preview_view = SheetPreviewWidget()
        
        # Settings view
        from src.ui.widgets.settings_view import SettingsWidget
        self.settings_view = SettingsWidget()
        
        self.stacked_widget.addWidget(self.dashboard_view)
        self.stacked_widget.addWidget(self.jobs_view)
        self.stacked_widget.addWidget(self.preview_view)
        self.stacked_widget.addWidget(self.settings_view)
        
        # Connections
        self.jobs_view.view_details_requested.connect(self.show_preview)
        
    def show_preview(self, job_name):
        # We switch to preview view.
        # Ideally, we pass the real generated PDF path. For now we pass a dummy path or nothing.
        # We can add a back button to the preview in a real scenario, but for now we'll just switch the view.
        self.stacked_widget.setCurrentWidget(self.preview_view)
        # Assuming we have a test PDF to show if it exists
        test_pdf = Path("test_planche.pdf")
        if test_pdf.exists():
            self.preview_view.load_pdf(str(test_pdf), fill_rate=85.4)
        else:
            self.preview_view.info_label.setText(f"Aperçu pour le job {job_name} - PDF non trouvé")
        
    def switch_view(self, index, button):
        self.stacked_widget.setCurrentIndex(index)
        
        # Reset check states
        self.btn_dashboard.setChecked(False)
        self.btn_jobs.setChecked(False)
        self.btn_settings.setChecked(False)
        
        # Check active button
        button.setChecked(True)
        
    def setup_status_bar(self):
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready | 0 Active Jobs | Mem: 0 MB")
        
    def setup_system_tray(self):
        # We need to make sure system tray is supported
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            
            # Use a default icon or null icon since we don't have an asset yet
            # It will show up as a blank space or a default icon depending on OS
            icon = QIcon() 
            self.tray_icon.setIcon(icon)
            
            self.tray_menu = QMenu()
            
            show_action = self.tray_menu.addAction("Show")
            show_action.triggered.connect(self.showNormal)
            
            quit_action = self.tray_menu.addAction("Quit")
            quit_action.triggered.connect(sys.exit)
            
            self.tray_icon.setContextMenu(self.tray_menu)
            self.tray_icon.show()
            self.tray_icon.setToolTip("JELOTIA IMPOSER")
            
            self.tray_icon.activated.connect(self.tray_activated)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.showNormal()

    def setup_hot_folder_monitor(self):
        from src.utils.config_manager import ConfigManager
        from src.core.hot_folder_monitor import HotFolderMonitor
        from pathlib import Path
        
        config = ConfigManager()
        input_path = config.get("paths", "input")
        
        if not input_path:
            # Fallback default
            input_path = str(Path.home() / "Jelotia" / "HotFolder" / "Input")
            
        processing_path = str(Path(input_path).parent / "Processing")
        
        self.hf_monitor = HotFolderMonitor(input_path, processing_path)
        self.hf_monitor.signals.new_job_ready.connect(self.handle_new_hot_folder_job)
        self.hf_monitor.start()
        
    def handle_new_hot_folder_job(self, file_path):
        from pathlib import Path
        p = Path(file_path)
        job_name = p.stem
        
        # Add to job list directly
        self.jobs_view.add_job(job_name, file_path, "Nouveau", "0%")
        self.status_bar.showMessage(f"Nouveau job détecté : {job_name}")

    def closeEvent(self, event):
        if hasattr(self, 'hf_monitor'):
            self.hf_monitor.stop()
        super().closeEvent(event)
