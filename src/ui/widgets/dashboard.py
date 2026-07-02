from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QFrame, QPushButton, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt
import pyqtgraph as pg
import numpy as np

class StatCard(QFrame):
    def __init__(self, title, value, color="#89b4fa"):
        super().__init__()
        self.setObjectName("StatCard")
        self.setStyleSheet(f"""
            #StatCard {{
                background-color: #181825;
                border-radius: 8px;
                border: 1px solid #313244;
            }}
        """)
        self.setMinimumHeight(100)
        
        layout = QVBoxLayout(self)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #a6adc8; font-size: 14px; font-weight: bold;")
        
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
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        
        self.btn_hotfolder = QPushButton("Démarrer Hot Folder")
        self.btn_hotfolder.setCheckable(True)
        self.btn_hotfolder.setStyleSheet("""
            QPushButton {
                background-color: #a6e3a1;
                color: #11111b;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:checked {
                background-color: #f38ba8;
                color: #11111b;
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
        
        self.card_active_jobs = StatCard("Jobs Actifs", "0", color="#89b4fa")
        self.card_errors = StatCard("Erreurs (Dernier Preflight)", "0", color="#f38ba8")
        self.card_sheets = StatCard("Planches Générées", "0", color="#a6e3a1")
        self.card_fill_rate = StatCard("Taux Remplissage", "0%", color="#f9e2af")
        
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
                background-color: #181825;
                border-radius: 8px;
                border: 1px solid #313244;
            }
        """)
        self.chart_layout = QVBoxLayout(self.chart_frame)
        
        chart_title = QLabel("Production des 7 derniers jours (Planches générées)")
        chart_title.setStyleSheet("color: #a6adc8; font-size: 14px; font-weight: bold;")
        self.chart_layout.addWidget(chart_title)
        
        # pyqtgraph setup
        pg.setConfigOption('background', '#181825')
        pg.setConfigOption('foreground', '#cdd6f4')
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', 'Planches générées')
        self.plot_widget.setLabel('bottom', 'Jours (Derniers 7 j)')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Mock data for demonstration
        days = np.array([1, 2, 3, 4, 5, 6, 7])
        sheets_generated = np.array([12, 18, 14, 25, 22, 30, 42])
        
        # Bar graph item
        bar_chart = pg.BarGraphItem(x=days, height=sheets_generated, width=0.6, brush='#89b4fa')
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
