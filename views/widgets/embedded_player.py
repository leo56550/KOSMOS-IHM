import os
import time
import cv2
import numpy as np
import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QVideoFrame

from views.widgets.timeline_widget import VideoTimeline
from views.dialogs.telemetry_dialog import TelemetryDialog

_SLIDER_STYLE = """
    QSlider::groove:horizontal { height: 4px; background: #333; border-radius: 2px; }
    QSlider::handle:horizontal { background: #2778a2; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
"""
_BTN_STYLE = """
    QPushButton {
        background-color: #20415d; color: white; font-weight: bold;
        border: 1px solid #2778a2; border-radius: 4px; padding: 6px 12px; min-width: 50px;
    }
    QPushButton:hover { background-color: #2778a2; }
    QPushButton:pressed { background-color: #152d42; }
"""
_TOGGLE_STYLE = """
    QPushButton {
        background-color: #20415d; color: white; font-weight: bold;
        border: 1px solid #444; border-radius: 4px; padding: 4px 10px;
    }
    QPushButton:checked { background-color: #1c6a9e; border-color: #2778a2; }
    QPushButton:hover:!disabled { background-color: #2778a2; }
    QPushButton:disabled { color: #555; background-color: #1a1a1a; border-color: #333; }
"""


class EmbeddedVideoPlayer(QtWidgets.QWidget):

    playback_state_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None, zone_definitions=None):
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

        # Performance: throttle rendering to ~30fps display
        self._last_render_ms: int = 0
        # Telemetry overlay cache: recomputed every 200 ms of video time
        self._telemetry_cache: tuple[str, int] = ("No Data", -9999)

        # Stored pixmaps for resize-aware rescaling
        self._last_pixmap_L: QtGui.QPixmap | None = None
        self._last_pixmap_R: QtGui.QPixmap | None = None

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

        self.video_widget = QtWidgets.QLabel()
        self.video_widget.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.video_widget.setStyleSheet("background-color: black;")

        self.video_widget_R = QtWidgets.QLabel()
        self.video_widget_R.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.video_widget_R.setStyleSheet("background-color: black;")
        self.video_widget_R.setVisible(False)

        self.video_widget.installEventFilter(self)
        self.video_widget_R.installEventFilter(self)

        vc_layout.addWidget(self.video_widget)
        vc_layout.addWidget(self.video_widget_R)
        self.display_stack.addWidget(self.video_container)

        self.video_sink = QVideoSink()
        self.player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self.process_realtime_frame)

        self.video_sink_R = QVideoSink()
        self.player_R.setVideoSink(self.video_sink_R)
        self.video_sink_R.videoFrameChanged.connect(self.process_realtime_frame_R)

        # Time bar
        self.time_layout = QtWidgets.QHBoxLayout()
        self.time_layout.setContentsMargins(10, 4, 10, 4)

        self.lbl_top_time = QtWidgets.QLabel("00:00 / 00:00")
        self.lbl_top_time.setStyleSheet(
            "color: #2778a2; font-weight: bold; font-size: 14px; border: none;")
        self.time_layout.addWidget(self.lbl_top_time)

        self.lbl_frame_number = QtWidgets.QLabel("Frame: -")
        self.lbl_frame_number.setStyleSheet(
            "color: white; font-size: 13px; margin-left: 12px; border: none;")
        self.time_layout.addWidget(self.lbl_frame_number)
        self.time_layout.addStretch()

        self.lbl_zoom = QtWidgets.QLabel("")
        self.lbl_zoom.setStyleSheet("color: white; font-size: 11px; margin-right: 5px;")
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

        # ── Corrections panel ─────────────────────────────────────────────
        self.corrections_panel = QtWidgets.QFrame()
        self.corrections_panel.setStyleSheet(
            "QFrame { background-color: #111111; border-top: 1px solid #2778a2; }")
        corr_layout = QtWidgets.QHBoxLayout(self.corrections_panel)
        corr_layout.setContentsMargins(8, 5, 8, 5)
        corr_layout.setSpacing(10)

        _lbl = lambda t: self._make_corr_label(t)

        title_lbl = QtWidgets.QLabel("Corrections :")
        title_lbl.setStyleSheet(
            "color: #2778a2; font-size: 11px; font-weight: bold; border: none;")
        corr_layout.addWidget(title_lbl)

        self.btn_corr_he = QtWidgets.QPushButton("HR")
        self.btn_corr_he.setCheckable(True)
        self.btn_corr_he.setStyleSheet(_TOGGLE_STYLE)
        self.btn_corr_he.setToolTip("Égalisation d'histogramme (améliore le contraste global)")
        self.btn_corr_he.toggled.connect(self._on_corr_he_toggled)

        self.btn_corr_dehaze = QtWidgets.QPushButton("Dehaze")
        self.btn_corr_dehaze.setCheckable(True)
        self.btn_corr_dehaze.setStyleSheet(_TOGGLE_STYLE)
        self.btn_corr_dehaze.setToolTip("Réduction de voile (CLAHE sur canal L)")
        self.btn_corr_dehaze.toggled.connect(self._on_corr_dehaze_toggled)

        sep1 = self._vline()

        lbl_contrast = self._make_corr_label("Contraste :")
        self.slider_contrast = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(50, 250)
        self.slider_contrast.setValue(100)
        self.slider_contrast.setFixedWidth(90)
        self.slider_contrast.setStyleSheet(_SLIDER_STYLE)
        self.lbl_contrast_val = self._make_corr_label("1.0×", min_w=32)
        self.slider_contrast.valueChanged.connect(self._on_contrast_changed)

        sep2 = self._vline()

        lbl_brightness = self._make_corr_label("Luminosité :")
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
        self.btn_reset_corr.setToolTip("Réinitialiser toutes les corrections")
        self.btn_reset_corr.clicked.connect(self._reset_corrections)

        self.lbl_pause_hint = QtWidgets.QLabel("⏸ pause pour activer")
        self.lbl_pause_hint.setStyleSheet("color: #666; font-size: 10px; border: none;")

        for w in [self.btn_corr_he, self.btn_corr_dehaze, sep1,
                  lbl_contrast, self.slider_contrast, self.lbl_contrast_val,
                  sep2, lbl_brightness, self.slider_brightness, self.lbl_brightness_val,
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
        lbl = QtWidgets.QLabel(text)
        style = "color: #aaaaaa; font-size: 11px; border: none;"
        if min_w:
            style += f" min-width: {min_w}px;"
        lbl.setStyleSheet(style)
        return lbl

    @staticmethod
    def _vline() -> QtWidgets.QFrame:
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setStyleSheet("color: #333;")
        return sep

    # ── Language ──────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        self.current_language = language
        self.lbl_zoom.setText(self.translate("Zoom :", "Zoom:"))
        self.btn_start.setToolTip(self.translate("LIRE", "PLAY"))
        self.btn_stop.setToolTip(self.translate("PAUSE", "PAUSE"))
        self.update_top_time_label(self.player.position(), self.player.duration())
        self.update_frame_label(self.player.position())

    # ── Frame rendering ───────────────────────────────────────────────────

    def process_realtime_frame(self, frame: QVideoFrame):
        self._render_dual_view(frame, self.video_widget, with_overlay=True)

    def process_realtime_frame_R(self, frame: QVideoFrame):
        if self.is_stereo:
            self._render_dual_view(frame, self.video_widget_R, with_overlay=False)

    def _render_dual_view(self, frame: QVideoFrame,
                          target_label: QtWidgets.QLabel, with_overlay: bool = False):
        if not frame.isValid():
            return

        is_paused = (self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState)

        # Throttle to ~30 fps display when playing — avoids overloading the main thread
        now_ms = int(time.monotonic() * 1000)
        if not is_paused and (now_ms - self._last_render_ms) < 33:
            return

        if not frame.map(QVideoFrame.MapMode.ReadOnly):
            return

        try:
            q_img = frame.toImage().convertToFormat(QtGui.QImage.Format.Format_RGB888)
            if q_img.isNull() or q_img.width() == 0 or q_img.height() == 0:
                return

            width, height = q_img.width(), q_img.height()
            ptr = q_img.bits()
            ptr.setsize(q_img.sizeInBytes())
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 3))
            frame_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

            # Store raw frame the moment we pause (main stream only)
            if is_paused and with_overlay:
                self._last_raw_frame = frame_bgr.copy()

            # Apply corrections only when paused
            display_frame = (self._apply_corrections(frame_bgr)
                             if is_paused and self._has_active_corrections()
                             else frame_bgr)

            if with_overlay:
                self._draw_telemetry_overlay(display_frame, width, height)

            self._last_render_ms = now_ms

            frame_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            out_img = QtGui.QImage(frame_rgb.data, width, height, 3 * width,
                                   QtGui.QImage.Format.Format_RGB888).copy()
            pix = QtGui.QPixmap.fromImage(out_img)
            if target_label is self.video_widget:
                self._last_pixmap_L = pix
            elif target_label is self.video_widget_R:
                self._last_pixmap_R = pix
            target_label.setPixmap(
                pix.scaled(target_label.size(),
                           QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                           QtCore.Qt.TransformationMode.SmoothTransformation))
        finally:
            frame.unmap()

    def _draw_telemetry_overlay(self, frame_bgr: np.ndarray, width: int, height: int):
        pos_ms = self.player.position()
        # Recompute overlay text at most every 200 ms of video time
        if abs(pos_ms - self._telemetry_cache[1]) > 200:
            overlay_text = "No Data"
            if (hasattr(self, 'df_telemetry')
                    and self.df_telemetry is not None
                    and not self.df_telemetry.empty
                    and 'Delta' in self.df_telemetry.columns):
                try:
                    current_s = pos_ms / 1000.0
                    diffs = (self.df_telemetry['Delta'] - current_s).abs()
                    idx = diffs.idxmin()
                    if diffs[idx] < 1.0:
                        row = self.df_telemetry.iloc[idx]
                        overlay_text = (
                            f"T: {row.get('température', 'N/A')}C | "
                            f"P: {row.get('pression', 'N/A')}hPa | "
                            f"Exp: {row.get('ExpTime', 'N/A')}ms | "
                            f"Lux: {row.get('Lux', 'N/A')}"
                        )
                    else:
                        overlay_text = "Out of Sync"
                except Exception:
                    overlay_text = "Sync Error"
            self._telemetry_cache = (overlay_text, pos_ms)

        overlay_text = self._telemetry_cache[0]
        overlay = frame_bgr.copy()
        cv2.rectangle(overlay, (5, height - 50), (width - 5, height - 5), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame_bgr, 0.4, 0, frame_bgr)
        cv2.putText(frame_bgr, overlay_text, (20, height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame_bgr, f"Time: {pos_ms / 1000.0:.2f}s", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    # ── Image corrections ─────────────────────────────────────────────────

    def _has_active_corrections(self) -> bool:
        return (self._corr_he or self._corr_dehaze
                or self._corr_contrast != 1.0 or self._corr_brightness != 0)

    def _apply_corrections(self, frame_bgr: np.ndarray) -> np.ndarray:
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
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = clahe.apply(lab[:, :, 0])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        except Exception:
            return img

    def _refresh_corrections(self):
        """Re-render the stored raw frame with current correction settings."""
        if (self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
                and self._last_raw_frame is not None):
            corrected = self._apply_corrections(self._last_raw_frame)
            h, w = corrected.shape[:2]
            rgb = cv2.cvtColor(corrected, cv2.COLOR_BGR2RGB)
            out_img = QtGui.QImage(rgb.data, w, h, 3 * w,
                                   QtGui.QImage.Format.Format_RGB888).copy()
            pix = QtGui.QPixmap.fromImage(out_img)
            self._last_pixmap_L = pix
            self.video_widget.setPixmap(
                pix.scaled(self.video_widget.size(),
                           QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                           QtCore.Qt.TransformationMode.SmoothTransformation))

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Resize:
            if obj is self.video_widget and self._last_pixmap_L is not None:
                obj.setPixmap(
                    self._last_pixmap_L.scaled(
                        obj.size(),
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation))
            elif obj is self.video_widget_R and self._last_pixmap_R is not None:
                obj.setPixmap(
                    self._last_pixmap_R.scaled(
                        obj.size(),
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation))
        return super().eventFilter(obj, event)

    def _on_corr_he_toggled(self, checked: bool):
        self._corr_he = checked
        self._refresh_corrections()

    def _on_corr_dehaze_toggled(self, checked: bool):
        self._corr_dehaze = checked
        self._refresh_corrections()

    def _on_contrast_changed(self, value: int):
        self._corr_contrast = value / 100.0
        self.lbl_contrast_val.setText(f"{self._corr_contrast:.1f}×")
        self._refresh_corrections()

    def _on_brightness_changed(self, value: int):
        self._corr_brightness = value
        self.lbl_brightness_val.setText(str(value))
        self._refresh_corrections()

    def _reset_corrections(self):
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
        enabled = not is_playing
        for w in [self.btn_corr_he, self.btn_corr_dehaze,
                  self.slider_contrast, self.slider_brightness, self.btn_reset_corr]:
            w.setEnabled(enabled)
        self.lbl_pause_hint.setVisible(is_playing)

    # ── Playback control ──────────────────────────────────────────────────

    def pause(self):
        self.player.pause()

    def _on_playback_state_changed(self, state):
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        if is_playing and (self.apply_histogram or self.apply_dehaze):
            self.apply_histogram = False
            self.apply_dehaze = False
        self._update_corrections_enabled(is_playing)
        self.playback_state_changed.emit(is_playing)

    def apply_filter(self, correction_type: str):
        if correction_type == "HR":
            self.apply_histogram = True
            self.apply_dehaze = False
        elif correction_type == "DEHAZE":
            self.apply_dehaze = True
            self.apply_histogram = False
        self._force_frame_refresh()

    def apply_fixed_correction(self, correction_type: str):
        self.pause()
        self.apply_filter(correction_type)

    def remove_filters(self):
        if self.apply_histogram or self.apply_dehaze:
            self.apply_histogram = False
            self.apply_dehaze = False
            self._force_frame_refresh()

    def _force_frame_refresh(self):
        pos = self.player.position()
        if pos > 0:
            self.player.setPosition(pos - 1)
            self.player.setPosition(pos)

    def on_zoom_changed(self, value):
        self.timeline.set_zoom(float(value))

    def on_timeline_zoom_changed(self, zoom_factor: float):
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(int(round(zoom_factor)))
        self.slider_zoom.blockSignals(False)

    def jump_time_offset(self, ms: int):
        target = max(0, min(self.player.position() + ms, self.player.duration()))
        self.player.setPosition(target)
        if self.is_stereo:
            self.player_R.setPosition(target)

    def on_timeline_pressed(self, target_ms: int):
        if self.timeline.is_dragging and not self.slider_was_playing:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.slider_was_playing = True
                self.player.pause()
        self.player.setPosition(target_ms)
        self.center_scroll_on_cursor()

    def on_timeline_released(self, target_ms: int):
        self.player.setPosition(target_ms)
        if self.slider_was_playing:
            self.player.play()
            self.slider_was_playing = False
        self.center_scroll_on_cursor()

    def on_player_position_changed(self, position_ms: int):
        if self.is_stereo and abs(self.player_R.position() - position_ms) > 50:
            self.player_R.setPosition(position_ms)

        if hasattr(self, 'telemetry_dialog') and self.telemetry_dialog.isVisible():
            self.telemetry_dialog.update_cursor(position_ms / 1000.0)

        if not self.timeline.is_dragging:
            self.timeline.set_current_position(position_ms)
            self.center_scroll_on_cursor()

        self.update_top_time_label(position_ms, self.player.duration())
        self.update_frame_label(position_ms)

    def center_scroll_on_cursor(self):
        if self.player.duration() <= 0 or self.slider_zoom.value() == 1:
            return
        ratio = self.player.position() / self.player.duration()
        cursor_x = int(ratio * self.timeline.width())
        scrollbar = self.scroll_area_timeline.horizontalScrollBar()
        scrollbar.setValue(cursor_x - (self.scroll_area_timeline.width() // 2))

    def on_player_duration_changed(self, duration_ms: int):
        self.timeline.set_total_duration(duration_ms)
        self.update_top_time_label(self.player.position(), duration_ms)
        self.update_frame_label(self.player.position())

    def update_top_time_label(self, position_ms: int, duration_ms: int):
        self.lbl_top_time.setText(
            f"{self.timeline._format_ms(position_ms)} / {self.timeline._format_ms(duration_ms)}"
        )

    def update_frame_label(self, position_ms: int):
        if self.video_fps and self.video_fps > 0:
            self.lbl_frame_number.setText(
                f"Frame: {int(position_ms * self.video_fps / 1000.0) + 1}")
        else:
            self.lbl_frame_number.setText("Frame: -")

    def _get_video_fps(self, video_path: str) -> float:
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
        self.player.stop()
        self.player_R.stop()
        self.is_stereo = is_stereo
        self.slider_was_playing = False
        self._last_raw_frame = None
        self._telemetry_cache = ("No Data", -9999)
        self.timeline.events = events
        self.slider_zoom.setValue(1)
        self.timeline.set_zoom(1.0)

        has_video = False

        if is_stereo and isinstance(video_data, list) and len(video_data) >= 2:
            path_l, path_r = video_data[0], video_data[1]
            if os.path.exists(path_l) and os.path.exists(path_r):
                self.video_widget_R.setVisible(True)
                self.video_fps = self._get_video_fps(path_l)
                self.current_video_path = path_l
                self.player.setSource(QtCore.QUrl.fromLocalFile(path_l))
                self.player_R.setSource(QtCore.QUrl.fromLocalFile(path_r))
                has_video = True
        else:
            self.is_stereo = False
            self.video_widget_R.setVisible(False)
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

    def load_dynamic_metadata(self, csv_path: str):
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
        self.player.play()
        if self.is_stereo:
            self.player_R.play()

    def pause_all(self):
        self.player.pause()
        if self.is_stereo:
            self.player_R.pause()

    def set_playback_rate_all(self, rate: float):
        self.player.setPlaybackRate(rate)
        if self.is_stereo:
            self.player_R.setPlaybackRate(rate)
