import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from src.utils.logger import app_logger

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jelotia Imposer")
        self.resize(800, 600)
        
        layout = QVBoxLayout()
        label = QLabel("Jelotia Imposer - Initialization Phase")
        layout.addWidget(label)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

def main():
    app_logger.info("Starting Jelotia Imposer...")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
