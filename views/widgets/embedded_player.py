import os
import time
import cv2
import numpy as np
import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from views.widgets.timeline_widget import VideoTimeline
from views.dialogs.telemetry_dialog import TelemetryDialog
from views.style import (C_INDIGO, C_CERULEAN, C_JASPER, C_MELON,
                          C_BG_DARK, C_PRESSED, C_BORDER_SUB, BTN_PRIMARY, BTN_TOGGLE, SLIDER)

_SLIDER_STYLE = SLIDER
_BTN_STYLE = BTN_PRIMARY
_TOGGLE_STYLE = BTN_TOGGLE


class _VideoLabel(QtWidgets.QWidget):
    """Widget d'affichage vidéo — stocke un QImage et le scale dans paintEvent sans passer par QPixmap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._image: QtGui.QImage | None = None

    def set_image(self, image: QtGui.QImage):
        self._image = image
        self.update()

    def clear(self):
        self._image = None
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.black)
        if self._image is not None and not self._image.isNull():
            scaled = self._image.size().scaled(
                self.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(QtCore.QRect(x, y, scaled.width(), scaled.height()), self._image)


class EmbeddedVideoPlayer(QtWidgets.QWidget):
    """Lecteur vidéo embarqué avec timeline, corrections image et support stéréo."""

    playback_state_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None, zone_definitions=None):
        """Construit l'interface complète : affichage vidéo, timeline, panneaux corrections et télémétrie."""
        super().__init__(parent)

        self.player = QMediaPlayer()
        self.player_R = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.is_stereo = False
        self.slider_was_playing = False
        self.current_video_path = None
        self.video_fps = 0.0
        self.current_language = 'fr'

        # Legacy compat
        self.apply_dehaze = False
        self.apply_histogram = False
        self.he_params = {"vB": 3, "vG": 3, "vR": 3}

        # Throttle UI updates (timeline, labels) pendant la lecture
        self._last_ui_update_ms: int = 0

        # Image corrections (active only when paused)
        self._last_raw_frame: np.ndarray | None = None
        self._corr_he = False
        self._corr_dehaze = False
        self._corr_contrast = 1.0
        self._corr_brightness = 0

        # ── Layout ──────────────────────────────────────────────────────────
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Video display
        self.display_stack = QtWidgets.QStackedWidget()
        self.display_stack.setStyleSheet("background-color: black; border-radius: 6px 6px 0px 0px;")

        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                 "img", "logo_kosmos.png")
        pixmap = QtGui.QPixmap(logo_path)
        if not pixmap.isNull():
            self.logo_label.setPixmap(
                pixmap.scaled(400, 400, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                              QtCore.Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo_label.setText("KOSMOS PLAYER")
            self.logo_label.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        self.display_stack.addWidget(self.logo_label)

        self.video_container = QtWidgets.QWidget()
        vc_layout = QtWidgets.QHBoxLayout(self.video_container)
        vc_layout.setContentsMargins(0, 0, 0, 0)
        vc_layout.setSpacing(2)

        # Caméra gauche : QVideoWidget (rendu hardware) + overlay corrections (_VideoLabel)
        self.video_widget = QVideoWidget()
        self.video_widget.setAspectRatioMode(QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self.correction_overlay = _VideoLabel()
        self.left_display = QtWidgets.QStackedWidget()
        self.left_display.addWidget(self.video_widget)      # index 0 → lecture hardware
        self.left_display.addWidget(self.correction_overlay)  # index 1 → corrections OpenCV
        self.left_display.setCurrentIndex(0)

        # Caméra droite (stéréo uniquement)
        self.video_widget_R = QVideoWidget()
        self.video_widget_R.setAspectRatioMode(QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self.video_widget_R.setVisible(False)

        vc_layout.addWidget(self.left_display)
        vc_layout.addWidget(self.video_widget_R)
        self.display_stack.addWidget(self.video_container)

        # Connecter les players à leurs QVideoWidget (rendu natif, 0 CPU)
        self.player.setVideoOutput(self.video_widget)
        self.player_R.setVideoOutput(self.video_widget_R)

        # Time bar
        self.time_layout = QtWidgets.QHBoxLayout()
        self.time_layout.setContentsMargins(10, 4, 10, 4)

        self.lbl_top_time = QtWidgets.QLabel("00:00 / 00:00")
        self.lbl_top_time.setStyleSheet(
            f"color: {C_MELON}; font-weight: bold; font-size: 13px; border: none;"
            " font-family: 'Segoe UI', sans-serif;")
        self.time_layout.addWidget(self.lbl_top_time)

        self.lbl_frame_number = QtWidgets.QLabel("Frame: -")
        self.lbl_frame_number.setStyleSheet(
            f"color: #b0c8d8; font-size: 12px; margin-left: 12px; border: none;")
        self.time_layout.addWidget(self.lbl_frame_number)
        self.time_layout.addStretch()

        self.lbl_zoom = QtWidgets.QLabel("")
        self.lbl_zoom.setStyleSheet(f"color: #b0c8d8; font-size: 11px; margin-right: 5px;")
        self.time_layout.addWidget(self.lbl_zoom)

        self.slider_zoom = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_zoom.setRange(1, 10)
        self.slider_zoom.setValue(1)
        self.slider_zoom.setFixedWidth(100)
        self.slider_zoom.setStyleSheet(_SLIDER_STYLE)
        self.time_layout.addWidget(self.slider_zoom)

        # Timeline
        self.scroll_area_timeline = QtWidgets.QScrollArea()
        self.scroll_area_timeline.setWidgetResizable(True)
        self.scroll_area_timeline.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area_timeline.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area_timeline.setStyleSheet(
            "QScrollArea { border: none; background-color: #141414; }")

        self.timeline = VideoTimeline([], parent=self, zone_definitions=zone_definitions)
        self.timeline.setMinimumHeight(140)
        self.scroll_area_timeline.setWidget(self.timeline)

        # Playback buttons
        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setContentsMargins(5, 5, 5, 5)
        buttons_layout.setSpacing(5)

        sys_style = QtWidgets.QApplication.style()
        self.btn_start = QtWidgets.QPushButton()
        self.btn_start.setIcon(sys_style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_stop = QtWidgets.QPushButton()
        self.btn_stop.setIcon(sys_style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPause))
        self.btn_m10 = QtWidgets.QPushButton("-10s")
        self.btn_p10 = QtWidgets.QPushButton("+10s")
        self.btn_x1 = QtWidgets.QPushButton("x1")
        self.btn_x2 = QtWidgets.QPushButton("x2")
        self.btn_x5 = QtWidgets.QPushButton("x5")
        self.btn_x10 = QtWidgets.QPushButton("x10")

        for btn in [self.btn_start, self.btn_stop, self.btn_m10, self.btn_p10,
                    self.btn_x1, self.btn_x2, self.btn_x5, self.btn_x10]:
            btn.setStyleSheet(_BTN_STYLE)
            buttons_layout.addWidget(btn)

        self._sep_cam = self._vline()
        self.btn_cam_L = QtWidgets.QPushButton("Cam G")
        self.btn_cam_L.setCheckable(True)
        self.btn_cam_L.setChecked(True)
        self.btn_cam_L.setStyleSheet(_TOGGLE_STYLE)

        self.btn_cam_R = QtWidgets.QPushButton("Cam D")
        self.btn_cam_R.setCheckable(True)
        self.btn_cam_R.setChecked(True)
        self.btn_cam_R.setStyleSheet(_TOGGLE_STYLE)

        for w in [self._sep_cam, self.btn_cam_L, self.btn_cam_R]:
            w.setVisible(False)
            buttons_layout.addWidget(w)

        # ── Corrections panel ─────────────────────────────────────────────
        self.corrections_panel = QtWidgets.QFrame()
        self.corrections_panel.setStyleSheet(
            f"QFrame {{ background-color: {C_BG_DARK}; border-top: 1px solid {C_CERULEAN}; }}")
        corr_layout = QtWidgets.QHBoxLayout(self.corrections_panel)
        corr_layout.setContentsMargins(8, 5, 8, 5)
        corr_layout.setSpacing(10)

        self.lbl_corrections_title = QtWidgets.QLabel("Corrections :")
        self.lbl_corrections_title.setStyleSheet(
            f"color: {C_MELON}; font-size: 11px; font-weight: bold; border: none;"
            " font-family: 'Segoe UI', sans-serif;")
        corr_layout.addWidget(self.lbl_corrections_title)

        self.btn_corr_he = QtWidgets.QPushButton("HR")
        self.btn_corr_he.setCheckable(True)
        self.btn_corr_he.setStyleSheet(_TOGGLE_STYLE)
        self.btn_corr_he.toggled.connect(self._on_corr_he_toggled)

        self.btn_corr_dehaze = QtWidgets.QPushButton("Dehaze")
        self.btn_corr_dehaze.setCheckable(True)
        self.btn_corr_dehaze.setStyleSheet(_TOGGLE_STYLE)
        self.btn_corr_dehaze.toggled.connect(self._on_corr_dehaze_toggled)

        sep1 = self._vline()

        self.lbl_contrast_lbl = self._make_corr_label("Contraste :")
        self.slider_contrast = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(50, 250)
        self.slider_contrast.setValue(100)
        self.slider_contrast.setFixedWidth(90)
        self.slider_contrast.setStyleSheet(_SLIDER_STYLE)
        self.lbl_contrast_val = self._make_corr_label("1.0×", min_w=32)
        self.slider_contrast.valueChanged.connect(self._on_contrast_changed)

        sep2 = self._vline()

        self.lbl_brightness_lbl = self._make_corr_label("Luminosité :")
        self.slider_brightness = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_brightness.setRange(-100, 100)
        self.slider_brightness.setValue(0)
        self.slider_brightness.setFixedWidth(90)
        self.slider_brightness.setStyleSheet(_SLIDER_STYLE)
        self.lbl_brightness_val = self._make_corr_label("0", min_w=25)
        self.slider_brightness.valueChanged.connect(self._on_brightness_changed)

        sep3 = self._vline()

        self.btn_reset_corr = QtWidgets.QPushButton("Reset")
        self.btn_reset_corr.setStyleSheet(_TOGGLE_STYLE)
        self.btn_reset_corr.clicked.connect(self._reset_corrections)

        self.lbl_pause_hint = QtWidgets.QLabel("⏸ pause pour activer")
        self.lbl_pause_hint.setStyleSheet(f"color: {C_BORDER_SUB}; font-size: 10px; border: none; font-style: italic;")

        for w in [self.btn_corr_he, self.btn_corr_dehaze, sep1,
                  self.lbl_contrast_lbl, self.slider_contrast, self.lbl_contrast_val,
                  sep2, self.lbl_brightness_lbl, self.slider_brightness, self.lbl_brightness_val,
                  sep3, self.btn_reset_corr]:
            corr_layout.addWidget(w)
        corr_layout.addStretch()
        corr_layout.addWidget(self.lbl_pause_hint)

        # ── Telemetry dialog ──────────────────────────────────────────────
        self.telemetry_dialog = TelemetryDialog(self)

        # ── Splitter ──────────────────────────────────────────────────────
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.display_stack)

        bottom_container = QtWidgets.QWidget()
        bottom_vbox = QtWidgets.QVBoxLayout(bottom_container)
        bottom_vbox.setContentsMargins(0, 0, 0, 0)
        bottom_vbox.setSpacing(0)

        time_container = QtWidgets.QWidget()
        time_container.setLayout(self.time_layout)
        buttons_container = QtWidgets.QWidget()
        buttons_container.setLayout(buttons_layout)

        bottom_vbox.addWidget(time_container)
        bottom_vbox.addWidget(self.scroll_area_timeline)
        bottom_vbox.addWidget(buttons_container)
        bottom_vbox.addWidget(self.corrections_panel)

        self.splitter.addWidget(bottom_container)
        main_layout.addWidget(self.splitter)

        # ── Signals ───────────────────────────────────────────────────────
        self.btn_start.clicked.connect(self.play_all)
        self.btn_stop.clicked.connect(self.pause_all)
        self.btn_m10.clicked.connect(lambda: self.jump_time_offset(-10000))
        self.btn_p10.clicked.connect(lambda: self.jump_time_offset(10000))
        self.btn_x1.clicked.connect(lambda: self.set_playback_rate_all(1.0))
        self.btn_x2.clicked.connect(lambda: self.set_playback_rate_all(2.0))
        self.btn_x5.clicked.connect(lambda: self.set_playback_rate_all(5.0))
        self.btn_x10.clicked.connect(lambda: self.set_playback_rate_all(10.0))

        self.btn_cam_L.toggled.connect(self._on_cam_L_toggled)
        self.btn_cam_R.toggled.connect(self._on_cam_R_toggled)

        self.slider_zoom.valueChanged.connect(self.on_zoom_changed)
        self.player.positionChanged.connect(self.on_player_position_changed)
        self.player.durationChanged.connect(self.on_player_duration_changed)
        self.timeline.timeChanged.connect(self.on_timeline_pressed)
        self.timeline.sliderMoved.connect(self.on_timeline_released)
        self.timeline.zoomChanged.connect(self.on_timeline_zoom_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

        self.df_telemetry = None
        self._update_corrections_enabled(is_playing=False)
        self.set_language(self.current_language)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_corr_label(text: str, min_w: int = 0) -> QtWidgets.QLabel:
        """Crée un QLabel stylisé pour le panneau corrections."""
        lbl = QtWidgets.QLabel(text)
        style = f"color: #b0c8d8; font-size: 11px; border: none; font-family: 'Segoe UI', sans-serif;"
        if min_w:
            style += f" min-width: {min_w}px;"
        lbl.setStyleSheet(style)
        return lbl

    @staticmethod
    def _vline() -> QtWidgets.QFrame:
        """Crée un séparateur vertical pour les barres de boutons."""
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setStyleSheet("color: #2a4057;")
        return sep

    # ── Language ──────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        """Retourne la chaîne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Met à jour la langue et rafraîchit les tooltips et labels de temps."""
        self.current_language = language
        self.lbl_zoom.setText(self.translate("Zoom :", "Zoom:"))
        self.btn_start.setToolTip(self.translate("LIRE", "PLAY"))
        self.btn_stop.setToolTip(self.translate("PAUSE", "PAUSE"))
        self.btn_cam_L.setText(self.translate("Cam G", "Cam L"))
        self.btn_cam_L.setToolTip(self.translate("Afficher/masquer caméra gauche", "Show/hide left camera"))
        self.btn_cam_R.setText(self.translate("Cam D", "Cam R"))
        self.btn_cam_R.setToolTip(self.translate("Afficher/masquer caméra droite", "Show/hide right camera"))
        self.lbl_corrections_title.setText(self.translate("Corrections :", "Corrections:"))
        self.btn_corr_he.setToolTip(self.translate(
            "Égalisation d'histogramme (améliore le contraste global)",
            "Histogram equalization (improves overall contrast)"))
        self.btn_corr_dehaze.setToolTip(self.translate(
            "Réduction de voile (CLAHE sur canal L)",
            "Haze reduction (CLAHE on L channel)"))
        self.lbl_contrast_lbl.setText(self.translate("Contraste :", "Contrast:"))
        self.lbl_brightness_lbl.setText(self.translate("Luminosité :", "Brightness:"))
        self.btn_reset_corr.setToolTip(self.translate(
            "Réinitialiser toutes les corrections", "Reset all corrections"))
        self.lbl_pause_hint.setText(self.translate("⏸ pause pour activer", "⏸ pause to activate"))
        if hasattr(self, 'telemetry_dialog'):
            self.telemetry_dialog.set_language(language)
        self.update_top_time_label(self.player.position(), self.player.duration())
        self.update_frame_label(self.player.position())

    # ── Frame rendering ───────────────────────────────────────────────────

    # ── Image corrections ─────────────────────────────────────────────────

    def _has_active_corrections(self) -> bool:
        """Retourne True si au moins une correction (HE, dehaze, contraste, luminosité) est active."""
        return (self._corr_he or self._corr_dehaze
                or self._corr_contrast != 1.0 or self._corr_brightness != 0)

    def _apply_corrections(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Applique les corrections actives (HE, dehaze, contraste, luminosité) sur frame_bgr."""
        result = frame_bgr.copy()
        if self._corr_he:
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
            hsv[:, :, 2] = cv2.equalizeHist(hsv[:, :, 2])
            result = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        if self._corr_dehaze:
            result = self._dehaze(result)
        if self._corr_contrast != 1.0 or self._corr_brightness != 0:
            result = cv2.convertScaleAbs(result,
                                         alpha=self._corr_contrast,
                                         beta=self._corr_brightness)
        return result

    def _dehaze(self, img: np.ndarray) -> np.ndarray:
        """Applique un CLAHE sur le canal L (LAB) pour réduire le voile sous-marin."""
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = clahe.apply(lab[:, :, 0])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        except Exception:
            return img

    def _grab_frame_opencv(self) -> np.ndarray | None:
        """Lit la frame courante via OpenCV (uniquement en pause, pour les corrections)."""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            return None
        cap = cv2.VideoCapture(self.current_video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, self.player.position())
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None

    def _refresh_corrections(self):
        """Applique les corrections à la frame courante (pause uniquement) via OpenCV."""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        if not self._has_active_corrections():
            # Aucune correction active → repasser au rendu hardware
            self.left_display.setCurrentIndex(0)
            return
        frame = self._grab_frame_opencv()
        if frame is None:
            return
        self._last_raw_frame = frame
        corrected = self._apply_corrections(frame)
        h, w = corrected.shape[:2]
        rgb = cv2.cvtColor(corrected, cv2.COLOR_BGR2RGB)
        out_img = QtGui.QImage(rgb.data, w, h, 3 * w,
                               QtGui.QImage.Format.Format_RGB888).copy()
        self.correction_overlay.set_image(out_img)
        self.left_display.setCurrentIndex(1)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        # _VideoLabel gère son propre rescaling via paintEvent — plus besoin d'intercepter Resize
        return super().eventFilter(obj, event)

    def _on_corr_he_toggled(self, checked: bool):
        """Active/désactive l'égalisation d'histogramme et rafraîchit la frame."""
        self._corr_he = checked
        self._refresh_corrections()

    def _on_corr_dehaze_toggled(self, checked: bool):
        """Active/désactive le débrumage et rafraîchit la frame."""
        self._corr_dehaze = checked
        self._refresh_corrections()

    def _on_contrast_changed(self, value: int):
        """Met à jour le facteur de contraste et rafraîchit la frame."""
        self._corr_contrast = value / 100.0
        self.lbl_contrast_val.setText(f"{self._corr_contrast:.1f}×")
        self._refresh_corrections()

    def _on_brightness_changed(self, value: int):
        """Met à jour l'offset de luminosité et rafraîchit la frame."""
        self._corr_brightness = value
        self.lbl_brightness_val.setText(str(value))
        self._refresh_corrections()

    def _reset_corrections(self):
        """Réinitialise toutes les corrections (HE, dehaze, contraste, luminosité) à leurs valeurs par défaut."""
        for w in [self.btn_corr_he, self.btn_corr_dehaze,
                  self.slider_contrast, self.slider_brightness]:
            w.blockSignals(True)
        self.btn_corr_he.setChecked(False)
        self.btn_corr_dehaze.setChecked(False)
        self.slider_contrast.setValue(100)
        self.slider_brightness.setValue(0)
        for w in [self.btn_corr_he, self.btn_corr_dehaze,
                  self.slider_contrast, self.slider_brightness]:
            w.blockSignals(False)
        self._corr_he = False
        self._corr_dehaze = False
        self._corr_contrast = 1.0
        self._corr_brightness = 0
        self.lbl_contrast_val.setText("1.0×")
        self.lbl_brightness_val.setText("0")
        self._refresh_corrections()

    def _update_corrections_enabled(self, is_playing: bool):
        """Active/grise les contrôles de correction selon l'état de lecture."""
        enabled = not is_playing
        for w in [self.btn_corr_he, self.btn_corr_dehaze,
                  self.slider_contrast, self.slider_brightness, self.btn_reset_corr]:
            w.setEnabled(enabled)
        self.lbl_pause_hint.setVisible(is_playing)

    # ── Playback control ──────────────────────────────────────────────────

    def hideEvent(self, event: QtGui.QHideEvent):
        """Pause automatiquement quand la page est masquée (changement de page)."""
        super().hideEvent(event)
        self.pause_all()

    def pause(self):
        """Met en pause le flux principal."""
        self.player.pause()

    def _on_playback_state_changed(self, state):
        """Met à jour l'état des corrections et émet playback_state_changed lors d'un changement d'état."""
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        if is_playing:
            # Reprendre la lecture : repasser au rendu hardware, purger la frame brute
            self.left_display.setCurrentIndex(0)
            self._last_raw_frame = None
            if self.apply_histogram or self.apply_dehaze:
                self.apply_histogram = False
                self.apply_dehaze = False
        self._update_corrections_enabled(is_playing)
        self.playback_state_changed.emit(is_playing)

    def apply_filter(self, correction_type: str):
        """Active une correction HR ou DEHAZE (API de compatibilité legacy)."""
        if correction_type == "HR":
            self.apply_histogram = True
            self.apply_dehaze = False
        elif correction_type == "DEHAZE":
            self.apply_dehaze = True
            self.apply_histogram = False
        self._force_frame_refresh()

    def apply_fixed_correction(self, correction_type: str):
        """Met en pause puis applique une correction (API legacy)."""
        self.pause()
        self.apply_filter(correction_type)

    def remove_filters(self):
        """Désactive toutes les corrections legacy et rafraîchit la frame."""
        if self.apply_histogram or self.apply_dehaze:
            self.apply_histogram = False
            self.apply_dehaze = False
            self._force_frame_refresh()

    def _force_frame_refresh(self):
        """Force le décodage d'une nouvelle frame en déplaçant la position d'un ms."""
        pos = self.player.position()
        if pos > 0:
            self.player.setPosition(pos - 1)
            self.player.setPosition(pos)

    def on_zoom_changed(self, value):
        """Applique le niveau de zoom du slider à la timeline."""
        self.timeline.set_zoom(float(value))

    def on_timeline_zoom_changed(self, zoom_factor: float):
        """Synchronise le slider de zoom quand la timeline change son facteur de zoom."""
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(int(round(zoom_factor)))
        self.slider_zoom.blockSignals(False)

    def jump_time_offset(self, ms: int):
        """Déplace la position de lecture de ms millisecondes (positif ou négatif)."""
        target = max(0, min(self.player.position() + ms, self.player.duration()))
        self.player.setPosition(target)
        if self.is_stereo:
            self.player_R.setPosition(target)

    def on_timeline_pressed(self, target_ms: int):
        """Met le lecteur en pause au début du drag timeline et se positionne sur target_ms."""
        if self.timeline.is_dragging and not self.slider_was_playing:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.slider_was_playing = True
                self.player.pause()
        self.player.setPosition(target_ms)
        self.center_scroll_on_cursor()
        # Synchroniser le curseur de télémétrie pendant le drag (positionChanged peut être différé)
        if self.current_video_path and hasattr(self, 'telemetry_dialog') and self.telemetry_dialog.isVisible():
            self.telemetry_dialog.update_cursor(target_ms / 1000.0)

    def on_timeline_released(self, target_ms: int):
        """Reprend la lecture si elle était active avant le drag timeline."""
        self.player.setPosition(target_ms)
        if self.slider_was_playing:
            self.player.play()
            self.slider_was_playing = False
        self.center_scroll_on_cursor()

    def on_player_position_changed(self, position_ms: int):
        """Synchronise le flux R, la timeline, le curseur télémétrie et les labels de temps."""
        if self.is_stereo and abs(self.player_R.position() - position_ms) > 50:
            self.player_R.setPosition(position_ms)

        # Throttler les mises à jour UI à ~15 fps pendant la lecture (positionChanged fire à la cadence native)
        now_ms = int(time.monotonic() * 1000)
        is_playing = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        if is_playing and (now_ms - self._last_ui_update_ms) < 66:
            return
        self._last_ui_update_ms = now_ms

        if (self.current_video_path
                and hasattr(self, 'telemetry_dialog')
                and self.telemetry_dialog.isVisible()):
            self.telemetry_dialog.update_cursor(position_ms / 1000.0)

        if not self.timeline.is_dragging:
            self.timeline.set_current_position(position_ms)
            self.center_scroll_on_cursor()

        self.update_top_time_label(position_ms, self.player.duration())
        self.update_frame_label(position_ms)

    def center_scroll_on_cursor(self):
        """Fait défiler la timeline pour garder le curseur de lecture visible au centre."""
        if self.player.duration() <= 0 or self.slider_zoom.value() == 1:
            return
        ratio = self.player.position() / self.player.duration()
        cursor_x = int(ratio * self.timeline.width())
        scrollbar = self.scroll_area_timeline.horizontalScrollBar()
        scrollbar.setValue(cursor_x - (self.scroll_area_timeline.width() // 2))

    def on_player_duration_changed(self, duration_ms: int):
        """Propage la durée totale à la timeline et rafraîchit les labels."""
        self.timeline.set_total_duration(duration_ms)
        self.update_top_time_label(self.player.position(), duration_ms)
        self.update_frame_label(self.player.position())

    def update_top_time_label(self, position_ms: int, duration_ms: int):
        """Met à jour le label de temps position/durée au format MM:SS."""
        self.lbl_top_time.setText(
            f"{self.timeline._format_ms(position_ms)} / {self.timeline._format_ms(duration_ms)}"
        )

    def update_frame_label(self, position_ms: int):
        """Met à jour le label de numéro de frame courant."""
        if self.video_fps and self.video_fps > 0:
            self.lbl_frame_number.setText(
                f"Frame: {int(position_ms * self.video_fps / 1000.0) + 1}")
        else:
            self.lbl_frame_number.setText("Frame: -")

    def _get_video_fps(self, video_path: str) -> float:
        """Lit le FPS de video_path via OpenCV, retourne 0.0 en cas d'échec."""
        if not video_path or not os.path.exists(video_path):
            return 0.0
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        try:
            return float(fps) if fps > 0 else 0.0
        except Exception:
            return 0.0

    def load_video_and_events(self, video_data, events: list, is_stereo: bool = False):
        """Charge une vidéo (mono ou stéréo), configure la timeline et démarre la lecture."""
        self.player.stop()
        self.player_R.stop()
        self.is_stereo = is_stereo
        self.slider_was_playing = False
        self._last_raw_frame = None
        self.timeline.events = events
        self.slider_zoom.setValue(1)
        self.timeline.set_zoom(1.0)

        has_video = False

        if is_stereo and isinstance(video_data, list) and len(video_data) >= 2:
            path_l, path_r = video_data[0], video_data[1]
            if os.path.exists(path_l) and os.path.exists(path_r):
                self.left_display.setVisible(True)
                self.video_widget_R.setVisible(True)
                self.video_fps = self._get_video_fps(path_l)
                self.current_video_path = path_l
                self.player.setSource(QtCore.QUrl.fromLocalFile(path_l))
                self.player_R.setSource(QtCore.QUrl.fromLocalFile(path_r))
                has_video = True
            # Reset cam toggles
            for btn in [self.btn_cam_L, self.btn_cam_R]:
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
            for w in [self._sep_cam, self.btn_cam_L, self.btn_cam_R]:
                w.setVisible(True)
        else:
            self.is_stereo = False
            self.left_display.setVisible(True)
            self.video_widget_R.setVisible(False)
            for w in [self._sep_cam, self.btn_cam_L, self.btn_cam_R]:
                w.setVisible(False)
            path = video_data[0] if isinstance(video_data, list) else video_data
            if path and os.path.exists(path):
                self.video_fps = self._get_video_fps(path)
                self.current_video_path = path
                self.player.setSource(QtCore.QUrl.fromLocalFile(path))
                has_video = True

        self.display_stack.setCurrentIndex(1 if has_video else 0)
        if has_video:
            self.play_all()

        self.timeline.update()

    def _on_cam_L_toggled(self, checked: bool):
        """Masque/affiche la caméra gauche tout en garantissant qu'au moins une caméra reste visible."""
        if not checked and not self.btn_cam_R.isChecked():
            self.btn_cam_L.blockSignals(True)
            self.btn_cam_L.setChecked(True)
            self.btn_cam_L.blockSignals(False)
            return
        self.left_display.setVisible(checked)

    def _on_cam_R_toggled(self, checked: bool):
        """Masque/affiche la caméra droite tout en garantissant qu'au moins une caméra reste visible."""
        if not checked and not self.btn_cam_L.isChecked():
            self.btn_cam_R.blockSignals(True)
            self.btn_cam_R.setChecked(True)
            self.btn_cam_R.blockSignals(False)
            return
        self.video_widget_R.setVisible(checked)

    def release_video_file(self, path: str):
        """Stop and clear source if this player holds a file from the same directory as path."""
        if not self.current_video_path:
            return
        if os.path.normpath(os.path.dirname(path)) == os.path.normpath(
                os.path.dirname(self.current_video_path)):
            self.player.stop()
            self.player_R.stop()
            self.player.setSource(QtCore.QUrl())
            self.player_R.setSource(QtCore.QUrl())
            self.current_video_path = None
            self.display_stack.setCurrentIndex(0)

    def load_dynamic_metadata(self, csv_path: str):
        """Charge le CSV de télémétrie et ouvre le dialogue TelemetryDialog."""
        try:
            df = pd.read_csv(csv_path, sep=None, engine='python')
            df.columns = df.columns.str.strip()
            col_delta = next((c for c in df.columns if 'Delta' in c), None)
            if col_delta:
                df.rename(columns={col_delta: 'Delta'}, inplace=True)
                if df['Delta'].dtype == object:
                    df['Delta'] = df['Delta'].str.replace(',', '.').astype(float)
                self.df_telemetry = df
                self.telemetry_dialog.update_data(df)
                self.telemetry_dialog.show()
        except Exception as e:
            print(f"Erreur chargement télémétrie : {e}")

    def play_all(self):
        """Lance la lecture sur le flux L et (en stéréo) le flux R."""
        self.player.play()
        if self.is_stereo:
            self.player_R.play()

    def pause_all(self):
        """Met en pause le flux L et (en stéréo) le flux R."""
        self.player.pause()
        if self.is_stereo:
            self.player_R.pause()

    def set_playback_rate_all(self, rate: float):
        """Applique une vitesse de lecture sur les deux flux."""
        self.player.setPlaybackRate(rate)
        if self.is_stereo:
            self.player_R.setPlaybackRate(rate)
