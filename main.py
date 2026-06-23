import sys
import os
import traceback

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from views.main_window import MainWindow
from controllers.app_controller import AppController
from views.style import APP_STYLESHEET


def _setup_crash_log():
    """Redirige les exceptions non gérées vers un fichier kosmos_crash.log."""
    log_path = os.path.join(os.path.dirname(sys.executable)
                            if getattr(sys, "frozen", False)
                            else os.path.dirname(os.path.abspath(__file__)),
                            "kosmos_crash.log")

    def excepthook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        with open(log_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n{'='*60}\n{datetime.now()}\n{msg}")
        # Affiche aussi en console si disponible
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook
    return log_path


def main():
    log_path = _setup_crash_log()
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
