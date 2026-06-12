from PyQt6 import QtWidgets, QtCore


class ExportOptionsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, is_stereo=False):
        super().__init__(parent)

        self.is_stereo = is_stereo
        self.current_language = 'fr'

        self.setWindowTitle("Options d'exportation")
        self.setModal(True)
        self.resize(350, 320)

        self.setStyleSheet("""
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
            QPushButton {
                font-size: 14px;
                padding: 6px;
                font-weight: bold;
                background-color: rgb(39, 120, 162);
                color: white;
                border: 1px solid #152d42;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)

        self.fps_group = QtWidgets.QGroupBox("", self)
        fps_layout = QtWidgets.QHBoxLayout(self.fps_group)
        self.fps_label = QtWidgets.QLabel("", self.fps_group)
        self.fps_spinbox = QtWidgets.QSpinBox(self.fps_group)
        self.fps_spinbox.setRange(1, 60)
        self.fps_spinbox.setValue(5)
        self.fps_spinbox.setSuffix(" fps")
        fps_layout.addWidget(self.fps_label)
        fps_layout.addWidget(self.fps_spinbox)
        layout.addWidget(self.fps_group)

        self.filters_group = QtWidgets.QGroupBox("", self)
        filters_layout = QtWidgets.QVBoxLayout(self.filters_group)
        self.check_he = QtWidgets.QCheckBox("", self.filters_group)
        self.check_dh = QtWidgets.QCheckBox("", self.filters_group)
        self.check_water = QtWidgets.QCheckBox("", self.filters_group)
        self.check_water.setEnabled(False)
        self.check_dh.toggled.connect(self.check_water.setEnabled)
        filters_layout.addWidget(self.check_he)
        filters_layout.addWidget(self.check_dh)
        filters_layout.addWidget(self.check_water)
        layout.addWidget(self.filters_group)

        self.chk_rectify = QtWidgets.QCheckBox("", self)
        self.chk_rectify.setToolTip("Nécessite matrices.json et les fichiers .txt de synchro")
        self.chk_rectify.setEnabled(self.is_stereo)
        layout.addWidget(self.chk_rectify)

        layout.addSpacing(10)

        self.buttons_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            QtCore.Qt.Orientation.Horizontal,
            self
        )

        self.export_button = self.buttons_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.buttons_box.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)

        self.buttons_box.accepted.connect(self.accept)
        self.buttons_box.rejected.connect(self.reject)
        layout.addWidget(self.buttons_box)

        self.set_language(self.current_language)

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        self.current_language = language
        self.setWindowTitle(self.translate("Options d'exportation", "Export Options"))
        self.fps_group.setTitle(self.translate("Configuration de la cadence (FPS)", "Framerate Configuration (FPS)"))
        self.filters_group.setTitle(self.translate("Filtres d'optimisation d'image", "Image Optimization Filters"))
        self.fps_label.setText(self.translate("Images par seconde :", "Frames per second:"))
        self.check_he.setText(self.translate("Égalisation d'histogramme (HE)", "Histogram Equalization (HE)"))
        self.check_dh.setText(self.translate("Suppression de la brume / flou (Dehaze)", "Haze / Blur Removal (Dehaze)"))
        self.check_water.setText(self.translate("Mode sous-marin (Option Dehaze)", "Underwater Mode (Dehaze Option)"))
        self.chk_rectify.setText(self.translate("Rectifier les images (Stéréo)", "Rectify images (Stereo)"))
        if self.export_button:
            self.export_button.setText(self.translate("Exporter", "Export"))
        if self.cancel_button:
            self.cancel_button.setText(self.translate("Annuler", "Cancel"))

    def get_processing_options(self) -> dict:
        """Retourne un dict avec les options de traitement sélectionnées."""
        return {
            "target_fps": self.fps_spinbox.value(),
            "apply_he": self.check_he.isChecked(),
            "apply_dh": self.check_dh.isChecked(),
            "is_water": self.check_water.isEnabled() and self.check_water.isChecked(),
            "apply_rectify": self.chk_rectify.isEnabled() and self.chk_rectify.isChecked()
        }
