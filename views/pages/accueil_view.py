from PyQt6 import QtWidgets


class AccueilView:
    """Vue de la page d'accueil — expose les widgets trouvés dans le .ui."""

    def __init__(self, widget: QtWidgets.QWidget):
        """Expose les widgets de la page d'accueil (bouton ouvrir, labels titre/sous-titre)."""
        self.widget = widget

        self.btn_open = widget.findChild(QtWidgets.QPushButton, "btn_ouvrir_campagne")
        self.lbl_title = widget.findChild(QtWidgets.QLabel, "lbl_titre_accueil")
        self.lbl_subtitle = widget.findChild(QtWidgets.QLabel, "lbl_sous_titre")
