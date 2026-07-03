from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QFrame, QPushButton, QGridLayout, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt
import pyqtgraph as pg
import numpy as np

class StatCard(QFrame):
    def __init__(self, title, value, color="#89b4fa"):
        super().__init__()
        self.setObjectName("StatCard")
        self.setStyleSheet("""
            #StatCard {
                border-radius: 8px;
                border: 1px solid #D97A27;
            }
        """)
        self.setMinimumHeight(100)
        
        layout = QVBoxLayout(self)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: bold;")
        self.value_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.setAlignment(self.title_label, Qt.AlignTop)

class DashboardWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)
        
        # Header
        self.header_layout = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        
        self.btn_hotfolder = QPushButton("Démarrer Hot Folder")
        self.btn_hotfolder.setCheckable(True)
        self.btn_hotfolder.setStyleSheet("""
            QPushButton {
                background-color: #D97A27;
                color: #FFFFFF;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:checked {
                background-color: #A05A1C;
                color: #FFFFFF;
            }
        """)
        self.btn_hotfolder.toggled.connect(self.toggle_hotfolder)
        
        self.header_layout.addWidget(title)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.btn_hotfolder)
        
        self.main_layout.addLayout(self.header_layout)
        
        # Stat Cards
        self.cards_layout = QHBoxLayout()
        self.cards_layout.setSpacing(15)
        
        self.card_active_jobs = StatCard("Jobs Actifs", "0", color="#D97A27")
        self.card_errors = StatCard("Erreurs (Dernier Preflight)", "0", color="#D97A27")
        self.card_sheets = StatCard("Planches Générées", "0", color="#D97A27")
        self.card_fill_rate = StatCard("Taux Remplissage", "0%", color="#D97A27")
        
        self.cards_layout.addWidget(self.card_active_jobs)
        self.cards_layout.addWidget(self.card_errors)
        self.cards_layout.addWidget(self.card_sheets)
        self.cards_layout.addWidget(self.card_fill_rate)
        
        self.main_layout.addLayout(self.cards_layout)
        
        # Chart
        self.setup_chart()
        
    def setup_chart(self):
        # Container frame for the chart
        self.chart_frame = QFrame()
        self.chart_frame.setStyleSheet("""
            QFrame {
                border-radius: 8px;
                border: 1px solid #D97A27;
            }
        """)
        self.chart_layout = QVBoxLayout(self.chart_frame)
        
        chart_title = QLabel("Production des 7 derniers jours (Planches générées)")
        chart_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.chart_layout.addWidget(chart_title)
        
        # pyqtgraph setup
        # Make pyqtgraph use transparent background
        pg.setConfigOption('background', 'w' if QApplication.style().objectName() == 'fusion' else 'k') # We will adapt this
        pg.setConfigOption('foreground', 'k' if QApplication.style().objectName() == 'fusion' else 'w')
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', 'Planches générées')
        self.plot_widget.setLabel('bottom', 'Jours (Derniers 7 j)')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Mock data for demonstration
        days = np.array([1, 2, 3, 4, 5, 6, 7])
        sheets_generated = np.array([12, 18, 14, 25, 22, 30, 42])
        
        # Bar graph item
        bar_chart = pg.BarGraphItem(x=days, height=sheets_generated, width=0.6, brush='#D97A27')
        self.plot_widget.addItem(bar_chart)
        
        self.chart_layout.addWidget(self.plot_widget)
        self.main_layout.addWidget(self.chart_frame)
        self.main_layout.setStretch(2, 1) # Make the chart take remaining space
        
    def toggle_hotfolder(self, checked):
        if checked:
            self.btn_hotfolder.setText("Arrêter Hot Folder")
            # Logic to start Hot Folder watchdog will go here
        else:
            self.btn_hotfolder.setText("Démarrer Hot Folder")
            # Logic to stop Hot Folder watchdog will go here
