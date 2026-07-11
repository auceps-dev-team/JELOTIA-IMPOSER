from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


class ThemeManager:
    # JELOTIA Brand Colors (legacy — used by apply_light_theme only)
    COLOR_ORANGE = "#D97A27"
    COLOR_BLACK = "#0C0C0C"
    COLOR_GREY = "#F1F3F7"
    COLOR_WHITE = "#FFFFFF"

    # "Workbench" design system tokens (dark theme — see 1c Workbench/Design System.dc.html)
    BG_APP = "#141517"
    BG_PANEL = "#1B1D20"
    BG_ACTIVE = "#26282C"
    BG_HEADER = "#202226"
    BORDER = "#33363B"
    BORDER_FIELD = "#3C4046"
    TEXT_1 = "#E8EAED"
    TEXT_2 = "#C8CBD0"
    TEXT_MUTE = "#8B8F96"
    TEXT_DIM = "#565A61"
    ACCENT = "#FF7A1A"
    ACCENT_TEXT = "#FF9A4D"
    ACCENT_HOVER = "#FFB35C"
    STATE_OK = "#4DD97E"
    STATE_WARN = "#FFB35C"
    STATE_ERR = "#E5484D"

    # Monospace stack: no IBM Plex Mono font file is bundled, so we fall back
    # to whichever system monospace font is actually installed.
    MONO_FONT_FAMILIES = ["Cascadia Mono", "Consolas", "Courier New", "monospace"]

    @staticmethod
    def apply_dark_theme(app: QApplication):
        app.setStyle("Fusion")
        T = ThemeManager

        font = QFont(T.MONO_FONT_FAMILIES[0])
        font.setFamilies(T.MONO_FONT_FAMILIES)
        font.setStyleHint(QFont.StyleHint.Monospace)
        app.setFont(font)

        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(T.BG_APP))
        palette.setColor(QPalette.WindowText, QColor(T.TEXT_1))
        palette.setColor(QPalette.Base, QColor(T.BG_APP))
        palette.setColor(QPalette.AlternateBase, QColor(T.BG_PANEL))
        palette.setColor(QPalette.ToolTipBase, QColor(T.BG_PANEL))
        palette.setColor(QPalette.ToolTipText, QColor(T.TEXT_1))

        palette.setColor(QPalette.Text, QColor(T.TEXT_1))
        palette.setColor(QPalette.Button, QColor(T.BG_PANEL))
        palette.setColor(QPalette.ButtonText, QColor(T.TEXT_2))
        palette.setColor(QPalette.BrightText, QColor(T.STATE_ERR))
        palette.setColor(QPalette.Link, QColor(T.ACCENT_TEXT))

        palette.setColor(QPalette.Highlight, QColor(T.BG_ACTIVE))
        palette.setColor(QPalette.HighlightedText, QColor(T.ACCENT_TEXT))

        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(T.TEXT_DIM))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(T.TEXT_DIM))

        app.setPalette(palette)

        # Global QSS: square corners everywhere, 1px borders, orange focus/accent.
        app.setStyleSheet(f"""
            QWidget {{
                background-color: {T.BG_APP};
                color: {T.TEXT_1};
            }}
            QFrame#sidebar, QFrame#topnav {{
                background-color: {T.BG_PANEL};
                border-bottom: 1px solid {T.BORDER};
            }}
            QFrame.panel {{
                background-color: {T.BG_PANEL};
                border: 1px solid {T.BORDER};
            }}

            QPushButton {{
                background-color: {T.BG_PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 0px;
                padding: 7px 14px;
                color: {T.TEXT_2};
            }}
            QPushButton:hover {{
                border: 1px solid {T.ACCENT};
                color: {T.ACCENT_TEXT};
            }}
            QPushButton:pressed {{
                background-color: {T.BG_ACTIVE};
            }}
            QPushButton:checked {{
                background-color: {T.BG_ACTIVE};
                border: 1px solid {T.BORDER};
                border-top: 2px solid {T.ACCENT};
                color: {T.ACCENT_TEXT};
                font-weight: 600;
            }}
            QPushButton:disabled {{
                color: {T.TEXT_DIM};
                border: 1px solid {T.BORDER};
            }}
            QPushButton#primary {{
                background-color: {T.ACCENT};
                border: 1px solid {T.ACCENT};
                color: {T.BG_APP};
                font-weight: 600;
            }}
            QPushButton#primary:hover {{
                background-color: {T.ACCENT_HOVER};
                border: 1px solid {T.ACCENT_HOVER};
                color: {T.BG_APP};
            }}

            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
                background-color: {T.BG_APP};
                border: 1px solid {T.BORDER_FIELD};
                border-radius: 0px;
                padding: 6px 10px;
                color: {T.TEXT_1};
                selection-background-color: {T.ACCENT};
                selection-color: {T.BG_APP};
            }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
            QTextEdit:focus, QPlainTextEdit:focus {{
                border: 1px solid {T.ACCENT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {T.BG_PANEL};
                border: 1px solid {T.BORDER};
                selection-background-color: {T.BG_ACTIVE};
                selection-color: {T.ACCENT_TEXT};
            }}
            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
                background-color: {T.BG_PANEL};
                border-left: 1px solid {T.BORDER_FIELD};
                width: 16px;
            }}

            QCheckBox {{ color: {T.TEXT_1}; spacing: 10px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {T.BORDER_FIELD};
                background-color: {T.BG_APP};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {T.ACCENT};
                background-color: {T.ACCENT};
            }}

            QTableWidget {{
                background-color: {T.BG_PANEL};
                border: 1px solid {T.BORDER};
                gridline-color: {T.BORDER};
                color: {T.TEXT_1};
            }}
            QHeaderView::section {{
                background-color: {T.BG_HEADER};
                color: {T.TEXT_MUTE};
                border: none;
                border-bottom: 1px solid {T.BORDER};
                padding: 8px 10px;
                font-weight: 600;
            }}
            QTableWidget::item {{
                border-bottom: 1px solid {T.BG_ACTIVE};
                padding: 4px;
            }}
            QTableWidget::item:selected {{
                background-color: {T.BG_ACTIVE};
                color: {T.TEXT_1};
            }}

            QTabWidget::pane {{ border: 1px solid {T.BORDER}; }}
            QTabBar::tab {{
                background: {T.BG_PANEL};
                border: 1px solid {T.BORDER};
                border-bottom: none;
                padding: 8px 16px;
                color: {T.TEXT_MUTE};
            }}
            QTabBar::tab:selected {{
                background: {T.BG_ACTIVE};
                border-top: 2px solid {T.ACCENT};
                color: {T.ACCENT_TEXT};
            }}

            QProgressBar {{
                border: 1px solid {T.BORDER};
                border-radius: 0px;
                background-color: {T.BG_ACTIVE};
                text-align: center;
                color: {T.TEXT_1};
            }}
            QProgressBar::chunk {{
                background-color: {T.ACCENT};
            }}

            QScrollBar:vertical, QScrollBar:horizontal {{
                background: {T.BG_APP};
                border: none;
            }}
            QScrollBar::handle {{
                background: {T.BORDER};
            }}
            QScrollBar::handle:hover {{
                background: {T.TEXT_DIM};
            }}

            QStatusBar {{
                background-color: {T.BG_PANEL};
                border-top: 1px solid {T.BORDER};
                color: {T.TEXT_MUTE};
            }}
            QStatusBar::item {{ border: none; }}

            QToolTip {{
                background-color: {T.BG_PANEL};
                color: {T.TEXT_1};
                border: 1px solid {T.BORDER};
                padding: 4px;
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
