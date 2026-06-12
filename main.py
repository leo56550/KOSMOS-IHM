import sys

from PyQt6.QtWidgets import QApplication

from views.main_window import MainWindow
from controllers.app_controller import AppController


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.controller = AppController(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
