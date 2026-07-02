import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QFrame, QPushButton, QStackedWidget, QLabel, 
    QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from pathlib import Path
from src.ui.widgets.job_queue import JobsWidget
from src.ui.widgets.settings_view import SettingsWidget
from src.core.system_notifier import SystemNotifier
from src.core.output_manager import OutputManager

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
        
        # Load system services
        self.notifier = SystemNotifier(self)
        self.output_manager = OutputManager()
        
        # Setup UI
        self.setup_status_bar()
        self.setup_system_tray()
        self.setup_hot_folder_monitor()
        self.recover_orphan_jobs()
        
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
        from src.core.auto_processor import AutoProcessor
        from pathlib import Path
        
        config = ConfigManager()
        input_path = config.get("paths", "input")
        
        if not input_path:
            # Fallback default
            input_path = str(Path.home() / "Jelotia" / "HotFolder" / "Input")
            
        processing_path = str(Path(input_path).parent / "Processing")
        
        # Start Auto Processor
        self.auto_processor = AutoProcessor(self)
        self.auto_processor.job_grouped.connect(self.handle_grouped_job)
        self.auto_processor.start()
        
        # Start Hot Folder Monitor
        self.hf_monitor = HotFolderMonitor(input_path, processing_path)
        self.hf_monitor.signals.new_job_ready.connect(self.handle_new_hot_folder_file)
        self.hf_monitor.start()
        
    def handle_new_hot_folder_file(self, file_path):
        # Pass raw file to the auto processor for intelligent grouping
        self.auto_processor.add_file(file_path)
        
    def handle_grouped_job(self, group_name, files):
        # A job has been grouped and is ready
        self.jobs_view.add_job(group_name, files[0], "Prêt", "0%")
        self.status_bar.showMessage(f"Nouveau job groupé prêt : {group_name} ({len(files)} fichiers)")
        self.notifier.notify("Nouveau Job", f"Le job {group_name} est prêt.", False)

    def recover_orphan_jobs(self):
        """Scans the /Processing folder at startup for files that were left behind during a crash"""
        from pathlib import Path
        processing_dir = Path(self.output_manager.processing_dir)
        if processing_dir.exists():
            for p in processing_dir.iterdir():
                if p.is_file() and p.suffix.lower() == ".pdf":
                    self.auto_processor.add_file(str(p))
                    
    def simulate_job_completion(self, job_name, files):
        """Simulate a job finishing successfully"""
        archive_path = self.output_manager.archive_files(job_name, files)
        if archive_path:
            self.notifier.notify("Job Terminé", f"Le job {job_name} a été archivé.", False)
            self.status_bar.showMessage(f"Job archivé : {job_name}")

    def closeEvent(self, event):
        if hasattr(self, 'hf_monitor'):
            self.hf_monitor.stop()
        if hasattr(self, 'auto_processor'):
            self.auto_processor.stop()
        super().closeEvent(event)
