from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

class ThemeManager:
    # JELOTIA Brand Colors
    COLOR_ORANGE = "#D97A27"
    COLOR_BLACK = "#0C0C0C"
    COLOR_GREY = "#F1F3F7"
    COLOR_WHITE = "#FFFFFF"
    
    @staticmethod
    def apply_dark_theme(app: QApplication):
        app.setStyle("Fusion")
        
        palette = QPalette()
        # Backgrounds
        palette.setColor(QPalette.Window, QColor(ThemeManager.COLOR_BLACK))
        palette.setColor(QPalette.WindowText, QColor(ThemeManager.COLOR_GREY))
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(ThemeManager.COLOR_BLACK))
        palette.setColor(QPalette.ToolTipBase, QColor(ThemeManager.COLOR_BLACK))
        palette.setColor(QPalette.ToolTipText, QColor(ThemeManager.COLOR_GREY))
        
        # Text
        palette.setColor(QPalette.Text, QColor(ThemeManager.COLOR_GREY))
        palette.setColor(QPalette.Button, QColor(40, 40, 40))
        palette.setColor(QPalette.ButtonText, QColor(ThemeManager.COLOR_GREY))
        palette.setColor(QPalette.BrightText, QColor(Qt.red))
        palette.setColor(QPalette.Link, QColor(ThemeManager.COLOR_ORANGE))
        
        # Highlights
        palette.setColor(QPalette.Highlight, QColor(ThemeManager.COLOR_ORANGE))
        palette.setColor(QPalette.HighlightedText, QColor(ThemeManager.COLOR_BLACK))
        
        app.setPalette(palette)
        
        # Global QSS for specific tweaks
        app.setStyleSheet(f"""
            QFrame#sidebar {{
                background-color: #1a1a1a;
                border-right: 1px solid #333333;
            }}
            QPushButton {{
                background-color: #282828;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 5px;
                color: {ThemeManager.COLOR_GREY};
            }}
            QPushButton:hover {{
                background-color: #383838;
                border: 1px solid {ThemeManager.COLOR_ORANGE};
            }}
            QPushButton:checked {{
                background-color: {ThemeManager.COLOR_ORANGE};
                color: {ThemeManager.COLOR_BLACK};
                font-weight: bold;
            }}
            QProgressBar {{
                border: 1px solid #333333;
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {ThemeManager.COLOR_ORANGE};
                width: 10px;
            }}
        """)

    @staticmethod
    def apply_light_theme(app: QApplication):
        app.setStyle("Fusion")
        
        palette = QPalette()
        # Backgrounds
        palette.setColor(QPalette.Window, QColor(ThemeManager.COLOR_GREY))
        palette.setColor(QPalette.WindowText, QColor(ThemeManager.COLOR_BLACK))
        palette.setColor(QPalette.Base, QColor(ThemeManager.COLOR_WHITE))
        palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
        palette.setColor(QPalette.ToolTipBase, QColor(ThemeManager.COLOR_WHITE))
        palette.setColor(QPalette.ToolTipText, QColor(ThemeManager.COLOR_BLACK))
        
        # Text
        palette.setColor(QPalette.Text, QColor(ThemeManager.COLOR_BLACK))
        palette.setColor(QPalette.Button, QColor(230, 230, 230))
        palette.setColor(QPalette.ButtonText, QColor(ThemeManager.COLOR_BLACK))
        palette.setColor(QPalette.BrightText, QColor(Qt.red))
        palette.setColor(QPalette.Link, QColor(ThemeManager.COLOR_ORANGE))
        
        # Highlights
        palette.setColor(QPalette.Highlight, QColor(ThemeManager.COLOR_ORANGE))
        palette.setColor(QPalette.HighlightedText, QColor(ThemeManager.COLOR_WHITE))
        
        app.setPalette(palette)
        
        # Global QSS
        app.setStyleSheet(f"""
            QFrame#sidebar {{
                background-color: #e5e7eb;
                border-right: 1px solid #d1d5db;
            }}
            QPushButton {{
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 5px;
                color: {ThemeManager.COLOR_BLACK};
            }}
            QPushButton:hover {{
                background-color: #f3f4f6;
                border: 1px solid {ThemeManager.COLOR_ORANGE};
            }}
            QPushButton:checked {{
                background-color: {ThemeManager.COLOR_ORANGE};
                color: {ThemeManager.COLOR_WHITE};
                font-weight: bold;
            }}
            QProgressBar {{
                border: 1px solid #d1d5db;
                border-radius: 4px;
                text-align: center;
                color: {ThemeManager.COLOR_BLACK};
            }}
            QProgressBar::chunk {{
                background-color: {ThemeManager.COLOR_ORANGE};
                width: 10px;
            }}
        """)
