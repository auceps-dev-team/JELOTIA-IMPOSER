import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.utils.logger import app_logger
from src.ui.main_window import MainWindow

def main():
    app_logger.info("Starting Jelotia Imposer...")
    app = QApplication(sys.argv)
    
    from src.ui.theme import ThemeManager
    from src.utils.config_manager import ConfigManager
    
    config = ConfigManager()
    theme = config.get("ui", "theme") or "dark"
    
    if theme == "light":
        ThemeManager.apply_light_theme(app)
    else:
        ThemeManager.apply_dark_theme(app)
        
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
