from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWebEngineWidgets import QWebEngineView


class MapBridge(QtCore.QObject):
    """Pont JS↔Python pour recevoir les clics sur la carte Folium."""

    videoSelected = QtCore.pyqtSignal(str)

    @QtCore.pyqtSlot(str)
    def select_video(self, video_name: str):
        print(f"-> [BRIDGE] Clic carte reçu pour : {video_name}")
        self.videoSelected.emit(video_name)


class MapDialog(QtWidgets.QDialog):
    """Dialogue affichant la carte de campagne dans un QWebEngineView."""

    def __init__(self, bridge: MapBridge, channel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Carte de Campagne")
        self.resize(800, 600)

        self.bridge = bridge
        self.channel = channel

        self.map_view = QWebEngineView(self)
        self.map_view.page().setWebChannel(self.channel)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_view)
