from PyQt6 import QtWidgets, QtCore


class ExportOptionsDialog(QtWidgets.QDialog):
    """Dialog de configuration des options d'export image (FPS, filtres, rectification stéréo)."""

    def __init__(self, parent=None, is_stereo=False):
        """
        Args:
            is_stereo: Active la case rectification stéréo si True.
        """
        super().__init__(parent)

        self.is_stereo = is_stereo
        self.current_language = 'fr'

        self.setWindowTitle("Options d'exportation")
        self.setModal(True)
        self.resize(350, 320)

        self.setStyleSheet("""
            QDialog { background-color: #111820; color: #ffffff; }
            QLabel { color: #b0c8d8; font-family: "Segoe UI", sans-serif; }
            QGroupBox {
                border: 1px solid #2778A2; border-radius: 5px;
                margin-top: 18px; padding-top: 10px; color: #F2BFB4;
                font-family: "Segoe UI", sans-serif; font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 3px 8px; background-color: #2778A2; color: white;
                border-radius: 3px; font-size: 12px; font-weight: bold;
            }
            QCheckBox { color: #b0c8d8; spacing: 6px; font-family: "Segoe UI", sans-serif; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #2778A2; border-radius: 3px; background: #162433;
            }
            QCheckBox::indicator:checked { background-color: #2778A2; }
            QSpinBox {
                background-color: #162433; color: #F2BFB4;
                border: 1px solid #2a4057; border-radius: 3px; padding: 3px 6px;
                font-family: "Segoe UI", sans-serif;
            }
            QSpinBox:focus { border-color: #2778A2; }
            QPushButton {
                background-color: #20415D; color: white; font-weight: bold;
                border: 1px solid #2778A2; border-radius: 4px;
                padding: 6px 18px; font-size: 12px; font-family: "Segoe UI", sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
            QPushButton:pressed { background-color: #152d42; }
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

        self.chk_include_images = QtWidgets.QCheckBox("", self)
        self.chk_include_images.setChecked(True)
        self.chk_include_images.toggled.connect(self._on_include_images_toggled)
        layout.addWidget(self.chk_include_images)

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

    def _on_include_images_toggled(self, checked: bool):
        self.fps_group.setEnabled(checked)
        self.filters_group.setEnabled(checked)
        self.chk_rectify.setEnabled(checked and self.is_stereo)

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Traduit tous les libellés du dialog."""
        self.current_language = language
        self.setWindowTitle(self.translate("Options d'exportation", "Export Options"))
        self.fps_group.setTitle(self.translate("Configuration de la cadence (FPS)", "Framerate Configuration (FPS)"))
        self.filters_group.setTitle(self.translate("Filtres d'optimisation d'image", "Image Optimization Filters"))
        self.fps_label.setText(self.translate("Images par seconde :", "Frames per second:"))
        self.check_he.setText(self.translate("Égalisation d'histogramme (HE)", "Histogram Equalization (HE)"))
        self.check_dh.setText(self.translate("Suppression de la brume / flou (Dehaze)", "Haze / Blur Removal (Dehaze)"))
        self.check_water.setText(self.translate("Mode sous-marin (Option Dehaze)", "Underwater Mode (Dehaze Option)"))
        self.chk_rectify.setText(self.translate("Rectifier les images (Stéréo)", "Rectify images (Stereo)"))
        self.chk_include_images.setText(self.translate("Exporter le lot d'images", "Export image batch"))
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
            "apply_rectify": self.chk_rectify.isEnabled() and self.chk_rectify.isChecked(),
            "include_images": self.chk_include_images.isChecked(),
        }
