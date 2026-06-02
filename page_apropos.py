from PyQt6 import QtWidgets, QtCore


class AProposPage:
    """Contrôleur pour la page À propos."""

    def __init__(self, widget: QtWidgets.QWidget):
        self.widget = widget
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(16, 16, 16, 16)
        self.heading_label = QtWidgets.QLabel("Page À propos", self.widget)
        self.heading_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.heading_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(self.heading_label)

    def set_language(self, langue: str):
        if hasattr(self, 'heading_label'):
            self.heading_label.setText("About page" if langue == 'en' else "Page À propos")
