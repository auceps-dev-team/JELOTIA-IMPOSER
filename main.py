import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.utils.logger import app_logger
from src.ui.main_window import MainWindow

def main():
    app_logger.info("Starting Jelotia Imposer...")
    app = QApplication(sys.argv)
    
    # Load stylesheet
    qss_path = Path(__file__).parent / "src" / "ui" / "resources" / "dark_theme.qss"
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    else:
        app_logger.warning(f"Stylesheet not found at {qss_path}")
        
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
