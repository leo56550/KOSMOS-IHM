import cv2
import numpy as np
from PyQt6 import QtWidgets, QtCore, QtGui

from services.image_service import (
    process_image_he,
    process_image_dehaze,
    calculate_atmospheric_light,
    calculate_water_light
)


class CaptureDialog(QtWidgets.QDialog):
    """Dialog de validation d'une capture image avec prévisualisation et traitements optionnels."""

    def __init__(self, parent, frame, current_name, brightness, contrast, sharpen, is_stereo=False):
        """
        Args:
            frame: Image BGR (numpy) extraite de la vidéo.
            current_name: Nom de fichier par défaut.
            brightness, contrast, sharpen: Valeurs initiales des sliders.
            is_stereo: Affiche deux vignettes L/R si True.
        """
        super().__init__(parent)
        self.is_stereo = is_stereo
        self.setWindowTitle("Validation de la capture " + ("(Stéréo)" if is_stereo else "(Mono)"))

        self.resize(1000 if is_stereo else 800, 600)
        self.setMinimumSize(600, 450)
        self.setSizeGripEnabled(True)

        self.raw_frame = frame.copy()
        self.result_name = None

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
                border-radius: 3px; font-size: 12px;
            }
            QLineEdit {
                background-color: #162433; color: #F2BFB4;
                border: 1px solid #2a4057; border-radius: 4px; padding: 5px 8px;
                font-family: "Segoe UI", sans-serif;
            }
            QLineEdit:focus { border-color: #2778A2; }
            QCheckBox { color: #b0c8d8; spacing: 6px; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #2778A2; border-radius: 3px; background: #162433;
            }
            QCheckBox::indicator:checked { background-color: #2778A2; }
            QPushButton {
                background-color: #20415D; color: white; font-weight: bold;
                border: 1px solid #2778A2; border-radius: 4px; padding: 7px 18px;
                font-family: "Segoe UI", sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
            QPushButton:pressed { background-color: #152d42; }
        """)

        self.a_vector_normal = calculate_atmospheric_light(self.raw_frame)
        self.a_vector_water = calculate_water_light(self.raw_frame)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.img_container = QtWidgets.QWidget()
        self.img_layout = QtWidgets.QHBoxLayout(self.img_container)

        if self.is_stereo:
            self.lbl_img_left = self._create_image_label("GAUCHE")
            self.lbl_img_right = self._create_image_label("DROITE")
            self.img_layout.addWidget(self.lbl_img_left)
            self.img_layout.addWidget(self.lbl_img_right)
        else:
            self.lbl_img = self._create_image_label()
            self.img_layout.addWidget(self.lbl_img)

        self.main_layout.addWidget(self.img_container, stretch=1)

        self.controls_widget = QtWidgets.QWidget()
        self.controls_layout = QtWidgets.QVBoxLayout(self.controls_widget)

        form = QtWidgets.QFormLayout()
        self.edit_name = QtWidgets.QLineEdit(current_name)
        form.addRow("Nom du fichier :", self.edit_name)
        self.controls_layout.addLayout(form)

        group_algo = QtWidgets.QGroupBox("Traitements avancés")
        algo_layout = QtWidgets.QHBoxLayout(group_algo)
        self.chk_he = QtWidgets.QCheckBox("Égalisation (HE)")
        self.chk_dh = QtWidgets.QCheckBox("Débrumage (Dehaze)")
        self.chk_water = QtWidgets.QCheckBox("Sous-marin")
        self.chk_water.setEnabled(False)
        algo_layout.addWidget(self.chk_he)
        algo_layout.addWidget(self.chk_dh)
        algo_layout.addWidget(self.chk_water)
        self.controls_layout.addWidget(group_algo)

        grid_sliders = QtWidgets.QGridLayout()
        self.sld_b = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sld_b.setRange(-100, 100)
        self.sld_b.setValue(brightness)
        self.sld_c = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sld_c.setRange(10, 30)
        self.sld_c.setValue(contrast)

        grid_sliders.addWidget(QtWidgets.QLabel("Luminosité :"), 0, 0)
        grid_sliders.addWidget(self.sld_b, 0, 1)
        grid_sliders.addWidget(QtWidgets.QLabel("Contraste :"), 1, 0)
        grid_sliders.addWidget(self.sld_c, 1, 1)
        self.controls_layout.addLayout(grid_sliders)

        self.btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.controls_layout.addWidget(self.btns)
        self.main_layout.addWidget(self.controls_widget)

        self.sld_b.valueChanged.connect(self.update_preview)
        self.sld_c.valueChanged.connect(self.update_preview)
        self.chk_he.stateChanged.connect(self.update_preview)
        self.chk_dh.stateChanged.connect(self.on_dehaze_toggled)
        self.chk_water.stateChanged.connect(self.update_preview)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)

        self.update_preview()

    def _create_image_label(self, text=""):
        """Crée un QLabel stylé pour l'affichage d'une vignette image."""
        lbl = QtWidgets.QLabel(text)
        lbl.setMinimumSize(400 if self.is_stereo else 480, 270)
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        lbl.setScaledContents(True)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("border: 1px solid #2778A2; background-color: #000000; border-radius: 4px;")
        return lbl

    def on_dehaze_toggled(self):
        """Active/désactive le mode sous-marin en fonction de l'état du checkbox dehaze."""
        self.chk_water.setEnabled(self.chk_dh.isChecked())
        self.update_preview()

    def update_preview(self):
        """Applique les traitements actifs et met à jour la prévisualisation."""
        processed = self.raw_frame.copy()

        if self.chk_dh.isChecked():
            vec = self.a_vector_water if self.chk_water.isChecked() else self.a_vector_normal
            processed = process_image_dehaze(processed, vec, is_water=self.chk_water.isChecked())

        if self.chk_he.isChecked():
            processed = process_image_he(processed)

        c = self.sld_c.value() / 10.0
        b = self.sld_b.value()
        processed = cv2.convertScaleAbs(processed, alpha=c, beta=b)

        rgb = cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888).copy()
        pix = QtGui.QPixmap.fromImage(qimg)

        if self.is_stereo:
            mid = w // 2
            self.lbl_img_left.setPixmap(pix.copy(0, 0, mid, h))
            self.lbl_img_right.setPixmap(pix.copy(mid, 0, mid, h))
        else:
            self.lbl_img.setPixmap(pix)

        self.current_processed = processed

    def get_values(self):
        return self.edit_name.text(), self.current_processed
