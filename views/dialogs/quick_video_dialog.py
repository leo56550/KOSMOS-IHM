import os

from PyQt6 import QtWidgets, QtCore, QtGui

from services.video_service import check_stereo_status
from services.motor_service import get_motor_stable_timestamps
from views.widgets.embedded_player import EmbeddedVideoPlayer


class QuickVideoDialog(QtWidgets.QDialog):
    """Dialog de lecture d'un fichier MP4 standalone, sans campagne ouverte."""

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Lecture — {os.path.basename(video_path)}")
        self.resize(1140, 700)
        self.setStyleSheet("background-color: #111820;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.player = EmbeddedVideoPlayer(parent=self)
        layout.addWidget(self.player)

        is_stereo, video_to_load = check_stereo_status(video_path)

        csv_path = video_path.replace(".mp4", ".csv")
        if os.path.exists(csv_path):
            self.player.load_dynamic_metadata(csv_path)

        motor_events = []
        system_csv = os.path.join(os.path.dirname(video_path), "systemEvent.csv")
        if os.path.exists(system_csv):
            try:
                for entry in get_motor_stable_timestamps(system_csv, delay=6.0):
                    start_ms = int(entry["timestamp"] * 1000)
                    motor_events.append({
                        "start": start_ms, "end": start_ms + 3000,
                        "title": f"Rot #{entry['rotation_index']} ({entry['angle']}°)",
                        "type": entry["type"],
                    })
            except Exception:
                pass

        self.player.load_video_and_events(video_to_load, motor_events, is_stereo=is_stereo)
        QtCore.QTimer.singleShot(0, self.player.setFocus)

    def closeEvent(self, event: QtGui.QCloseEvent):
        if hasattr(self.player, '_exit_fullscreen'):
            self.player._exit_fullscreen()
        super().closeEvent(event)
