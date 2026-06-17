import os
import json
import uuid
import cv2
import numpy as np
import matplotlib.image as mpimg
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from PyQt6 import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from services.motor_service import get_motor_stable_timestamps
from services.campaign_service import get_video_json_path
from services.image_service import extract_frame_at_time
from services.video_service import check_stereo_status
from services.export_service import ExportWorker
from views.widgets.embedded_player import EmbeddedVideoPlayer
from views.dialogs.export_options_dialog import ExportOptionsDialog
from models.video_model import VideoFilterProxyModel
from services.thumbnail_service import THUMB_W, THUMB_H


class EvenementsController:
    """Contrôleur de la page Événements : capture, édition et export des événements vidéo."""

    def __init__(self, page_widget: QtWidgets.QWidget, shared_model: QtGui.QStandardItemModel,
                 on_video_focused=None):
        """Initialise les widgets de la page et connecte les signaux de capture et d'export."""
        self.page = page_widget
        self.video_model = shared_model
        self._on_video_focused = on_video_focused
        self.current_language = 'en'
        self.export_start_ms = 0
        self.export_end_ms = 0
        self.current_json_path = None
        self.current_video_path = None
        self.event_dictionary = {}
        self.capture_start_time = None

        self.left_frame_events = self.page.findChild(QtWidgets.QFrame, "frame_12")
        self.player_container_events = self.page.findChild(QtWidgets.QFrame, "video_timeline_container")
        self.choose_event_container = self.page.findChild(QtWidgets.QFrame, "choose_event_container")

        if self.choose_event_container:
            self.choose_event_container.setMinimumWidth(320)
            self.choose_event_container.setMaximumWidth(420)
            self.choose_event_container.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding
            )
            self.choose_event_container.setStyleSheet(
                "QFrame { background-color: #181c24; border: 1px solid #2778a2; border-radius: 14px; }"
            )

        self.set_language(self.current_language)

        self.list_event_container = self.page.findChild(QtWidgets.QFrame, "list_event_container")
        self._initialize_list_event_layout()

        self.export_container = (
            self.page.findChild(QtWidgets.QWidget, "container_export")
            or self.page.findChild(QtWidgets.QFrame, "container_export")
        )
        self._initialize_export_ui()

        if self.left_frame_events:
            self.left_frame_events.setMinimumWidth(150)
            self.left_frame_events.setMaximumWidth(16777215)

        self.proxy_model = VideoFilterProxyModel(self.page)
        self.proxy_model.setSourceModel(self.video_model)

        if self.player_container_events:
            layout = self.player_container_events.layout() or QtWidgets.QVBoxLayout(self.player_container_events)
            layout.setContentsMargins(10, 10, 10, 10)
            zones = [
                {"label": "Deployment", "color": QtGui.QColor(32, 65, 93, 100)},
                {"label": "Fauna / Animal", "color": QtGui.QColor(39, 120, 162, 100)},
                {"label": "Images", "color": QtGui.QColor(217, 79, 56, 100)},
            ]
            self.event_player = EmbeddedVideoPlayer(parent=self.player_container_events, zone_definitions=zones)
            layout.addWidget(self.event_player)

            self.event_player.timeline.eventResized.connect(self.refresh_event_list)
            if hasattr(self.event_player.timeline, 'eventMoved'):
                self.event_player.timeline.eventMoved.connect(self.refresh_event_list)
            elif hasattr(self.event_player.timeline, 'eventChanged'):
                self.event_player.timeline.eventChanged.connect(self.refresh_event_list)

            self.event_player.timeline.eventSelected.connect(self.on_timeline_event_selected)
            self.event_player.timeline.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            self.event_player.timeline.customContextMenuRequested.connect(
                lambda pos: self.open_context_menu(pos, self.event_player.timeline)
            )
            self._initialize_event_dropdown_menus()

            # Histogramme : démarrage/arrêt du timer selon l'état de lecture
            self.event_player.player.playbackStateChanged.connect(self._on_hist_playback_state)
            # Mise à jour immédiate sur seek en pause
            self.event_player.player.positionChanged.connect(self._on_hist_position_changed)

        self.tree_view_events = self.page.findChild(QtWidgets.QTreeView, "treeView")
        if self.tree_view_events:
            self.tree_view_events.setModel(self.proxy_model)
            self.tree_view_events.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))
            self.tree_view_events.clicked.connect(self.on_video_selected)

        self.tree_captures.itemChanged.connect(self.on_arbre_item_changed)

    # --- Language ---

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def _get_tree_headers(self):
        """Retourne les en-têtes de l'arbre événements selon la langue active."""
        if self.current_language == 'en':
            return ["Start / Capture time", "End", "Event type", "Value", "Comment", "Preview"]
        return ["Début / Heure Capture", "Fin", "Type d'événement", "Valeur", "Commentaire", "Aperçu"]

    def set_language(self, language: str):
        """Met à jour la langue et rafraîchit les en-têtes de l'arbre."""
        self.current_language = language
        if hasattr(self, 'event_player'):
            self.event_player.set_language(language)
        if hasattr(self, 'tree_captures') and self.tree_captures:
            self.tree_captures.setHeaderLabels(self._get_tree_headers())
        self._retranslate_ui()

    def _retranslate_ui(self):
        """Met à jour tous les libellés de l'interface selon la langue active."""
        if hasattr(self, 'lbl_title_event'):
            self.lbl_title_event.setText(self.translate("Sélection d'événement", "Event Selection"))
        if hasattr(self, 'lbl_type_event'):
            self.lbl_type_event.setText(self.translate("Type d'événement", "Event Type"))
        if hasattr(self, 'lbl_valeur_event'):
            self.lbl_valeur_event.setText(self.translate("Caractéristiques", "Characteristics"))
        if hasattr(self, 'lbl_commentaire_input'):
            self.lbl_commentaire_input.setText(self.translate("Commentaire rapide", "Quick Comment"))
        if hasattr(self, 'input_commentaire_event'):
            self.input_commentaire_event.setPlaceholderText(
                self.translate("Écrivez un commentaire...", "Write a comment here..."))
        if hasattr(self, 'btn_capturer') and self.capture_start_time is None:
            self._update_capture_mode()
        if hasattr(self, 'btn_finir') and self.capture_start_time is None:
            self.btn_finir.setText(self.translate("FIN D'ÉVÉNEMENT", "END EVENT"))
        if hasattr(self, 'export_button'):
            self.export_button.setText(self.translate("EXPORTER LES ÉVÉNEMENTS", "EXPORT EVENTS"))

    def load_campaign_videos(self, model: QtGui.QStandardItemModel):
        """Remplace le modèle vidéo partagé après ouverture d'une nouvelle campagne."""
        self.video_model = model
        self.proxy_model.setSourceModel(self.video_model)

    def select_video_by_name(self, video_name: str):
        """Sélectionne une vidéo dans l'arbre depuis son nom (appel depuis la carte)."""
        if not self.tree_view_events or not self.video_model:
            return
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and item.text() == video_name:
                source_index = self.video_model.indexFromItem(item)
                proxy_index = self.proxy_model.mapFromSource(source_index)
                if not proxy_index.isValid():
                    return
                self.tree_view_events.selectionModel().setCurrentIndex(
                    proxy_index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect |
                    QtCore.QItemSelectionModel.SelectionFlag.Rows
                )
                self.tree_view_events.scrollTo(proxy_index)
                self.on_video_selected(proxy_index)
                break

    # --- Tree layout ---

    def _initialize_list_event_layout(self):
        """Crée ou recrée le QTreeWidget d'événements dans list_event_container."""
        if not self.list_event_container:
            return
        if self.list_event_container.layout() is not None:
            main_layout = self.list_event_container.layout()
            while main_layout.count():
                child = main_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        else:
            main_layout = QtWidgets.QHBoxLayout(self.list_event_container)
            main_layout.setContentsMargins(5, 5, 5, 5)
            main_layout.setSpacing(0)

        self.tree_captures = QtWidgets.QTreeWidget()
        self.tree_captures.setColumnCount(6)
        self.tree_captures.setHeaderLabels(self._get_tree_headers())
        self.tree_captures.setColumnWidth(0, 130)
        self.tree_captures.setColumnWidth(1, 90)
        self.tree_captures.setColumnWidth(2, 150)
        self.tree_captures.setColumnWidth(3, 130)
        self.tree_captures.setColumnWidth(4, 180)
        self.tree_captures.setStyleSheet("""
            QTreeWidget { background-color: #1e1e1e; color: white; border: 1px solid #2778a2; border-radius: 4px; }
            QHeaderView::section { background-color: #20415d; color: white; font-weight: bold; border: 1px solid #2778a2; }
            QTreeWidget::item { height: 40px; }
        """)
        self.tree_captures.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_captures.customContextMenuRequested.connect(
            lambda pos: self.open_context_menu(pos, self.tree_captures)
        )
        self.tree_captures.itemSelectionChanged.connect(self.on_tree_event_selected)
        main_layout.addWidget(self.tree_captures)

    # --- Two-way tree/timeline sync ---

    def on_tree_event_selected(self):
        """Propage la sélection de l'arbre vers la timeline (synchronisation bidirectionnelle)."""
        if not hasattr(self, 'event_player') or not self.event_player or not self.event_player.timeline:
            return
        self.event_player.timeline.blockSignals(True)
        try:
            selected_items = self.tree_captures.selectedItems()
            if not selected_items:
                if hasattr(self.event_player.timeline, 'set_selected_event'):
                    self.event_player.timeline.set_selected_event(None)
                else:
                    self.event_player.timeline._selected_event = None
                    self.event_player.timeline.update()
                return
            item = selected_items[0]
            target_value = item.text(3)
            found_event = None
            if hasattr(self.event_player.timeline, 'events'):
                for evt in self.event_player.timeline.events:
                    if evt.get("title", "").replace("Pic: ", "") == target_value:
                        found_event = evt
                        break
            if hasattr(self.event_player.timeline, 'set_selected_event'):
                self.event_player.timeline.set_selected_event(found_event)
            else:
                self.event_player.timeline._selected_event = found_event
                self.event_player.timeline.update()
        finally:
            self.event_player.timeline.blockSignals(False)

    def on_timeline_event_selected(self, event_dict):
        """Propage la sélection de la timeline vers l'arbre (synchronisation bidirectionnelle)."""
        if not hasattr(self, 'tree_captures') or not self.tree_captures:
            return
        self.tree_captures.blockSignals(True)
        try:
            if event_dict is None:
                self.tree_captures.clearSelection()
                return
            target_value = event_dict.get("title", "").replace("Pic: ", "")
            for i in range(self.tree_captures.topLevelItemCount()):
                item = self.tree_captures.topLevelItem(i)
                if item and item.text(3) == target_value:
                    self.tree_captures.clearSelection()
                    item.setSelected(True)
                    self.tree_captures.scrollToItem(item, QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible)
                    break
            else:
                self.tree_captures.clearSelection()
        finally:
            self.tree_captures.blockSignals(False)

    # --- JSON key helpers ---

    def _get_json_key_from_label(self, display_label: str) -> str:
        """Convertit un label affiché (ex. 'Deployment') en clé JSON (ex. 'events_deployment')."""
        if not display_label:
            return "events_custom"
        if hasattr(self, 'event_key_by_label') and display_label in self.event_key_by_label:
            return self.event_key_by_label[display_label]
        lower = display_label.lower()
        if "deployment" in lower or "déploiement" in lower:
            return "events_deployment"
        if "animal" in lower or "faune" in lower:
            return "events_animal"
        if "image" in lower:
            return "events_interesting_images"
        return "events_custom"

    def _get_label_from_json_key(self, json_key: str) -> str:
        """Convertit une clé JSON en label localisé selon la langue active."""
        if hasattr(self, 'event_category_labels') and json_key in self.event_category_labels:
            return self.event_category_labels[json_key]
        if self.current_language == 'en':
            mapping = {
                "events_deployment": "Deployment",
                "events_animal": "Fauna / Animal",
                "events_interesting_images": "Interesting Image"
            }
        else:
            mapping = {
                "events_deployment": "Déploiement",
                "events_animal": "Faune / Animal",
                "events_interesting_images": "Image Intéressante"
            }
        return mapping.get(json_key, json_key)

    def _generate_event_uid(self) -> str:
        """Génère un identifiant unique pour un événement."""
        return str(uuid.uuid4())

    def _ensure_event_uid(self, event_dict: dict) -> str:
        """Garantit qu'event_dict possède un _event_uid, en en créant un si absent."""
        if not event_dict.get("_event_uid"):
            event_dict["_event_uid"] = self._generate_event_uid()
        return event_dict["_event_uid"]

    def _build_event_categories_from_json(self, data: dict):
        """Peuple event_dictionary et les tables de correspondance label↔clé depuis le JSON vidéo."""
        self.event_category_labels = {}
        self.event_key_by_label = {}
        self.event_dictionary.clear()
        if not isinstance(data, dict):
            return
        video_obs = data.get("video_observation", {})
        if not isinstance(video_obs, dict):
            return
        for json_key, value in video_obs.items():
            if not isinstance(json_key, str) or not json_key.startswith("events_"):
                continue
            if not isinstance(value, list) or not value:
                continue
            first_object = value[0]
            if not isinstance(first_object, dict):
                continue
            if self.current_language == 'en':
                authorized_values = (first_object.get("authorized_values_en")
                                     or first_object.get("authorized_values_fr") or [])
            else:
                authorized_values = (first_object.get("authorized_values_fr")
                                     or first_object.get("authorized_values_en") or [])
            if not isinstance(authorized_values, list):
                continue
            label = self._get_label_from_json_key(json_key)
            self.event_category_labels[json_key] = label
            self.event_key_by_label[label] = json_key
            self.event_dictionary[label] = [str(v) for v in authorized_values if v is not None]

    def _get_video_fps(self) -> float:
        """Retourne le FPS du lecteur actif, ou 25.0 par défaut."""
        if hasattr(self, 'event_player') and self.event_player:
            if hasattr(self.event_player, 'video_fps') and isinstance(self.event_player.video_fps, (int, float)):
                if self.event_player.video_fps > 0:
                    return float(self.event_player.video_fps)
        return 25.0

    def _ms_to_frame(self, ms: int, fps: float) -> int:
        """Convertit un timestamp en millisecondes en numéro de frame (base 1)."""
        if fps <= 0:
            return 0
        return max(1, int(round((ms / 1000.0) * fps)))

    def _zone_index_for_event_type(self, type_label: str) -> int:
        """Retourne l'index de zone timeline (0=Déploiement, 1=Faune, 2=Images) selon le label."""
        if not type_label:
            return 0
        label = type_label.lower()
        if "deployment" in label or "déploiement" in label:
            return 0
        if "animal" in label or "faune" in label:
            return 1
        if "image" in label:
            return 2
        return 0

    # --- Dropdown menus ---

    def _initialize_event_dropdown_menus(self):
        """Crée les combos de type/valeur, le champ commentaire et les boutons Capturer/Finir."""
        if not self.choose_event_container:
            return
        if self.choose_event_container.layout() is None:
            menu_layout = QtWidgets.QVBoxLayout(self.choose_event_container)
        else:
            menu_layout = self.choose_event_container.layout()

        menu_layout.setContentsMargins(16, 16, 16, 16)
        menu_layout.setSpacing(14)
        self.choose_event_container.setStyleSheet(
            "QFrame { background-color: #181c24; border: 1px solid #2778a2; border-radius: 14px; }"
        )

        combo_style = """
            QComboBox { background-color: #212a35; color: white; border: 1px solid #2778a2;
                        border-radius: 8px; padding: 8px; }
            QComboBox QAbstractItemView { background-color: #212a35; color: white;
                                          selection-background-color: #2778a2; }"""
        btn_style = """
            QPushButton { background-color: #e68c14; color: white; font-weight: bold;
                          border: 1px solid #f09624; border-radius: 8px; padding: 10px; }
            QPushButton:hover { background-color: #f09624; }
            QPushButton:disabled { background-color: #454545; color: #888888; border: 1px solid #555555; }"""
        label_style = "color: white; font-weight: bold;"
        title_style = "font-size: 14px; font-weight: bold; color: #ffffff;"

        if not hasattr(self, 'combo_type_event') or self.combo_type_event is None:
            self.lbl_title_event = QtWidgets.QLabel(self.translate("Sélection d'événement", "Event Selection"))
            self.lbl_title_event.setStyleSheet(title_style)
            self.lbl_title_event.setMaximumHeight(75)

            self.lbl_type_event = QtWidgets.QLabel(self.translate("Type d'événement", "Event Type"))
            self.lbl_type_event.setStyleSheet(label_style)
            self.combo_type_event = QtWidgets.QComboBox()
            self.combo_type_event.setStyleSheet(combo_style)
            self.combo_type_event.setMinimumWidth(220)

            self.lbl_valeur_event = QtWidgets.QLabel(self.translate("Caractéristiques", "Characteristics"))
            self.lbl_valeur_event.setStyleSheet(label_style)
            self.combo_valeur_event = QtWidgets.QComboBox()
            self.combo_valeur_event.setStyleSheet(combo_style)
            self.combo_valeur_event.setMinimumWidth(220)

            self.lbl_commentaire_input = QtWidgets.QLabel(self.translate("Commentaire rapide", "Quick Comment"))
            self.lbl_commentaire_input.setStyleSheet(label_style)
            self.input_commentaire_event = QtWidgets.QLineEdit()
            self.input_commentaire_event.setPlaceholderText(
                self.translate("Écrivez un commentaire...", "Write a comment here..."))
            self.input_commentaire_event.setStyleSheet("""
                QLineEdit { background-color: #212a35; color: white; border: 1px solid #2778a2;
                            border-radius: 8px; padding: 8px; }""")

            self.btn_capturer = QtWidgets.QPushButton(self.translate("CAPTURER L'ÉVÉNEMENT", "CAPTURE EVENT"))
            self.btn_capturer.setStyleSheet(btn_style)
            self.btn_capturer.setMinimumHeight(38)
            self.btn_finir = QtWidgets.QPushButton(self.translate("FIN D'ÉVÉNEMENT", "END EVENT"))
            self.btn_finir.setStyleSheet(btn_style)
            self.btn_finir.setMinimumHeight(38)
            self.btn_finir.setEnabled(False)

            menu_layout.addWidget(self.lbl_title_event)
            form_layout = QtWidgets.QFormLayout()
            form_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            form_layout.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            form_layout.setSpacing(12)
            form_layout.setContentsMargins(0, 0, 0, 0)
            form_layout.addRow(self.lbl_type_event, self.combo_type_event)
            form_layout.addRow(self.lbl_valeur_event, self.combo_valeur_event)
            form_layout.addRow(self.lbl_commentaire_input, self.input_commentaire_event)
            menu_layout.addLayout(form_layout)

            btn_layout = QtWidgets.QHBoxLayout()
            btn_layout.setSpacing(10)
            btn_layout.addWidget(self.btn_capturer)
            btn_layout.addWidget(self.btn_finir)
            menu_layout.addLayout(btn_layout)

            self.combo_type_event.currentTextChanged.connect(self.on_event_type_changed)
            self.combo_valeur_event.currentTextChanged.connect(self.on_event_value_changed)
            self.btn_capturer.clicked.connect(self.on_capturer_clicked)
            self.btn_finir.clicked.connect(self.on_finir_clicked)

    # --- Export UI ---

    def _initialize_export_ui(self):
        """Crée le bouton d'export, la barre de progression et le label de statut."""
        if not self.export_container:
            return
        layout = self.export_container.layout() or QtWidgets.QVBoxLayout(self.export_container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.export_button = QtWidgets.QPushButton(self.translate("EXPORTER LES ÉVÉNEMENTS", "EXPORT EVENTS"), self.export_container)
        self.export_button.setStyleSheet(
            "QPushButton { background-color: #e68c14; color: white; font-weight: bold; "
            "border: 1px solid #f09624; border-radius: 8px; padding: 12px; }"
            "QPushButton:hover { background-color: #f09624; }"
        )
        self.export_button.setEnabled(False)

        self.export_progress = QtWidgets.QProgressBar(self.export_container)
        self.export_progress.setMinimum(0)
        self.export_progress.setMaximum(100)
        self.export_progress.setValue(0)
        self.export_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #e68c14; border-radius: 4px; background-color: #2a2a2a; }"
            "QProgressBar::chunk { background-color: #e68c14; }"
        )
        self.export_progress.setVisible(False)

        self.export_status_label = QtWidgets.QLabel("", self.export_container)
        self.export_status_label.setWordWrap(True)
        self.export_status_label.setStyleSheet("color: white; font-size: 12px;")

        layout.addWidget(self.export_button)
        layout.addWidget(self.export_progress)
        layout.addWidget(self.export_status_label)

        # ── Histogramme ──────────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1e3448;")
        layout.addWidget(sep)

        lbl_hist = QtWidgets.QLabel(self.translate("Histogramme frame courante", "Current frame histogram"))
        lbl_hist.setStyleSheet(
            "color: #7ec8e3; font-size: 11px; font-weight: bold; border: none;"
        )
        layout.addWidget(lbl_hist)

        fig = Figure(facecolor='#111820')
        self._hist_ax = fig.add_subplot(111)
        self._hist_ax.set_facecolor('#111820')
        fig.subplots_adjust(left=0.06, right=0.99, top=0.96, bottom=0.18)
        self._hist_canvas = FigureCanvas(fig)
        self._hist_canvas.setMinimumHeight(220)
        self._hist_canvas.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._hist_canvas.setStyleSheet("background: #111820; border: none;")
        layout.addWidget(self._hist_canvas, stretch=1)

        # Logo watermark — pré-redimensionné à hauteur fixe pour OffsetImage
        self._hist_logo = None
        _logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'img', 'logo_kosmos.png')
        try:
            raw = cv2.imread(_logo_path, cv2.IMREAD_UNCHANGED)
            if raw is not None:
                lh, lw = raw.shape[:2]
                target_h = 80
                target_w = max(1, int(lw * target_h / lh))
                small = cv2.resize(raw, (target_w, target_h), interpolation=cv2.INTER_AREA)
                # cv2 charge en BGR(A) → convertir en RGB(A) pour matplotlib
                if small.ndim == 3 and small.shape[2] == 4:
                    small = small[:, :, [2, 1, 0, 3]]
                elif small.ndim == 3:
                    small = small[:, :, [2, 1, 0]]
                self._hist_logo = small.astype(np.float32) / 255.0
        except Exception:
            self._hist_logo = None

        self._draw_empty_histogram()

        # Timer répétitif : met à jour l'histogramme toutes les secondes pendant la lecture
        self._hist_timer = QtCore.QTimer()
        self._hist_timer.setInterval(1000)
        self._hist_timer.timeout.connect(self._update_histogram)

        self.export_button.clicked.connect(self.on_export_segment_clicked)
        self.export_worker = None

    def _update_export_button_state(self):
        """Active le bouton Export seulement si une vidéo est chargée."""
        has_video = bool(self.current_video_path)
        if hasattr(self, 'export_button') and self.export_button:
            self.export_button.setEnabled(has_video)

    def _on_hist_playback_state(self, state):
        """Démarre le timer répétitif en lecture, l'arrête en pause."""
        from PyQt6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._hist_timer.start()
        else:
            self._hist_timer.stop()
            # Mise à jour immédiate quand on met en pause
            self._update_histogram()

    def _on_hist_position_changed(self, _pos):
        """Mise à jour immédiate de l'histogramme lors d'un seek en pause."""
        from PyQt6.QtMultimedia import QMediaPlayer
        if not hasattr(self, 'event_player'):
            return
        if self.event_player.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._update_histogram()

    def _hist_apply_style(self, ax):
        """Applique le style sombre commun et le logo watermark sur les axes."""
        ax.set_facecolor('#111820')
        for spine in ax.spines.values():
            spine.set_color('#1e3448')
        ax.tick_params(colors='#56789a', labelsize=6, length=2)
        if hasattr(self, '_hist_logo') and self._hist_logo is not None:
            oi = OffsetImage(self._hist_logo, zoom=1.0, alpha=0.10)
            ab = AnnotationBbox(
                oi, (0.5, 0.5),
                xycoords='axes fraction',
                box_alignment=(0.5, 0.5),
                frameon=False,
                zorder=0,
            )
            ax.add_artist(ab)

    def _draw_empty_histogram(self):
        """Affiche un histogramme vide avec watermark en attente de vidéo."""
        if not hasattr(self, '_hist_ax'):
            return
        ax = self._hist_ax
        ax.clear()
        self._hist_apply_style(ax)
        ax.text(0.5, 0.5, "Aucune vidéo", transform=ax.transAxes,
                ha='center', va='center', color='#2a4a62', fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
        self._hist_canvas.draw()

    def _update_histogram(self):
        """Calcule et dessine l'histogramme R/G/B enrichi de la frame courante."""
        if not hasattr(self, '_hist_ax') or not hasattr(self, 'event_player'):
            return
        video_path = getattr(self.event_player, 'current_video_path', None)
        if not video_path or not os.path.exists(video_path):
            return

        position_ms = self.event_player.player.position()
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, position_ms)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return

        ax = self._hist_ax
        ax.clear()
        self._hist_apply_style(ax)

        # OpenCV lit en BGR → (idx 2=R, 1=G, 0=B)
        channel_cfg = [('#D94F38', 2, 'R'), ('#4CAF50', 1, 'G'), ('#2778A2', 0, 'B')]
        hists = {}
        for color, idx, name in channel_cfg:
            h = cv2.calcHist([frame], [idx], None, [256], [0, 256]).flatten()
            hists[name] = h
            ax.fill_between(range(256), h, alpha=0.28, color=color, zorder=2)
            ax.plot(h, color=color, linewidth=0.9, alpha=0.9, zorder=3)

        y_max = max(h.max() for h in hists.values()) or 1

        # Zones de clipping (surex / sous-ex)
        ax.axvspan(0, 5,   alpha=0.22, color='#5555ff', zorder=1)   # sous-exposition
        ax.axvspan(250, 255, alpha=0.22, color='#D94F38', zorder=1)  # surexposition

        # Ligne de luminosité moyenne
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_luma = int(np.mean(gray))
        ax.axvline(mean_luma, color='#ffffff', linewidth=0.9,
                   alpha=0.55, linestyle='--', zorder=4)

        # Canal dominant
        means = {name: float(np.mean(frame[:, :, idx])) for _, idx, name in channel_cfg}
        dominant = max(means, key=means.get)
        dom_color = {'R': '#D94F38', 'G': '#4CAF50', 'B': '#2778A2'}[dominant]

        # Textes de stats
        ax.text(0.02, 0.97, f"Lum. : {mean_luma}",
                transform=ax.transAxes, color='#a0b8c8',
                fontsize=6.5, va='top', ha='left', zorder=5)
        ax.text(0.98, 0.97, f"Dom. {dominant}",
                transform=ax.transAxes, color=dom_color,
                fontsize=6.5, va='top', ha='right', fontweight='bold', zorder=5)

        ax.set_xlim(0, 255)
        ax.set_ylim(0, y_max * 1.08)
        ax.set_xlabel('Intensité', color='#56789a', fontsize=7)
        self._hist_canvas.draw()

    # --- Capture mode helpers ---

    def on_event_type_changed(self, selected_type: str):
        """Recharge combo_valeur_event et met à jour le mode de capture quand le type change."""
        if not selected_type or selected_type not in self.event_dictionary:
            return
        self.combo_valeur_event.blockSignals(True)
        self.combo_valeur_event.clear()
        self.combo_valeur_event.addItems(
            [str(v) for v in self.event_dictionary[selected_type] if v is not None]
        )
        self.combo_valeur_event.blockSignals(False)
        self._update_capture_mode()

    def on_event_value_changed(self, selected_value: str):
        """Met à jour le mode de capture quand la valeur d'événement change."""
        self._update_capture_mode()

    def _is_single_frame_event(self, selected_type: str, value: str = "") -> bool:
        """Retourne True si la combinaison type/valeur correspond à un événement ponctuel (une frame)."""
        if not selected_type:
            return False
        type_lower = selected_type.lower()
        value_lower = (value or "").strip().lower()
        if "interesting_images" in type_lower or "image" in type_lower:
            return True
        if any(kw in value_lower for kw in ["atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff", "take_off"]):
            return True
        return False

    def _is_landing_event(self, value: str) -> bool:
        """Retourne True si value correspond à un événement d'atterrissage."""
        v = (value or "").strip().lower()
        return any(kw in v for kw in ["atterrissage", "atterissage", "landing"])

    def _is_takeoff_event(self, value: str) -> bool:
        """Retourne True si value correspond à un événement de décollage."""
        v = (value or "").strip().lower()
        return any(kw in v for kw in ["décollage", "decollage", "takeoff", "take_off"])

    def _single_frame_event_conflict(self, selected_type: str, value: str):
        """Détecte si un atterrissage ou décollage existe déjà dans la timeline (conflit unicité)."""
        if not self._is_single_frame_event(selected_type, value):
            return None
        if not hasattr(self, 'event_player') or not getattr(self.event_player, 'timeline', None):
            return None
        for evt in self.event_player.timeline.events:
            if not isinstance(evt, dict):
                continue
            title = str(evt.get('title', '')).replace('Pic: ', '').strip()
            if self._is_landing_event(value) and self._is_landing_event(title):
                return 'landing'
            if self._is_takeoff_event(value) and self._is_takeoff_event(title):
                return 'takeoff'
        return None

    def _update_capture_mode(self):
        """Adapte le libellé et l'état des boutons Capturer/Finir selon le type d'événement sélectionné."""
        current_type = self.combo_type_event.currentText()
        current_value = self.combo_valeur_event.currentText() if hasattr(self, 'combo_valeur_event') else ""
        if self._is_single_frame_event(current_type, current_value):
            self.btn_capturer.setText(self.translate("CAPTURER", "CAPTURE"))
            self.btn_finir.setVisible(False)
            self.btn_finir.setEnabled(False)
            if self.capture_start_time is not None:
                self.capture_start_time = None
        else:
            self.btn_capturer.setText(self.translate("CAPTURER L'ÉVÉNEMENT", "CAPTURE EVENT"))
            self.btn_finir.setVisible(True)
            self.btn_finir.setEnabled(False)

    # --- Capture button handlers ---

    def on_capturer_clicked(self):
        """Enregistre un événement ponctuel ou démarre la capture d'un événement avec durée."""
        if not hasattr(self, 'event_player') or self.event_player is None:
            return
        current_type = self.combo_type_event.currentText()
        current_value = self.combo_valeur_event.currentText()
        quick_comment = self.input_commentaire_event.text().strip() if hasattr(self, 'input_commentaire_event') else ""
        pos_ms = self.event_player.timeline.get_current_position() if hasattr(self.event_player, 'timeline') else 0
        time_str = self.event_player.timeline._format_ms(pos_ms) if hasattr(self.event_player, 'timeline') else "00:00:00"

        if self._is_single_frame_event(current_type, current_value):
            conflict = self._single_frame_event_conflict(current_type, current_value)
            if conflict:
                QtWidgets.QMessageBox.warning(
                    self.page,
                    self.translate("Action impossible", "Impossible action"),
                    self.translate(f"Un {conflict} existe déjà.", f"A {conflict} already exists.")
                )
                return

            clean_category_name = current_type.split(' ')[0]
            new_evt = {
                "start": pos_ms, "end": pos_ms,
                "title": f"Pic: {current_value}",
                "type": "custom_event",
                "zone": self._zone_index_for_event_type(current_type),
                "single_frame": True,
                "comment": quick_comment,
                "_json_key": self._get_json_key_from_label(current_type),
                "_event_uid": self._generate_event_uid()
            }
            self.event_player.timeline.events.append(new_evt)
            self.event_player.timeline.update()

            if hasattr(self, 'tree_captures') and self.tree_captures:
                tree_item = QtWidgets.QTreeWidgetItem(
                    [time_str, "-", clean_category_name, current_value, quick_comment, ""]
                )
                tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#e68c14")))
                self.tree_captures.addTopLevelItem(tree_item)
                self.add_tree_thumbnail(tree_item, pos_ms)

            self.save_event_to_json(new_evt, current_type)
            if hasattr(self, 'input_commentaire_event'):
                self.input_commentaire_event.clear()
        else:
            self.capture_start_time = pos_ms
            self._current_comment = quick_comment
            self.btn_capturer.setEnabled(False)
            self.btn_finir.setEnabled(True)
            self.btn_finir.setText(self.translate(f"FIN D'ÉVÉNEMENT (Début : {time_str})", f"END EVENT (Start: {time_str})"))

    def on_finir_clicked(self):
        """Clôture la capture en cours et enregistre l'événement avec sa durée start→end."""
        if not hasattr(self, 'event_player') or self.capture_start_time is None:
            return
        current_type = self.combo_type_event.currentText()
        current_value = self.combo_valeur_event.currentText()
        saved_comment = getattr(self, '_current_comment', "")
        t_start = self.capture_start_time
        t_end = self.event_player.timeline.get_current_position() if hasattr(self.event_player, 'timeline') else 0
        if t_end < t_start:
            t_start, t_end = t_end, t_start

        start_str = self.event_player.timeline._format_ms(t_start)
        end_str = self.event_player.timeline._format_ms(t_end)
        clean_category = current_type.split(' ')[0]

        new_evt = {
            "start": t_start, "end": t_end,
            "title": current_value,
            "type": "custom_event",
            "zone": self._zone_index_for_event_type(current_type),
            "single_frame": False,
            "comment": saved_comment,
            "_json_key": self._get_json_key_from_label(current_type),
            "_event_uid": self._generate_event_uid()
        }
        self.event_player.timeline.events.append(new_evt)
        self.event_player.timeline.update()

        if hasattr(self, 'tree_captures') and self.tree_captures:
            tree_item = QtWidgets.QTreeWidgetItem(
                [start_str, end_str, clean_category, current_value, saved_comment, ""]
            )
            tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            self.tree_captures.addTopLevelItem(tree_item)
            self.add_tree_thumbnail(tree_item, t_start)

        self.save_event_to_json(new_evt, current_type)
        self.capture_start_time = None
        self._current_comment = ""
        if hasattr(self, 'input_commentaire_event'):
            self.input_commentaire_event.clear()
        self.btn_capturer.setEnabled(True)
        self.btn_finir.setEnabled(False)
        self.btn_finir.setText(self.translate("FIN D'ÉVÉNEMENT", "END EVENT"))

    # --- Video selection ---

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Charge la vidéo sélectionnée, reconstruit la timeline avec les événements JSON et moteur."""
        original_index = self.proxy_model.mapToSource(index)
        item = self.video_model.itemFromIndex(original_index.siblingAtColumn(0))
        if not item or not item.data(QtCore.Qt.ItemDataRole.UserRole):
            return

        self.current_video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        video_dir = os.path.dirname(self.current_video_path)
        self.current_json_path = get_video_json_path(self.current_video_path)
        if self._on_video_focused:
            self._on_video_focused(item.text())

        is_stereo, video_to_load = check_stereo_status(self.current_video_path)

        if hasattr(self, 'tree_captures') and self.tree_captures:
            self.tree_captures.blockSignals(True)
            self.tree_captures.clear()

        self.capture_start_time = None
        if hasattr(self, 'btn_capturer'):
            self.btn_capturer.setEnabled(True)

        self.charger_evenements_du_json()
        self._nettoyer_json_misplaced_events()
        self._update_export_button_state()

        video_fps = 25.0
        if os.path.exists(self.current_video_path):
            try:
                cap = cv2.VideoCapture(self.current_video_path)
                video_fps = cap.get(cv2.CAP_PROP_FPS)
                if video_fps <= 0:
                    video_fps = 25.0
                cap.release()
            except Exception:
                video_fps = 25.0

        timeline_events = []
        csv_system = os.path.join(video_dir, "systemEvent.csv")
        if os.path.exists(csv_system):
            try:
                motor_data = get_motor_stable_timestamps(csv_system, delay=6.0)
                for motor_item in motor_data:
                    start_ms = int(motor_item["timestamp"] * 1000)
                    timeline_events.append({
                        "start": start_ms, "end": start_ms + 3000,
                        "title": f"Rot #{motor_item['rotation_index']} ({motor_item['angle']}°)",
                        "type": motor_item["type"]
                    })
            except Exception as e:
                print(f"[EVENTS] Motor CSV Error: {e}")

        if self.current_json_path and os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                video_obs = data.get("video_observation", {})
                fps = video_fps
                frame_tolerance = max(1, int(fps * 0.25))

                for json_key in ["events_deployment", "events_animal", "events_interesting_images"]:
                    if json_key in video_obs and video_obs[json_key]:
                        values_list = video_obs[json_key][0].get("values", [])
                        category_name = self._get_label_from_json_key(json_key)

                        for val in values_list:
                            frame_start = val.get("frame_number_start", 0)
                            frame_end = val.get("frame_number_end", 0)
                            value = val.get("value", "")
                            json_comment = val.get("comment", "")
                            start_ms = int(((frame_start - 1) / fps) * 1000) if frame_start and fps else 0
                            end_ms = int(((frame_end - 1) / fps) * 1000) if frame_end and fps else 0
                            is_pic = (json_key == "events_interesting_images" or start_ms == end_ms)
                            timeline_title = f"Pic: {value}" if is_pic else value
                            zone_index = self._zone_index_for_event_type(json_key)

                            is_duplicate = any(
                                e.get("title") == timeline_title
                                and abs(e.get("start", 0) - start_ms) <= (frame_tolerance * 1000 / fps)
                                for e in timeline_events
                            )
                            if not is_duplicate:
                                txt_start = self.event_player.timeline._format_ms(start_ms)
                                txt_end = self.event_player.timeline._format_ms(end_ms) if not is_pic else "-"
                                event_dict = {
                                    "start": start_ms, "end": end_ms,
                                    "title": timeline_title,
                                    "type": "custom_event",
                                    "zone": zone_index,
                                    "comment": json_comment,
                                    "_json_key": json_key
                                }
                                if "event_id" in val and val["event_id"]:
                                    event_dict["_event_uid"] = val["event_id"]
                                timeline_events.append(event_dict)

                                if hasattr(self, 'tree_captures') and self.tree_captures:
                                    tree_item = QtWidgets.QTreeWidgetItem(
                                        [txt_start, txt_end, category_name, value, json_comment, ""]
                                    )
                                    tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                                    if is_pic:
                                        tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#e68c14")))
                                    else:
                                        tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#2778a2")))
                                    self.tree_captures.addTopLevelItem(tree_item)
                                    self.add_tree_thumbnail(tree_item, start_ms)
            except Exception as e:
                print(f"[EVENTS] JSON Parsing failed: {e}")

        if hasattr(self, 'tree_captures') and self.tree_captures:
            self.tree_captures.blockSignals(False)

        if hasattr(self, 'event_player') and self.event_player:
            csv_telemetry = self.current_video_path.replace(".mp4", ".csv")
            if os.path.exists(csv_telemetry):
                self.event_player.load_dynamic_metadata(csv_telemetry)
            else:
                self.event_player.df_telemetry = None
                self.event_player.btn_telemetry.setEnabled(False)
                self.event_player.btn_telemetry.setChecked(False)
            self.event_player.load_video_and_events(video_to_load, timeline_events, is_stereo=is_stereo)
            self._draw_empty_histogram()
            self._hist_timer.start()
            QtCore.QTimer.singleShot(400, self._update_histogram)

    def charger_evenements_du_json(self):
        """Lit le JSON vidéo courant et peuple les combos de type/valeur avec les catégories disponibles."""
        self.event_dictionary.clear()
        self.combo_type_event.blockSignals(True)
        self.combo_type_event.clear()
        if self.current_json_path and os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._build_event_categories_from_json(data)
                if self.event_dictionary:
                    self.combo_type_event.addItems(list(self.event_dictionary.keys()))
                    self.on_event_type_changed(self.combo_type_event.currentText())
            except Exception as e:
                print(f"[ERROR] Failed to read JSON event schema: {e}")
        self.combo_type_event.blockSignals(False)

    # --- JSON persistence ---

    def save_event_to_json(self, event_dict: dict, display_type: str):
        """Persiste un événement dans la section video_observation du JSON vidéo courant."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if "video_observation" not in data:
                data["video_observation"] = {}

            json_key = event_dict.get("_json_key") or self._get_json_key_from_label(display_type)
            title_value = event_dict.get("title", "").replace("Pic: ", "").strip().lower()
            if any(kw in title_value for kw in ["atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff"]):
                json_key = "events_deployment"
                event_dict["_json_key"] = "events_deployment"

            if json_key not in data["video_observation"] or not data["video_observation"][json_key]:
                data["video_observation"][json_key] = [{"authorized_values_fr": [], "values": []}]

            fps = self._get_video_fps()
            frame_start = self._ms_to_frame(event_dict["start"], fps)
            frame_end = self._ms_to_frame(event_dict["end"], fps)
            event_uid = self._ensure_event_uid(event_dict)

            saved_value = {
                "event_id": event_uid,
                "time_code_start": self.event_player.timeline._format_ms(event_dict["start"]),
                "time_code_end": self.event_player.timeline._format_ms(event_dict["end"]),
                "frame_number_start": frame_start,
                "frame_number_end": frame_end,
                "description_fr": None,
                "description_en": None,
                "value": event_dict["title"].replace("Pic: ", ""),
                "comment": event_dict.get("comment", "")
            }

            values_list = data["video_observation"][json_key][0].get("values", [])
            existing_index = -1
            for idx, v in enumerate(values_list):
                if v.get("event_id") == event_uid:
                    existing_index = idx
                    break

            if existing_index != -1:
                values_list[existing_index] = saved_value
            else:
                tolerance = max(1, int(fps * 0.25))
                for idx, v in enumerate(values_list):
                    if (v.get("value") == saved_value["value"]
                            and abs(v.get("frame_number_start", 0) - frame_start) <= tolerance):
                        existing_index = idx
                        break
                if existing_index != -1:
                    values_list[existing_index] = saved_value
                else:
                    values_list.append(saved_value)

            data["video_observation"][json_key][0]["values"] = values_list
            event_dict["_json_key"] = json_key
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[BACKEND] Exception writing JSON: {e}")

    def delete_event_from_json(self, event_dict: dict):
        """Supprime l'événement correspondant du JSON vidéo courant (tolérance d'un quart de seconde)."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            video_obs = data.get("video_observation", {})
            target_value = event_dict["title"].replace("Pic: ", "")
            fps = self._get_video_fps()
            target_frame_start = self._ms_to_frame(event_dict["start"], fps)
            tolerance = max(1, int(fps * 0.25))
            for json_key in ["events_deployment", "events_animal", "events_interesting_images"]:
                if json_key in video_obs and video_obs[json_key]:
                    values_list = video_obs[json_key][0].get("values", [])
                    new_list = [
                        v for v in values_list
                        if not (v.get("value") == target_value
                                and abs(v.get("frame_number_start", 0) - target_frame_start) <= tolerance)
                    ]
                    video_obs[json_key][0]["values"] = new_list
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[BACKEND] Error purging event: {e}")

    def refresh_event_list(self, modified_event: dict):
        """Met à jour les timestamps d'un événement dans l'arbre après redimensionnement sur la timeline."""
        if not hasattr(self, 'tree_captures') or self.tree_captures is None:
            return
        self.tree_captures.blockSignals(True)
        target_value = modified_event.get("title", "").replace("Pic: ", "")
        for i in range(self.tree_captures.topLevelItemCount()):
            item = self.tree_captures.topLevelItem(i)
            if item.text(3) == target_value:
                new_start = modified_event.get("start", 0)
                new_end = modified_event.get("end", 0)
                txt_start = self.event_player.timeline._format_ms(new_start)
                txt_end = (self.event_player.timeline._format_ms(new_end)
                           if new_start != new_end and "Pic:" not in modified_event.get("title", "")
                           else "-")
                item.setText(0, txt_start)
                item.setText(1, txt_end)
                self.add_tree_thumbnail(item, new_start)
                break
        self.tree_captures.blockSignals(False)
        self.tree_captures.viewport().update()

        display_type = self.combo_type_event.currentText()
        if "_json_key" in modified_event:
            display_type = self._get_label_from_json_key(modified_event["_json_key"])
        self.save_event_to_json(modified_event, display_type)

    def on_arbre_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int):
        """Persiste le commentaire édité directement dans l'arbre (colonne 4) vers le JSON."""
        if column != 4:
            return
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        target_value = item.text(3)
        new_comment = item.text(4).strip()

        if hasattr(self, 'event_player') and getattr(self.event_player, 'timeline', None):
            for evt in self.event_player.timeline.events:
                if evt.get("title", "").replace("Pic: ", "") == target_value:
                    evt["comment"] = new_comment
                    break

        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            video_obs = data.get("video_observation", {})
            modified = False
            for json_key in ["events_deployment", "events_animal", "events_interesting_images"]:
                if json_key in video_obs and video_obs[json_key]:
                    for val in video_obs[json_key][0].get("values", []):
                        if val.get("value") == target_value:
                            val["comment"] = new_comment
                            modified = True
                            break
                if modified:
                    break
            if modified:
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[BACKEND] Error editing comment: {e}")

    # --- Context menu ---

    def open_context_menu(self, position, emitter):
        """Affiche un menu contextuel Supprimer sur un clic droit dans l'arbre ou la timeline."""
        event_dict = None
        target_tree_item = None

        if emitter == self.tree_captures:
            item = self.tree_captures.itemAt(position)
            if item:
                target_tree_item = item
                title_value = item.text(3)
                for evt in self.event_player.timeline.events:
                    if evt.get("title") == title_value or evt.get("title") == f"Pic: {title_value}":
                        event_dict = evt
                        break
        elif emitter == self.event_player.timeline:
            event_dict = self.event_player.timeline.get_event_at_position(position)
            if event_dict:
                title_value = event_dict.get("title", "").replace("Pic: ", "")
                for i in range(self.tree_captures.topLevelItemCount()):
                    item = self.tree_captures.topLevelItem(i)
                    if item.text(3) == title_value:
                        target_tree_item = item
                        break

        if not event_dict:
            return

        menu = QtWidgets.QMenu(self.page)
        menu.setStyleSheet("""
            QMenu { background-color: #2b2b2b; color: white; border: 1px solid #2778a2; }
            QMenu::item { padding: 6px 20px 6px 20px; }
            QMenu::item:selected { background-color: #20415d; color: #f09624; }
        """)
        delete_action = menu.addAction(self.translate("Supprimer l'événement", "Delete event"))
        chosen_action = menu.exec(emitter.mapToGlobal(position))
        if chosen_action == delete_action:
            self.delete_event_unified(event_dict, target_tree_item)

    def delete_event_unified(self, event_dict: dict, tree_item: QtWidgets.QTreeWidgetItem):
        """Supprime un événement de la timeline, de l'arbre et du JSON en une seule opération."""
        if event_dict in self.event_player.timeline.events:
            self.event_player.timeline.events.remove(event_dict)
            self.event_player.timeline.update()
        if tree_item:
            top_index = self.tree_captures.indexOfTopLevelItem(tree_item)
            if top_index != -1:
                self.tree_captures.takeTopLevelItem(top_index)
        self.delete_event_from_json(event_dict)

    # --- Thumbnails ---

    def add_tree_thumbnail(self, tree_item: QtWidgets.QTreeWidgetItem, timestamp_ms: int):
        """Extrait une miniature vidéo et l'insère dans la colonne Aperçu de tree_item."""
        thumbnail_label = QtWidgets.QLabel()
        thumbnail_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        thumbnail_label.setStyleSheet("background-color: black; margin: 2px; border-radius: 2px;")
        vignette_pixmap = None
        if self.current_video_path and os.path.exists(self.current_video_path):
            frame_rgb = extract_frame_at_time(self.current_video_path, timestamp_ms / 1000.0)
            if frame_rgb is not None:
                h, w, ch = frame_rgb.shape
                q_img = QtGui.QImage(frame_rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
                vignette_pixmap = QtGui.QPixmap.fromImage(q_img)
        if vignette_pixmap and not vignette_pixmap.isNull():
            thumbnail_label.setPixmap(
                vignette_pixmap.scaled(60, 34, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                       QtCore.Qt.TransformationMode.SmoothTransformation)
            )
        else:
            thumbnail_label.setText("N/A")
            thumbnail_label.setStyleSheet("color: gray; font-size: 9px; font-weight: bold;")
        self.tree_captures.setItemWidget(tree_item, 5, thumbnail_label)

    # --- JSON cleanup ---

    def _nettoyer_json_misplaced_events(self):
        """Déplace les événements atterrissage/décollage mal classés vers events_deployment dans le JSON."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            video_obs = data.get("video_observation", {})
            modified = False
            event_categories = [k for k in video_obs if isinstance(k, str) and k.startswith("events_") and k != "events_deployment"]
            for json_key in event_categories:
                if json_key not in video_obs or not video_obs[json_key]:
                    continue
                values_list = video_obs[json_key][0].get("values", [])
                deployment_events = []
                other_events = []
                for event in values_list:
                    v = event.get("value", "").strip().lower()
                    if any(kw in v for kw in ["atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff"]):
                        deployment_events.append(event)
                        modified = True
                    else:
                        other_events.append(event)
                if deployment_events:
                    video_obs[json_key][0]["values"] = other_events
                    if "events_deployment" not in video_obs or not video_obs["events_deployment"]:
                        video_obs["events_deployment"] = [{"authorized_values_fr": [], "values": []}]
                    existing_deploy = video_obs["events_deployment"][0].get("values", [])
                    for evt in deployment_events:
                        if not any(
                            e.get("value") == evt.get("value")
                            and e.get("frame_number_start") == evt.get("frame_number_start")
                            for e in existing_deploy
                        ):
                            existing_deploy.append(evt)
                    video_obs["events_deployment"][0]["values"] = existing_deploy
            if modified:
                data["video_observation"] = video_obs
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[CLEANUP] Error: {e}")

    # --- Export ---

    def _get_export_segment_bounds(self):
        """Lit les frames atterrissage et décollage du JSON et retourne (start_ms, end_ms), ou None."""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            return None
        template_path = get_video_json_path(self.current_video_path)
        if not os.path.exists(template_path):
            return None
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            events_deployment = json_data.get('video_observation', {}).get('events_deployment', [])
            if not isinstance(events_deployment, list) or not events_deployment:
                return None
            values = events_deployment[0].get('values', [])
            landing_frame = takeoff_frame = None
            for item in values:
                val = str(item.get('value', '')).strip().lower()
                if val in ('atterrissage', 'landing'):
                    landing_frame = item.get('frame_number_start')
                elif val in ('décollage', 'take_off', 'takeoff'):
                    takeoff_frame = item.get('frame_number_start')
            if landing_frame is None or takeoff_frame is None:
                return None
            landing_frame = int(landing_frame)
            takeoff_frame = int(takeoff_frame)
            cap = cv2.VideoCapture(self.current_video_path)
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.release()
            start_ms = ((float(landing_frame) - 1.0) / float(video_fps)) * 1000.0
            end_ms = ((float(takeoff_frame) - 1.0) / float(video_fps)) * 1000.0
            return start_ms, end_ms
        except Exception as e:
            print(f"[EXPORT] Exception: {e}")
            return None

    def on_export_segment_clicked(self):
        """Lance le dialogue d'options puis démarre ExportWorker sur le segment atterrissage→décollage."""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            QtWidgets.QMessageBox.warning(self.page,
                self.translate("Export Impossible", "Export Impossible"),
                self.translate("Aucune source vidéo active.", "No active video source."))
            return
        if not hasattr(self, 'event_player') or not getattr(self.event_player, 'timeline', None):
            QtWidgets.QMessageBox.warning(self.page,
                self.translate("Export Impossible", "Export Impossible"),
                self.translate("Composants de tracking indisponibles.", "Tracking components unavailable."))
            return

        bounds = self._get_export_segment_bounds()
        if bounds is None:
            QtWidgets.QMessageBox.warning(self.page,
                self.translate("Export Impossible", "Export Impossible"),
                self.translate("Bornes temporelles manquantes.", "Missing time bounds."))
            return

        parent_video_directory = os.path.dirname(self.current_video_path)
        session_root = os.path.dirname(parent_video_directory)
        json_path = os.path.join(session_root, "matrices.json")
        is_stereo_mode = getattr(self.event_player, "is_stereo", False)

        dialog = ExportOptionsDialog(self.page, is_stereo=is_stereo_mode)
        dialog.set_language(self.current_language)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        options = dialog.get_processing_options()
        target_fps = options.get("target_fps", 5)
        apply_he = options.get("apply_he", False)
        apply_dh = options.get("apply_dh", False)
        is_water = options.get("is_water", False)
        apply_rectify = options.get("apply_rectify", False)

        if apply_rectify and not os.path.exists(json_path):
            QtWidgets.QMessageBox.critical(
                self.page,
                self.translate("Fichier Manquant", "Missing File"),
                self.translate(
                    f"La rectification est cochée mais le fichier est introuvable :\n{json_path}",
                    f"Rectification is checked but the file could not be found:\n{json_path}"
                )
            )
            return

        start_ms, end_ms = bounds
        self.export_start_ms = start_ms
        self.export_end_ms = end_ms

        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)
        self.export_status_label.setText(self.translate(f"Export en cours ({target_fps} FPS)...", f"Exporting ({target_fps} FPS)..."))
        self.export_button.setEnabled(False)

        self.export_worker = ExportWorker(
            video_path=self.current_video_path,
            base_output_dir=parent_video_directory,
            start_ms=start_ms, end_ms=end_ms,
            target_fps=target_fps, events=[],
            apply_he=apply_he, apply_dh=apply_dh,
            is_water=is_water, is_stereo=is_stereo_mode,
            apply_rectify=apply_rectify, json_path=json_path
        )
        self.export_worker.progress_updated.connect(self._on_export_progress)
        self.export_worker.export_finished.connect(self._on_export_finished)
        self.export_worker.export_error.connect(self._on_export_error)
        self.export_worker.start()

    def _on_export_progress(self, progress: int):
        """Met à jour la barre de progression pendant l'export."""
        if hasattr(self, 'export_progress') and self.export_progress:
            self.export_progress.setValue(progress)

    def _on_export_finished(self, saved_count: int):
        """Affiche le résultat de l'export et génère le CSV d'événements."""
        message = self.translate(f"Export terminé : {saved_count} images sauvegardées.", f"Export complete: {saved_count} images saved.")
        if self._generate_events_csv(self.current_video_path, self.export_start_ms, self.export_end_ms):
            message += self.translate("\nCSV d'événements généré.", "\nEvents CSV generated.")
        if hasattr(self, 'export_status_label') and self.export_status_label:
            self.export_status_label.setText(message)
        if hasattr(self, 'export_button') and self.export_button:
            self.export_button.setEnabled(bool(self.current_video_path))
        if hasattr(self, 'export_progress') and self.export_progress:
            self.export_progress.setVisible(False)

    def _on_export_error(self, error_message: str):
        """Affiche le message d'erreur de l'export et réactive le bouton."""
        if hasattr(self, 'export_status_label') and self.export_status_label:
            self.export_status_label.setText(self.translate(f"Erreur : {error_message}", f"Error: {error_message}"))
        if hasattr(self, 'export_button') and self.export_button:
            self.export_button.setEnabled(bool(self.current_video_path))
        if hasattr(self, 'export_progress') and self.export_progress:
            self.export_progress.setVisible(False)

    def _generate_events_csv(self, video_path, start_ms, end_ms):
        """Génère events.csv dans le dossier vidéo en associant événements JSON et rotations moteur aux images exportées."""
        parent_dir = os.path.dirname(os.path.normpath(video_path))
        template_json_path = get_video_json_path(video_path)
        events_csv_path = os.path.normpath(os.path.join(parent_dir, "events.csv"))
        img_dir_root = os.path.normpath(os.path.join(parent_dir, "img"))
        stereo_left_path = os.path.join(img_dir_root, "LEFT")
        img_dir = stereo_left_path if os.path.exists(stereo_left_path) else img_dir_root

        if not os.path.exists(template_json_path) or not os.path.exists(img_dir):
            return False

        try:
            with open(template_json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            cap = cv2.VideoCapture(self.current_video_path)
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.release()

            video_obs = json_data.get('video_observation', {})

            # Images nommées séquentiellement : 00001.jpg, 00002.jpg, …
            seq_to_image = {}
            for img_name in sorted(os.listdir(img_dir)):
                if img_name.endswith('.jpg'):
                    try:
                        seq_to_image[int(os.path.splitext(img_name)[0])] = img_name
                    except ValueError:
                        pass
            total_images = len(seq_to_image)
            if total_images == 0:
                return False

            # Correspondance video_frame → seq_idx :  seq = round((F - start_frame) / interval) + 1
            start_frame = int((start_ms / 1000.0) * video_fps)
            interval = max(1, int(video_fps / 5.0))

            def frame_to_seq(video_frame: int) -> int:
                return max(1, min(round((video_frame - start_frame) / interval) + 1, total_images))

            events_list = []
            track_id = 0
            for category in ['events_deployment', 'events_animal', 'events_interesting_images']:
                cat_data = video_obs.get(category, [])
                if isinstance(cat_data, list) and len(cat_data) > 0:
                    for item in cat_data[0].get('values', []):
                        f_start = item.get('frame_number_start')
                        f_end = item.get('frame_number_end')
                        name = str(item.get('value', 'unknown')).strip()
                        if f_start is not None:
                            f_start = int(f_start)
                            f_end = int(f_end) if (f_end is not None and int(f_end) >= f_start) else f_start
                            events_list.append({'id': track_id, 'start': f_start, 'end': f_end, 'name': name})
                            track_id += 1

            motor_events = []
            system_event_path = os.path.normpath(os.path.join(parent_dir, "systemEvent.csv"))
            if os.path.exists(system_event_path):
                try:
                    motor_events = get_motor_stable_timestamps(system_event_path, delay=6.0, start_track_id=track_id)
                except Exception as e:
                    print(f"[CSV] Error motor file: {e}")

            from datetime import datetime
            with open(events_csv_path, 'w', newline='', encoding='utf-8') as f:
                f.write(
                    "# 1: Detection or Track-id,2: Video or Image Identifier,3: Unique Frame Identifier,"
                    "4-7: Img-bbox(TL_x,TL_y,BR_x,BR_y),8: Detection or Length Confidence,"
                    "9: Target Length (0 or -1 if invalid),10-11+: Repeated Species,Confidence Pairs or Attributes\n"
                )
                f.write(
                    f"# metadata,fps: 5,\"exported_by: \"\"dive:kosmos\"\"\","
                    f"\"exported_time: \"\"{datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}\"\"\"\n"
                )

                for ev in events_list:
                    is_takeoff = any(kw in ev['name'].lower() for kw in ['décollage', 'decollage', 'takeoff', 'take_off'])
                    s_idx = frame_to_seq(ev['start'])
                    e_idx = total_images if is_takeoff else frame_to_seq(ev['end'])
                    for seq_num in range(s_idx, e_idx + 1):
                        if seq_num in seq_to_image:
                            img_full = os.path.normpath(os.path.join(img_dir, seq_to_image[seq_num]))
                            f.write(f"{ev['id']},{img_full},{seq_num},0,0,0,0,1,-1,{ev['name']},1,\n")

                for m_ev in motor_events:
                    f_s = int(m_ev['timestamp'] * video_fps)
                    f_e = int((m_ev['timestamp'] + m_ev['duration']) * video_fps)
                    for seq_num in range(frame_to_seq(f_s), frame_to_seq(f_e) + 1):
                        if seq_num in seq_to_image:
                            img_full = os.path.normpath(os.path.join(img_dir, seq_to_image[seq_num]))
                            f.write(f"{m_ev['track_id']},{img_full},{seq_num},0,0,0,0,1,-1,{m_ev['type']},1,\n")

            return True
        except Exception as e:
            print(f"[CSV ERROR] {e}")
            return False
