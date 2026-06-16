from PyQt6 import QtWidgets


class AccueilController:
    """Contrôleur de la page Accueil : saisie du dérusher et ouverture de campagne."""

    def __init__(self, page_widget, open_campaign_callback):
        """Connecte le bouton d'ouverture au callback AppController."""
        self.widget = page_widget
        self.open_campaign_callback = open_campaign_callback
        self.derusher_name = ""
        self.current_language = 'fr'

        self.btn_open = self.widget.findChild(QtWidgets.QPushButton, "btn_ouvrir_campagne")
        if self.btn_open:
            self.btn_open.clicked.connect(self.request_derusher_name)

        self.set_language(self.current_language)

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Met à jour la langue et le libellé du bouton."""
        self.current_language = language
        if self.btn_open:
            self.btn_open.setText(self.translate("Ouvrir campagne", "Open campaign"))

    def request_derusher_name(self):
        """Ouvre un dialog de saisie du nom dérusher, puis déclenche l'ouverture de campagne."""
        dialog = QtWidgets.QInputDialog(self.widget)
        dialog.setWindowTitle(self.translate("Identification", "Identification"))
        dialog.setLabelText(self.translate("Nom du dérusher :", "Derusher name:"))
        dialog.setInputMode(QtWidgets.QInputDialog.InputMode.TextInput)
        dialog.setStyleSheet("""
            QInputDialog { background-color: #111820; color: white; }
            QLabel {
                color: #F2BFB4; font-weight: bold; font-size: 13px;
                font-family: "Segoe UI", sans-serif;
            }
            QLineEdit {
                background-color: #162433; color: #F2BFB4;
                border: 1px solid #2778A2; border-radius: 4px;
                padding: 7px; font-size: 13px; font-family: "Segoe UI", sans-serif;
            }
            QLineEdit:focus { border: 2px solid #2778A2; }
            QPushButton {
                background-color: #20415D; color: white; font-weight: bold;
                border: 1px solid #2778A2; border-radius: 4px;
                padding: 7px 18px; font-size: 12px; min-width: 70px;
                font-family: "Segoe UI", sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
            QPushButton:pressed { background-color: #152d42; border-color: #F2BFB4; }
        """)

        executable = dialog.exec()
        name = dialog.textValue()

        if executable == QtWidgets.QDialog.DialogCode.Accepted:
            if name.strip():
                self.derusher_name = name.strip()
                self.open_campaign_callback(self.derusher_name)
            else:
                QtWidgets.QMessageBox.warning(
                    self.widget,
                    self.translate("Champ requis", "Required field"),
                    self.translate(
                        "Vous devez obligatoirement saisir un nom pour continuer.",
                        "You must enter a name to continue."
                    )
                )
