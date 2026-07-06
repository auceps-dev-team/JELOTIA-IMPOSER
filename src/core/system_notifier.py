from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from src.utils.config_manager import ConfigManager


class SystemNotifier:
    def __init__(self, parent=None):
        self.config = ConfigManager()
        self.tray = QSystemTrayIcon(parent)
        
        # We need an icon to show the tray, usually application's window icon
        if parent and parent.windowIcon() and not parent.windowIcon().isNull():
            self.tray.setIcon(parent.windowIcon())
        else:
            # Fallback icon
            # It's better to create a dummy icon if none exists so that the tray works
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(32, 32)
            pixmap.fill(parent.palette().window().color() if parent else "blue")
            self.tray.setIcon(QIcon(pixmap))
            
        self.tray.show()

    def notify(self, title: str, message: str, is_error: bool = False):
        if not self.config.get("output", "enable_notifications"):
            return
            
        icon_type = QSystemTrayIcon.Critical if is_error else QSystemTrayIcon.Information
        self.tray.showMessage(title, message, icon_type, 3000)
