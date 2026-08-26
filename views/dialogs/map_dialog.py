from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWebEngineWidgets import QWebEngineView


class MapBridge(QtCore.QObject):
    """Pont JS↔Python pour recevoir les clics et déplacements de marqueur sur la carte Folium."""

    videoSelected = QtCore.pyqtSignal(str)
    markerMoved = QtCore.pyqtSignal(str, float, float)

    @QtCore.pyqtSlot(str)
    def select_video(self, video_name: str):
        print(f"-> [BRIDGE] Clic carte reçu pour : {video_name}")
        self.videoSelected.emit(video_name)

    @QtCore.pyqtSlot(str, float, float)
    def update_coords(self, video_name: str, lat: float, lon: float):
        print(f"-> [BRIDGE] Marqueur déplacé pour {video_name} : ({lat}, {lon})")
        self.markerMoved.emit(video_name, lat, lon)


class MapDialog(QtWidgets.QDialog):
    """Dialogue affichant la carte de campagne dans un QWebEngineView."""

    def __init__(self, bridge: MapBridge, channel, parent=None, language: str = 'fr'):
        super().__init__(parent)
        self.current_language = language
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.setWindowTitle("Carte de Campagne" if language == 'fr' else "Campaign Map")
        self.resize(800, 600)

        self.bridge = bridge
        self.channel = channel

        self.map_view = QWebEngineView(self)
        self.map_view.page().setWebChannel(self.channel)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_view)

    def set_language(self, language: str):
        self.current_language = language
        self.setWindowTitle("Carte de Campagne" if language == 'fr' else "Campaign Map")
