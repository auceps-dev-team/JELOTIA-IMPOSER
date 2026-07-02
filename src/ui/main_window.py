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
        self.btn_settings.clicked.connect(lambda: self.switch_view(2, self.btn_settings))
        
    def setup_stacked_widget(self):
        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget)
        
        # Dashboard view
        from src.ui.widgets.dashboard import DashboardWidget
        self.dashboard_view = DashboardWidget()
        
        # Placeholder views for other sections
        self.jobs_view = QLabel("Jobs View (Coming soon)")
        self.jobs_view.setAlignment(Qt.AlignCenter)
        self.jobs_view.setStyleSheet("font-size: 24px; color: #a6adc8;")
        
        self.settings_view = QLabel("Settings View (Coming soon)")
        self.settings_view.setAlignment(Qt.AlignCenter)
        self.settings_view.setStyleSheet("font-size: 24px; color: #a6adc8;")
        
        self.stacked_widget.addWidget(self.dashboard_view)
        self.stacked_widget.addWidget(self.jobs_view)
        self.stacked_widget.addWidget(self.settings_view)
        
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
