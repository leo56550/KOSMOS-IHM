import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from views.main_window import MainWindow
from controllers.app_controller import AppController
from views.style import APP_STYLESHEET


def main():
    """Point d'entrée de l'application KOSMOS IHM : crée la QApplication, la fenêtre et le contrôleur principal."""
    app = QApplication(sys.argv)

    # Fusion garantit que le QSS est rendu correctement sur Windows
    # (évite le fond blanc des QToolBar et autres artefacts du style natif)
    app.setStyle("Fusion")

    # Police de base pour tous les widgets
    base_font = QFont("Segoe UI", 10)
    app.setFont(base_font)

    # Thème global KOSMOS
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.setWindowTitle("KOSMOS IHM")
    window.controller = AppController(window)

    # Langue par défaut : français (le drapeau FR est coché visuellement mais la langue
    # n'était jamais propagée aux contrôleurs au démarrage)
    window.controller.set_language("fr")

    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
