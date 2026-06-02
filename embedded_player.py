import os
import cv2
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QVideoFrame
from timeline import VideoTimeline

# On importe les fonctions de traitement de l'image de utils2
import utils2


class EmbeddedVideoPlayer(QtWidgets.QWidget):
    """Le lecteur vidéo encapsulé réutilisable avec traitement temps réel à la volée.

    Param: zone_definitions: list of {label, color} dicts passed to VideoTimeline.
    Si None -> timeline s'affiche sans zones colorées (comportement par défaut).
    """

    # Signal personnalisé pour informer le contrôleur parent de l'état de lecture
    playback_state_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None, zone_definitions=None):
        super().__init__(parent)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.slider_was_playing = False
        self.current_video_path = None
        self.video_fps = 0.0

        # --- VARIABLES DE CONTRÔLE DES FILTRES (Temps Réel) ---
        self.apply_dehaze = False
        self.apply_histogram = False
        self.he_params = {"vB": 3, "vG": 3, "vR": 3}

        # --- LAYOUT PRINCIPAL ---
        layout_principal = QtWidgets.QVBoxLayout(self)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.setSpacing(0)

        # --- ECRAN VIDEO ---
        self.affichage_stack = QtWidgets.QStackedWidget()
        self.affichage_stack.setStyleSheet("background-color: black; border-radius: 6px 6px 0px 0px;")

        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        logo_path = os.path.join(os.path.dirname(__file__), "img", "logo_kosmos.png")
        pixmap = QtGui.QPixmap(logo_path)
        if not pixmap.isNull():
            self.logo_label.setPixmap(pixmap.scaled(400, 400, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo_label.setText("KOSMOS PLAYER")
            self.logo_label.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")

        self.affichage_stack.addWidget(self.logo_label)

        # --- LABEL POUR REÇEVOIR LES IMAGES PROCESSÉES PAR OPENCV ---
        self.video_widget = QtWidgets.QLabel()
        self.video_widget.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.video_widget.setStyleSheet("background-color: black;")
        self.affichage_stack.addWidget(self.video_widget)

        # Création du Sink pour intercepter les frames natives du décodeur
        self.video_sink = QVideoSink()
        self.player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self.traiter_frame_temps_reel)

        # --- BANDEAU TEMPS + ZOOM ---
        self.layout_temps = QtWidgets.QHBoxLayout()
        self.layout_temps.setContentsMargins(10, 4, 10, 4)

        self.lbl_temps_haut = QtWidgets.QLabel("00:00 / 00:00")
        self.lbl_temps_haut.setStyleSheet("color: #2778a2; font-weight: bold; font-size: 14px; border: none;")
        self.layout_temps.addWidget(self.lbl_temps_haut)

        self.lbl_frame_number = QtWidgets.QLabel("Frame: -")
        self.lbl_frame_number.setStyleSheet("color: white; font-size: 13px; margin-left: 12px; border: none;")
        self.layout_temps.addWidget(self.lbl_frame_number)
        self.layout_temps.addStretch()

        self.lbl_zoom = QtWidgets.QLabel("Zoom :")
        self.lbl_zoom.setStyleSheet("color: white; font-size: 11px; margin-right: 5px;")
        self.layout_temps.addWidget(self.lbl_zoom)

        self.slider_zoom = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_zoom.setRange(1, 10)
        self.slider_zoom.setValue(1)
        self.slider_zoom.setFixedWidth(100)
        self.slider_zoom.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #333; border-radius: 2px; }
            QSlider::handle:horizontal { background: #2778a2; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
        """)
        self.layout_temps.addWidget(self.slider_zoom)

        # --- TIMELINE DANS UNE SCROLLAREA ---
        self.scroll_area_timeline = QtWidgets.QScrollArea()
        self.scroll_area_timeline.setWidgetResizable(True)
        self.scroll_area_timeline.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area_timeline.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area_timeline.setStyleSheet("QScrollArea { border: none; background-color: #141414; }")

        self.timeline = VideoTimeline([], parent=self, zone_definitions=zone_definitions)
        self.timeline.setMinimumHeight(140)
        self.scroll_area_timeline.setWidget(self.timeline)

        # --- BOUTONS DE CONTROLE ---
        layout_boutons = QtWidgets.QHBoxLayout()
        layout_boutons.setContentsMargins(5, 5, 5, 5)
        layout_boutons.setSpacing(5)

        style_bouton_bleu = """
            QPushButton { 
                background-color: #20415d; color: white; font-weight: bold; 
                border: 1px solid #2778a2; border-radius: 4px; padding: 6px 12px; min-width: 50px;
            }
            QPushButton:hover { background-color: #2778a2; }
            QPushButton:pressed { background-color: #152d42; }
        """

        style_systeme = QtWidgets.QApplication.style()

        self.btn_start = QtWidgets.QPushButton()
        self.btn_start.setIcon(style_systeme.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_start.setIconSize(QtCore.QSize(18, 18))
        self.btn_start.setToolTip("START")

        self.btn_stop = QtWidgets.QPushButton()
        self.btn_stop.setIcon(style_systeme.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPause))
        self.btn_stop.setIconSize(QtCore.QSize(18, 18))
        self.btn_stop.setToolTip("STOP")

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

        # --- ASSEMBLAGE SPLITTER VERTICAL ---
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        top_widget = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.affichage_stack)

        bottom_widget = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(6, 6, 6, 6)

        time_container = QtWidgets.QWidget()
        time_container.setLayout(self.layout_temps)
        bottom_layout.addWidget(time_container)

        bottom_layout.addWidget(self.scroll_area_timeline)

        buttons_container = QtWidgets.QWidget()
        buttons_container.setLayout(layout_boutons)
        bottom_layout.addWidget(buttons_container)

        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)

        layout_principal.addWidget(splitter)

        # --- CONNEXIONS ---
        self.btn_start.clicked.connect(self.player.play)
        self.btn_stop.clicked.connect(self.player.pause)
        self.btn_m10.clicked.connect(lambda: self.sauter_de_temps(-10000))
        self.btn_p10.clicked.connect(lambda: self.sauter_de_temps(10000))

        self.btn_x1.clicked.connect(lambda: self.player.setPlaybackRate(1.0))
        self.btn_x2.clicked.connect(lambda: self.player.setPlaybackRate(2.0))
        self.btn_x5.clicked.connect(lambda: self.player.setPlaybackRate(5.0))
        self.btn_x10.clicked.connect(lambda: self.player.setPlaybackRate(10.0))

        self.slider_zoom.valueChanged.connect(self.on_zoom_changed)

        self.player.positionChanged.connect(self.on_player_position_changed)
        self.player.durationChanged.connect(self.on_player_duration_changed)
        
        self.timeline.timeChanged.connect(self.on_timeline_pressed)
        self.timeline.sliderMoved.connect(self.on_timeline_released)
        self.timeline.zoomChanged.connect(self.on_timeline_zoom_changed)

        # Capture des changements d'état natifs du QMediaPlayer
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

    # --- MÉTHODE DE FILTRAGE ET DE DESSIN EN TEMPS RÉEL ---
    def traiter_frame_temps_reel(self, frame: QVideoFrame):
        """Prend la frame vidéo, applique OpenCV si un filtre est actif, et dessine dans le QLabel."""
        if not frame.isValid():
            return

        # Mapper la mémoire graphique pour pouvoir lire l'image
        if frame.map(QVideoFrame.MapMode.ReadOnly):
            q_img = frame.toImage()
            
            # On applique OpenCV uniquement si au moins un filtre est actif
            if self.apply_dehaze or self.apply_histogram:
                # S'assurer d'un format lisible standard (RGB24 bits)
                q_img = q_img.convertToFormat(QtGui.QImage.Format.Format_RGB888)
                width = q_img.width()
                height = q_img.height()
                
                # Conversion : QImage vers Matrice NumPy (RGB) sans copie lourde
                ptr = q_img.bits()
                ptr.setsize(q_img.sizeInBytes())
                arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 3))
                
                # Convertir le RGB de Qt en BGR pour vos fonctions OpenCV d'utils2
                frame_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                
                # --- TRAITEMENT DES FILTRES À LA VOLÉE ---
                if self.apply_histogram:
                    frame_bgr = utils2.process_image_HE(frame_bgr, **self.he_params)
                    
                if self.apply_dehaze:
                    frame_bgr = utils2.process_image_dehaze(frame_bgr)
                
                # Reconvertir de OpenCV (BGR) vers Qt (RGB)
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                q_img = QtGui.QImage(frame_rgb.data, width, height, 3 * width, QtGui.QImage.Format.Format_RGB888)

            # Conversion en Pixmap pour affichage
            pixmap = QtGui.QPixmap.fromImage(q_img)
            
            # Redimensionnement fluide proportionnel à la taille de la fenêtre
            scaled_pixmap = pixmap.scaled(
                self.video_widget.size(), 
                QtCore.Qt.AspectRatioMode.KeepAspectRatio, 
                QtCore.Qt.TransformationMode.SmoothTransformation
            )
            self.video_widget.setPixmap(scaled_pixmap)
            
            # Toujours libérer la mémoire mappée
            frame.unmap()

    # --- GESTION INTERNE DU LECTEUR ---
    def pause(self):
        """Méthode publique pour mettre en pause le lecteur (appelée par ValidationPage)."""
        self.player.pause()

    def _on_playback_state_changed(self, state):
        """Déclenché automatiquement par QtMultimedia dès que l'état du lecteur change."""
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        
        # Si la vidéo reprend la lecture (Play ou Drag timeline), on coupe les corrections
        if is_playing:
            if self.apply_histogram or self.apply_dehaze:
                self.apply_histogram = False
                self.apply_dehaze = False
                print("[LECTEUR] Reprise de la lecture : filtres désactivés.")
        
        # Émission du signal vers ValidationPage
        self.playback_state_changed.emit(is_playing)

    def appliquer_filtre(self, type_correction: str):
        """Active le filtre demandé sur l'image figée et force son rafraîchissement."""
        if type_correction == "HR":
            self.apply_histogram = True
            self.apply_dehaze = False
        elif type_correction == "DEHAZE":
            self.apply_dehaze = True
            self.apply_histogram = False

        # Force le rafraîchissement immédiat de la frame fixe
        self._forcer_rafraichissement_frame()

    def appliquer_correction_fixe(self, type_correction: str):
        """Alias de compatibilité pour appliquer_filtre."""
        self.pause()
        self.appliquer_filtre(type_correction)

    def retirer_filtres(self):
        """Désactive l'ensemble des filtres et actualise l'affichage."""
        if self.apply_histogram or self.apply_dehaze:
            self.apply_histogram = False
            self.apply_dehaze = False
            self._forcer_rafraichissement_frame()
            print("[LECTEUR] Filtres réinitialisés.")

    def _forcer_rafraichissement_frame(self):
        """Effectue un micro-saut temporel pour forcer QVideoSink à réémettre l'image en pause."""
        pos = self.player.position()
        if pos > 0:
            self.player.setPosition(pos - 1)
            self.player.setPosition(pos)

    # --- EVENEMENTS SLIDERS / TIMELINE ---
    def on_zoom_changed(self, value):
        self.timeline.set_zoom(float(value))

    def on_timeline_zoom_changed(self, zoom_factor: float):
        """Met à jour le slider de zoom quand on utilise la molette sur la timeline"""
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(int(round(zoom_factor)))
        self.slider_zoom.blockSignals(False)

    def sauter_de_temps(self, ms: int):
        nouvelle_position = self.player.position() + ms
        self.player.setPosition(max(0, min(nouvelle_position, self.player.duration())))

    def on_timeline_pressed(self, target_ms: int):
        if self.timeline.is_dragging and not self.slider_was_playing:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.slider_was_playing = True
                self.player.pause()
        self.player.setPosition(target_ms)
        self.centrer_scroll_sur_curseur()

    def on_timeline_released(self, target_ms: int):
        self.player.setPosition(target_ms)
        if self.slider_was_playing:
            self.player.play()
            self.slider_was_playing = False
        self.centrer_scroll_sur_curseur()

    def on_player_position_changed(self, position_ms: int):
        if not self.timeline.is_dragging:
            self.timeline.set_current_position(position_ms)
            self.centrer_scroll_sur_curseur()
        self.mettre_a_jour_label_haut(position_ms, self.player.duration())
        self.mettre_a_jour_label_frame(position_ms)

    def centrer_scroll_sur_curseur(self):
        if self.player.duration() <= 0 or self.slider_zoom.value() == 1:
            return
        ratio = self.player.position() / self.player.duration()
        largeur_timeline = self.timeline.width()
        largeur_visible = self.scroll_area_timeline.width()
        x_curseur = int(ratio * largeur_timeline)
        scrollbar = self.scroll_area_timeline.horizontalScrollBar()
        cible_scroll = x_curseur - (largeur_visible // 2)
        scrollbar.setValue(cible_scroll)

    def on_player_duration_changed(self, duree_ms: int):
        self.timeline.set_total_duration(duree_ms)
        self.mettre_a_jour_label_haut(self.player.position(), duree_ms)
        self.mettre_a_jour_label_frame(self.player.position())

    def mettre_a_jour_label_haut(self, position_ms: int, duree_ms: int):
        texte_courant = self.timeline._format_ms(position_ms)
        texte_total = self.timeline._format_ms(duree_ms)
        self.lbl_temps_haut.setText(f"{texte_courant} / {texte_total}")

    def mettre_a_jour_label_frame(self, position_ms: int):
        if self.video_fps and self.video_fps > 0:
            frame_num = int(position_ms * self.video_fps / 1000.0) + 1
            self.lbl_frame_number.setText(f"Frame: {frame_num}")
        else:
            self.lbl_frame_number.setText("Frame: -")

    def _obtenir_fps_video(self, video_path: str) -> float:
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

    def charger_video_et_evenements(self, video_path: str, events: list):
        self.player.stop()
        self.slider_was_playing = False
        self.current_video_path = video_path
        self.video_fps = self._obtenir_fps_video(video_path)
        self.timeline.events = events
        self.slider_zoom.setValue(1)
        self.timeline.set_zoom(1.0)
        self.timeline.update()
        
        if video_path and os.path.exists(video_path):
            self.affichage_stack.setCurrentIndex(1)
            self.player.setSource(QtCore.QUrl.fromLocalFile(video_path))
            self.player.play()
        else:
            self.affichage_stack.setCurrentIndex(0)