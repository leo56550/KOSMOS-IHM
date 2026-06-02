from PyQt6 import QtWidgets

class AccueilPage:
    def __init__(self, widget_page, fonction_ouvrir_campagne):
        """
        Contrôleur pour la page d'accueil.
        :param widget_page: Le widget de la page chargé depuis le .ui
        :param fonction_ouvrir_campagne: La méthode à exécuter si la saisie est validée
        """
        self.widget = widget_page
        self.fonction_ouvrir_campagne = fonction_ouvrir_campagne
        
        # Nom du dérusher qui sera stocké après saisie (optionnel, si tu en as besoin plus tard)
        self.nom_derusher = ""
        self.current_language = 'fr'
        
        # Récupération du bouton depuis le widget de la page
        self.btn_ouvrir = self.widget.findChild(QtWidgets.QPushButton, "btn_ouvrir_campagne")
        
        # Connexion du bouton
        if self.btn_ouvrir:
            self.btn_ouvrir.clicked.connect(self.demander_nom_derusher)
        else:
            print("Attention : 'btn_ouvrir_campagne' non trouvé dans la page d'accueil.")
        self.set_language(self.current_language)

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, langue: str):
        self.current_language = langue
        if self.btn_ouvrir:
            self.btn_ouvrir.setText(self.translate("Ouvrir campagne", "Open campaign"))

    def demander_nom_derusher(self):
        # 1. Création de l'instance de la boîte de dialogue
        dialog = QtWidgets.QInputDialog(self.widget)
        dialog.setWindowTitle(self.translate("Identification", "Identification"))
        dialog.setLabelText(self.translate("Nom du dérusher :", "Derusher name:"))
        dialog.setInputMode(QtWidgets.QInputDialog.InputMode.TextInput)
        
        # 2. Application du style adapté à la boîte de dialogue
        dialog.setStyleSheet("""
            QInputDialog {
                background-color: #20415d;
                color: white;
            }
            QLabel {
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #ffffff;
                color: #20415d;
                border: 1px solid #2778a2;
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #00a2ff;
            }
            QPushButton {
                background-color: #2778a2;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 6px 15px;
                font-size: 12px;
                min-width: 65px;
            }
            QPushButton:hover {
                background-color: #00a2ff;
            }
            QPushButton:pressed {
                background-color: #20415d;
                border: 1px solid #ffffff;
            }
        """)

        # 3. Affichage et récupération du résultat
        executable = dialog.exec()
        nom = dialog.textValue()
        
        # 4. Vérification du résultat (validation)
        if executable == QtWidgets.QDialog.DialogCode.Accepted:
            if nom.strip():
                self.nom_derusher = nom.strip()
                print(f"Campagne ouverte par : {self.nom_derusher}")
                
                # On lance la logique d'ouverture de la campagne
                self.fonction_ouvrir_campagne(self.nom_derusher)
            else:
                QtWidgets.QMessageBox.warning(
                    self.widget,
                    self.translate("Champ requis", "Required field"),
                    self.translate(
                        "Vous devez obligatoirement saisir un nom pour continuer.",
                        "You must enter a name to continue."
                    )
                )