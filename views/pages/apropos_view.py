from PyQt6 import QtWidgets


class AProposView:
    """Vue de la page À propos."""

    def __init__(self, widget: QtWidgets.QWidget):
        """Conserve la référence au widget (page statique sans sous-widgets exposés)."""
        self.widget = widget
