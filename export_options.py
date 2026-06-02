from PyQt6 import QtWidgets, QtCore

class ExportOptionsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options d'exportation")
        self.setModal(True)
        self.resize(350, 280)  # Ajusté pour la nouvelle taille sans sélection d'événements
        
        # --------------------------------------------------------------------
        # APPLICATION STRICTE DE VOTRE STYLE (FONDS BLEUS / TEXTES BLANCS GRAS)
        # --------------------------------------------------------------------
        self.setStyleSheet("""
            /* Style pour les titres des blocs (sections) */
            QGroupBox {
                margin-top: 20px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 6px;
                font-size: 14px;
                font-weight: bold;
                background-color: rgb(39, 120, 162);
                color: white;
                border: 1px solid #152d42;
            }

            /* Style pour les boutons d'action */
            QPushButton {
                font-size: 14px;
                padding: 6px;
                font-weight: bold;
                background-color: rgb(39, 120, 162);
                color: white;
                border: 1px solid #152d42;
            }
        """)

        # Layout principal de la boîte de dialogue
        layout = QtWidgets.QVBoxLayout(self)
        
        # 1. SECTION FPS
        fps_group = QtWidgets.QGroupBox("Configuration de la cadence (FPS)", self)
        fps_layout = QtWidgets.QHBoxLayout(fps_group)
        
        fps_label = QtWidgets.QLabel("Images par seconde :", fps_group)
        self.fps_spinbox = QtWidgets.QSpinBox(fps_group)
        self.fps_spinbox.setRange(1, 60)      # Limites (1 à 60 images par seconde)
        self.fps_spinbox.setValue(5)          # Valeur par défaut à 5 FPS
        self.fps_spinbox.setSuffix(" fps")
        
        fps_layout.addWidget(fps_label)
        fps_layout.addWidget(self.fps_spinbox)
        layout.addWidget(fps_group)
        
        # 2. SECTION FILTRES D'OPTIMISATION
        filters_group = QtWidgets.QGroupBox("Filtres d'optimisation d'image", self)
        filters_layout = QtWidgets.QVBoxLayout(filters_group)
        
        self.check_he = QtWidgets.QCheckBox("Égalisation d'histogramme (HE)", filters_group)
        self.check_dh = QtWidgets.QCheckBox("Suppression de la brume / flou (Dehaze)", filters_group)
        self.check_water = QtWidgets.QCheckBox("Mode sous-marin (Option Dehaze)", filters_group)
        
        # Par défaut, le mode sous-marin est désactivé tant que Dehaze n'est pas coché
        self.check_water.setEnabled(False)
        self.check_dh.toggled.connect(self.check_water.setEnabled)
        
        filters_layout.addWidget(self.check_he)
        filters_layout.addWidget(self.check_dh)
        filters_layout.addWidget(self.check_water)
        layout.addWidget(filters_group)
        
        # Spacing pour détacher les boutons d'action du bas de la dernière boîte
        layout.addSpacing(10)

        # BOUTONS ACTION (ANNULER / VALIDER)
        buttons_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            QtCore.Qt.Orientation.Horizontal,
            self
        )
        
        # Personnalisation des textes en français
        export_button = buttons_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if export_button:
            export_button.setText("Exporter")
            
        cancel_button = buttons_box.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        if cancel_button:
            cancel_button.setText("Annuler")
        
        # Connexions des signaux standards de fermeture
        buttons_box.accepted.connect(self.accept)
        buttons_box.rejected.connect(self.reject)
        layout.addWidget(buttons_box)

    def get_processing_options(self):
        """
        Renvoie un dictionnaire contenant le FPS choisi et les filtres activés.
        """
        return {
            "target_fps": self.fps_spinbox.value(),
            "apply_he": self.check_he.isChecked(),
            "apply_dh": self.check_dh.isChecked(),
            "is_water": self.check_water.isEnabled() and self.check_water.isChecked()
        }