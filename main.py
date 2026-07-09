import multiprocessing
import sys

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.logger import app_logger


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
    # Required for multiprocessing (ProcessPoolExecutor, used by the worker
    # pool) to work in a frozen PyInstaller build on Windows. Without this,
    # each spawned worker process doesn't recognize itself as a worker and
    # re-runs this whole module as if freshly launched — opening a brand new
    # GUI window per worker instead of executing the submitted job function
    # (which is also why jobs never actually produced any sheets: the real
    # work never ran, the process pool just kept spawning more app windows).
    multiprocessing.freeze_support()
    main()
