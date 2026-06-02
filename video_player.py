import os
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

# Import de la timeline externe pour éviter toute redéfinition parasite
from timeline import VideoTimeline

class VideoPlayerWindow(QtWidgets.QDialog):
    """Fenêtre détachable contenant le lecteur vidéo et sa timeline intégrée."""

    def __init__(self, video_path: str, events_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Lecteur - {os.path.basename(video_path)}")
        self.resize(900, 600)
        self.setStyleSheet("background-color: #1e1e1e; color: white;")
        
        # --- CONFIGURATION DU PLAYER ---
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        # --- INTERFACE VISUELLE ---
        layout_principal = QtWidgets.QVBoxLayout(self)
        layout_principal.setContentsMargins(10, 10, 10, 10)
        layout_principal.setSpacing(5)
        
        # Widget d'affichage vidéo
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        layout_principal.addWidget(self.video_widget, stretch=4) # Priorité d'affichage à la vidéo
        self.player.setVideoOutput(self.video_widget)
        
        # --- INTÉGRATION DE LA TIMELINE HORIZONTALE ---
        self.timeline = VideoTimeline(events_data, parent=self)
        layout_principal.addWidget(self.timeline, stretch=0)
        
        # Zone des boutons de contrôle
        layout_boutons = QtWidgets.QHBoxLayout()
        layout_boutons.setSpacing(5)
        
        style_bouton_bleu = """
            QPushButton { 
                background-color: #20415d; 
                color: white; 
                font-weight: bold; 
                border: 1px solid #2778a2; 
                border-radius: 4px; 
                padding: 5px 10px; 
                min-width: 45px;
            }
            QPushButton:hover { background-color: #2778a2; }
            QPushButton:pressed { background-color: #152d42; }
        """
        
        # Récupération du style de l'application pour charger les icônes système standard
        style_systeme = QtWidgets.QApplication.style()
        
        # Remplacement des textes par les icônes standard adaptées au thème actif
        self.btn_start = QtWidgets.QPushButton()
        self.btn_start.setIcon(style_systeme.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_start.setIconSize(QtCore.QSize(18, 18))
        self.btn_start.setToolTip("Démarrer la lecture")

        self.btn_stop = QtWidgets.QPushButton()
        self.btn_stop.setIcon(style_systeme.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPause))
        self.btn_stop.setIconSize(QtCore.QSize(18, 18))
        self.btn_stop.setToolTip("Mettre en pause")

        self.btn_m10 = QtWidgets.QPushButton("-10s")
        self.btn_p10 = QtWidgets.QPushButton("+10s")
        self.btn_x1 = QtWidgets.QPushButton("x1")
        self.btn_x2 = QtWidgets.QPushButton("x2")
        self.btn_x5 = QtWidgets.QPushButton("x5")
        self.btn_x10 = QtWidgets.QPushButton("x10")
        
        boutons = [self.btn_start, self.btn_stop, self.btn_m10, self.btn_p10, self.btn_x1, self.btn_x2, self.btn_x5, self.btn_x10]
        for btn in boutons:
            btn.setStyleSheet(style_bouton_bleu)
            layout_boutons.addWidget(btn)
            
        layout_principal.addLayout(layout_boutons, stretch=0)
        
        # --- CONNEXIONS DES SIGNAUX ---
        self.btn_start.clicked.connect(self.player.play)
        self.btn_stop.clicked.connect(self.player.pause)
        self.btn_m10.clicked.connect(lambda: self.sauter_de_temps(-10000))
        self.btn_p10.clicked.connect(lambda: self.sauter_de_temps(10000))
        
        self.btn_x1.clicked.connect(lambda: self.player.setPlaybackRate(1.0))
        self.btn_x2.clicked.connect(lambda: self.player.setPlaybackRate(2.0))
        self.btn_x5.clicked.connect(lambda: self.player.setPlaybackRate(5.0))
        self.btn_x10.clicked.connect(lambda: self.player.setPlaybackRate(10.0))
        
        # Synchronisation de la vidéo vers la Timeline
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        
        # Synchronisation de la Timeline (clic utilisateur) vers la Vidéo
        self.timeline.timeChanged.connect(self.set_position)
        
        # Chargement initial de la source vidéo
        self.player.setSource(QtCore.QUrl.fromLocalFile(video_path))

    def sauter_de_temps(self, ms: int):
        nouvelle_position = self.player.position() + ms
        self.player.setPosition(max(0, min(nouvelle_position, self.player.duration())))

    def on_position_changed(self, position):
        self.timeline.set_current_position(position)

    def on_duration_changed(self, duration):
        self.timeline.set_total_duration(duration)

    def set_position(self, position):
        self.player.setPosition(position)

    def closeEvent(self, event):
        self.player.stop()
        event.accept()