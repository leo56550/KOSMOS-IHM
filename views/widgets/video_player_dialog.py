import os
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from views.widgets.timeline_widget import VideoTimeline


class VideoPlayerWindow(QtWidgets.QDialog):
    """Fenêtre de lecture vidéo détachable avec timeline intégrée (mono ou stéréo)."""

    def __init__(self, video_data, events_data, parent=None):
        """
        Args:
            video_data: str (mono) ou list [path_L, path_R] (stéréo).
            events_data: Structure d'événements pour la timeline.
        """
        super().__init__(parent)

        self.is_stereo = isinstance(video_data, list) and len(video_data) >= 2
        path_l = video_data[0] if self.is_stereo else video_data

        self.setWindowTitle(f"Player {'[STEREO]' if self.is_stereo else ''} - {os.path.basename(path_l)}")
        self.resize(1200, 700) if self.is_stereo else self.resize(900, 600)
        self.setStyleSheet("background-color: #1e1e1e; color: white;")

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.player_R = QMediaPlayer()
        self.audio_output_R = QAudioOutput()
        self.player_R.setAudioOutput(self.audio_output_R)
        self.audio_output_R.setMuted(True)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        self.video_container = QtWidgets.QHBoxLayout()

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.player.setVideoOutput(self.video_widget)
        self.video_container.addWidget(self.video_widget)

        self.video_widget_R = QVideoWidget()
        self.video_widget_R.setStyleSheet("background-color: black;")
        self.player_R.setVideoOutput(self.video_widget_R)
        self.video_container.addWidget(self.video_widget_R)
        self.video_widget_R.setVisible(self.is_stereo)

        main_layout.addLayout(self.video_container, stretch=4)

        self.timeline = VideoTimeline(events_data, parent=self)
        main_layout.addWidget(self.timeline, stretch=0)

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setSpacing(5)

        blue_button_style = """
            QPushButton {
                background-color: #20415d; color: white; font-weight: bold;
                border: 1px solid #2778a2; border-radius: 4px; padding: 5px 10px; min-width: 45px;
            }
            QPushButton:hover { background-color: #2778a2; }
            QPushButton:pressed { background-color: #152d42; }
        """

        system_style = QtWidgets.QApplication.style()

        self.btn_start = QtWidgets.QPushButton()
        self.btn_start.setIcon(system_style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_stop = QtWidgets.QPushButton()
        self.btn_stop.setIcon(system_style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPause))
        self.btn_m10 = QtWidgets.QPushButton("-10s")
        self.btn_p10 = QtWidgets.QPushButton("+10s")
        self.btn_x1 = QtWidgets.QPushButton("x1")
        self.btn_x2 = QtWidgets.QPushButton("x2")
        self.btn_x5 = QtWidgets.QPushButton("x5")

        for btn in [self.btn_start, self.btn_stop, self.btn_m10, self.btn_p10,
                    self.btn_x1, self.btn_x2, self.btn_x5]:
            btn.setStyleSheet(blue_button_style)
            buttons_layout.addWidget(btn)

        main_layout.addLayout(buttons_layout, stretch=0)

        self.btn_start.clicked.connect(self.play_all)
        self.btn_stop.clicked.connect(self.pause_all)
        self.btn_m10.clicked.connect(lambda: self.skip_time(-10000))
        self.btn_p10.clicked.connect(lambda: self.skip_time(10000))
        self.btn_x1.clicked.connect(lambda: self.set_rate(1.0))
        self.btn_x2.clicked.connect(lambda: self.set_rate(2.0))
        self.btn_x5.clicked.connect(lambda: self.set_rate(5.0))

        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.timeline.timeChanged.connect(self.set_position)

        self.player.setSource(QtCore.QUrl.fromLocalFile(path_l))
        if self.is_stereo:
            self.player_R.setSource(QtCore.QUrl.fromLocalFile(video_data[1]))

    def play_all(self):
        """Lance la lecture sur les deux flux (L et R en stéréo)."""
        self.player.play()
        if self.is_stereo:
            self.player_R.play()

    def pause_all(self):
        """Met en pause les deux flux."""
        self.player.pause()
        if self.is_stereo:
            self.player_R.pause()

    def set_rate(self, rate: float):
        """Applique une vitesse de lecture sur les deux flux."""
        self.player.setPlaybackRate(rate)
        if self.is_stereo:
            self.player_R.setPlaybackRate(rate)

    def skip_time(self, ms: int):
        """Avance ou recule de ms millisecondes."""
        self.set_position(self.player.position() + ms)

    def on_position_changed(self, position: int):
        """Synchronise la timeline et le flux R à la position du flux L."""
        self.timeline.set_current_position(position)
        if self.is_stereo and abs(self.player.position() - self.player_R.position()) > 100:
            self.player_R.setPosition(position)

    def on_duration_changed(self, duration: int):
        """Propage la durée totale à la timeline."""
        self.timeline.set_total_duration(duration)

    def set_position(self, position: int):
        """Positionne les deux lecteurs en ms, clampé dans [0, durée]."""
        target = max(0, min(position, self.player.duration()))
        self.player.setPosition(target)
        if self.is_stereo:
            self.player_R.setPosition(target)

    def release_files(self):
        """Stoppe les lecteurs et libère les handles fichiers (nécessaire sur Windows
        avant tout shutil.move/rmtree sur le dossier de la vidéo)."""
        self.player.stop()
        self.player_R.stop()
        self.player.setSource(QtCore.QUrl())
        self.player_R.setSource(QtCore.QUrl())

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Libère les fichiers avant la fermeture de la fenêtre."""
        self.release_files()
        event.accept()
