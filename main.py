import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from views.main_window import MainWindow
from controllers.app_controller import AppController
from views.style import APP_STYLESHEET


def main():
    """Point d'entrée de l'application KOSMOS IHM : crée la QApplication, la fenêtre et le contrôleur principal."""
    app = QApplication(sys.argv)

    # Police de base pour tous les widgets
    base_font = QFont("Segoe UI", 10)
    app.setFont(base_font)

    # Thème global KOSMOS
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.controller = AppController(window)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
