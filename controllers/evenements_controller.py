import os
import json
import shutil
import uuid
import cv2
from PyQt6 import QtCore, QtGui, QtWidgets

from services.motor_service import get_motor_stable_timestamps
from services.campaign_service import (
    get_video_json_path, get_campaign_output_dir, get_video_output_dir,
    get_working_video_dir, resolve_video_json_path,
)
from services.image_service import extract_frame_at_time
from services.video_service import check_stereo_status
from services.export_service import ExportWorker
from views.widgets.embedded_player import EmbeddedVideoPlayer
from views.widgets.video_bar_delegate import VideoBarDelegate
from views.dialogs.export_options_dialog import ExportOptionsDialog
from models.video_model import VideoFilterProxyModel
from services.thumbnail_service import THUMB_W, THUMB_H


class _EventTypeDelegate(QtWidgets.QStyledItemDelegate):
    """QComboBox en ligne pour éditer le type d'événement (colonne 2) dans l'arbre."""

    def __init__(self, get_types_fn, parent=None):
        super().__init__(parent)
        self._get_types = get_types_fn

    def createEditor(self, parent, option, index):
        combo = QtWidgets.QComboBox(parent)
        combo.addItems(self._get_types())
        combo.setStyleSheet(
            "QComboBox { background-color:#212a35; color:white; border:1px solid #2778a2; padding:4px; }"
            "QComboBox QAbstractItemView { background-color:#212a35; color:white;"
            " selection-background-color:#2778a2; }"
        )
        combo.activated.connect(lambda: (
            self.commitData.emit(combo),
            self.closeEditor.emit(combo, QtWidgets.QAbstractItemDelegate.EndEditHint.NoHint),
        ))
        return combo

    def setEditorData(self, editor, index):
        current = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        idx = editor.findText(current)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), QtCore.Qt.ItemDataRole.EditRole)


class EvenementsController:
    """Contrôleur de la page Événements : capture, édition et export des événements vidéo."""

    def __init__(self, page_widget: QtWidgets.QWidget, shared_model: QtGui.QStandardItemModel,
                 on_video_focused=None, on_events_changed=None):
        """Initialise les widgets de la page et connecte les signaux de capture et d'export."""
        self.page = page_widget
        self.video_model = shared_model
        self._on_video_focused = on_video_focused
        self._on_events_changed = on_events_changed
        self._working_dir: str = ""
        self.current_language = 'en'
        self.export_start_ms = 0
        self.export_end_ms = 0
        self.current_json_path = None
        self.current_video_path = None
        self.event_dictionary = {}
        self.capture_start_time = None
        self._analysis_widgets: dict[str, QtWidgets.QLineEdit] = {}

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
            # Ne pas dépasser 420 (largeur max de choose_event_container) : sinon frame_12
            # se voit allouer plus d'espace par le splitter que son contenu n'en occupe,
            # et son propre fond bleu reste visible en trou entre la liste et le lecteur.
            self.left_frame_events.setMaximumWidth(420)

        self.proxy_model = VideoFilterProxyModel(self.page)
        self.proxy_model.setSourceModel(self.video_model)

        if self.player_container_events:
            layout = self.player_container_events.layout() or QtWidgets.QVBoxLayout(self.player_container_events)
            layout.setContentsMargins(0, 0, 0, 0)
            zones = [
                {"label": "Deployment",     "color": QtGui.QColor(39, 120, 162, 180)},  # bleu
                {"label": "Fauna / Animal", "color": QtGui.QColor(217, 79,  56, 180)},  # rouge
                {"label": "Images",         "color": QtGui.QColor(230, 140,  20, 180)}, # orange
            ]
            self.event_player = EmbeddedVideoPlayer(parent=self.player_container_events, zone_definitions=zones)
            layout.addWidget(self.event_player)

            self.event_player.btn_ardoise.setVisible(False)
            self.event_player.btn_ardoise_manquante.setVisible(False)
            self.event_player.btn_debut_annotation.clicked.connect(self._saisir_debut_annotation)
            self.event_player.btn_fin_annotation.clicked.connect(self._saisir_fin_annotation)
            self.event_player.btn_debut_annotation.setVisible(True)
            self.event_player.btn_fin_annotation.setVisible(True)

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


        self.tree_view_events = self.page.findChild(QtWidgets.QTreeView, "treeView")
        if self.tree_view_events:
            self.tree_view_events.setModel(self.proxy_model)
            self.tree_view_events.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.tree_view_events.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.tree_view_events.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))
            self.tree_view_events.setHeaderHidden(True)
            self.tree_view_events.setColumnHidden(1, True)
            self.tree_view_events.setColumnHidden(2, True)
            self.tree_view_events.header().setStretchLastSection(False)
            self.tree_view_events.header().setSectionResizeMode(
                0, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
            self.tree_view_events.clicked.connect(self.on_video_selected)
            self._bar_delegate = VideoBarDelegate(self.tree_view_events)
            self.tree_view_events.setItemDelegateForColumn(0, self._bar_delegate)

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
        if hasattr(self, 'btn_finir') and self.capture_start_time is None:
            self.btn_finir.setText(self.translate("⏹ FIN D'ÉVÉNEMENT", "⏹ END EVENT"))
        self._rebuild_event_buttons()
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
        self.tree_captures.setColumnWidth(0, 95)
        self.tree_captures.setColumnWidth(1, 60)
        self.tree_captures.setColumnWidth(2, 100)
        self.tree_captures.setColumnWidth(3, 80)
        self.tree_captures.setColumnWidth(5, 68)
        header = self.tree_captures.header()
        for col in (0, 1, 2, 3, 5):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree_captures.setAlternatingRowColors(True)
        self.tree_captures.setRootIsDecorated(False)
        self.tree_captures.setUniformRowHeights(True)
        self.tree_captures.setStyleSheet("""
            QTreeWidget {
                background-color: #14202c;
                alternate-background-color: #182838;
                color: #d4e8f5;
                border: 1px solid #2a4057;
                border-radius: 6px;
                font-size: 12px;
                outline: none;
            }
            QTreeWidget::item {
                height: 42px;
                border-bottom: 1px solid #1e3448;
            }
            QTreeWidget::item:hover {
                background-color: #1e3448;
            }
            QTreeWidget::item:selected {
                background-color: #2778a2;
                color: white;
            }
            QHeaderView::section {
                background-color: #1a2e3a;
                color: #7ec8e3;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 4px;
                border: none;
                border-bottom: 2px solid #2778a2;
            }
            QHeaderView::section:first { border-top-left-radius: 5px; }
            QHeaderView::section:last { border-top-right-radius: 5px; }
        """)
        self.tree_captures.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_captures.customContextMenuRequested.connect(
            lambda pos: self.open_context_menu(pos, self.tree_captures)
        )
        self.tree_captures.itemSelectionChanged.connect(self.on_tree_event_selected)

        self._event_type_delegate = _EventTypeDelegate(lambda: list(self.event_dictionary.keys()))
        self.tree_captures.setItemDelegateForColumn(2, self._event_type_delegate)

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
            return "events_motor"
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
                "events_motor": "Deployment",
                "events_animal": "Fauna / Animal",
                "events_interesting_images": "Interesting Image"
            }
        else:
            mapping = {
                "events_motor": "Déploiement",
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
        for json_key_raw, value in video_obs.items():
            if not isinstance(json_key_raw, str) or not json_key_raw.startswith("events_"):
                continue
            # Rétro-compat : events_deployment → events_motor
            json_key = "events_motor" if json_key_raw == "events_deployment" else json_key_raw
            if not isinstance(value, list) or not value:
                continue
            first_object = value[0]
            if not isinstance(first_object, dict):
                continue
            _RENAME = {"tableau blanc": "ardoise", "whiteboard": "slate"}
            _ARDOISE_VALS = {"ardoise", "slate"}
            if self.current_language == 'en':
                authorized_values = (first_object.get("authorized_values_en")
                                     or first_object.get("authorized_values_fr") or [])
            else:
                authorized_values = (first_object.get("authorized_values_fr")
                                     or first_object.get("authorized_values_en") or [])
            # events_motor n'a pas de authorized_values dans le template : valeurs fixes
            if json_key == "events_motor" and not authorized_values:
                if self.current_language == 'en':
                    authorized_values = ["landing", "takeoff", "analysis_start", "analysis_end",
                                          "motor rotation"]
                else:
                    authorized_values = ["atterrissage", "décollage", "debut_analyse", "fin_analyse",
                                          "rotation moteur"]
            if not isinstance(authorized_values, list):
                continue
            label = self._get_label_from_json_key(json_key)
            self.event_category_labels[json_key] = label
            self.event_key_by_label[label] = json_key
            renamed = []
            for v in authorized_values:
                if v is None:
                    continue
                final = _RENAME.get(str(v).lower(), str(v))
                if final.lower() not in _ARDOISE_VALS:
                    renamed.append(final)
            self.event_dictionary[label] = renamed

    def _capture_timecode_field(self, field_key: str, btn: QtWidgets.QPushButton):
        """Capture le timecode courant et l'écrit dans video_observation.<field_key> du _temp.json."""
        if not self.current_json_path or not os.path.isfile(self.current_json_path):
            return
        if not hasattr(self, 'event_player') or not self.event_player:
            return
        # Vérifier unicité : demander confirmation si déjà posé
        if hasattr(self.event_player, 'timeline'):
            already = any(e.get("_json_key") == field_key for e in self.event_player.timeline.events)
            if already:
                field_label = self.translate("Atterrissage", "Landing") if field_key == "timecode_landing" \
                              else self.translate("Décollage", "Takeoff")
                reply = QtWidgets.QMessageBox.question(
                    self.page,
                    self.translate("Écraser ?", "Overwrite?"),
                    self.translate(
                        f"Un {field_label} est déjà enregistré. Voulez-vous le remplacer ?",
                        f"A {field_label} is already set. Replace it?"
                    ),
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                )
                if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
        pos_ms = self.event_player.timeline.get_current_position() if hasattr(self.event_player, 'timeline') else 0
        h = int(pos_ms // 3600000)
        m = int((pos_ms % 3600000) // 60000)
        s = int((pos_ms % 60000) // 1000)
        timecode = f"{h:02d}:{m:02d}:{s:02d}"
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            obs = data.setdefault("video_observation", {})
            obs.setdefault(field_key, {})["value"] = timecode
            print(f"[TEMP_JSON] {os.path.basename(self.current_json_path)} ← video_observation.{field_key} = {timecode!r}")
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            # Ajout / mise à jour du marqueur sur la timeline
            if hasattr(self, 'event_player') and getattr(self.event_player, 'timeline', None):
                label = self.translate("Atterrissage", "Landing") if field_key == "timecode_landing" \
                        else self.translate("Décollage", "Takeoff")
                tl = self.event_player.timeline
                # Remplace l'ancien marqueur du même champ (unicité)
                tl.events = [e for e in tl.events if e.get("_json_key") != field_key]
                tl.events.append({
                    "start": pos_ms, "end": pos_ms,
                    "title": label,
                    "type": "timecode_marker",
                    "zone": 0,
                    "_json_key": field_key,
                })
                tl.update()
            # Arbre : supprimer ancienne ligne puis ajouter la nouvelle
            if hasattr(self, 'tree_captures') and self.tree_captures:
                for i in range(self.tree_captures.topLevelItemCount() - 1, -1, -1):
                    it = self.tree_captures.topLevelItem(i)
                    if it.text(3) == label:
                        self.tree_captures.takeTopLevelItem(i)
                txt_tc = self.event_player.timeline._format_ms(pos_ms) if hasattr(self.event_player, 'timeline') else timecode
                tree_item = QtWidgets.QTreeWidgetItem([txt_tc, "-", "Déploiement", label, "", ""])
                tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#2778A2")))
                self.tree_captures.addTopLevelItem(tree_item)
                self.add_tree_thumbnail(tree_item, pos_ms)
            # Flash visuel de confirmation
            s_dep = self._ZONE_STYLES[0]
            self._apply_evt_btn_style(btn, s_dep, "selected")
            QtCore.QTimer.singleShot(600, lambda: self._apply_evt_btn_style(btn, s_dep, "normal"))
            if self._on_events_changed:
                self._on_events_changed()
        except Exception as e:
            print(f"[EVENTS] Erreur capture {field_key} : {e}")

    @staticmethod
    def _strip_events_motor_placeholder(events_motor) -> list:
        """Retire l'entrée-modèle vide de events_motor (copiée telle quelle depuis template.json,
        event_id/frame_number toujours null) avant d'y ajouter un vrai événement — sinon elle
        reste indéfiniment dans le tableau à côté des événements réellement capturés."""
        if not isinstance(events_motor, list):
            return []
        return [
            e for e in events_motor
            if isinstance(e, dict) and (e.get("event_id") is not None or e.get("frame_number") is not None)
        ]

    def _capture_motor_rotation_event(self, btn: QtWidgets.QPushButton):
        """Ajoute un événement 'Rotation moteur' au timecode courant dans events_motor.

        Contrairement à Atterrissage/Décollage (champ unique, écrasé à chaque clic),
        une vidéo peut contenir plusieurs rotations moteur : chaque clic ajoute une
        nouvelle entrée dans le tableau plat video_observation.events_motor.
        """
        if not self.current_json_path or not os.path.isfile(self.current_json_path):
            return
        if not hasattr(self, 'event_player') or not self.event_player:
            return
        label = self.translate("Rotation moteur", "Motor rotation")
        pos_ms = self.event_player.timeline.get_current_position() if hasattr(self.event_player, 'timeline') else 0
        fps = self._get_video_fps()
        frame_number = self._ms_to_frame(pos_ms, fps)
        event_uid = self._generate_event_uid()
        timecode = self.event_player.timeline._format_ms(pos_ms) if hasattr(self.event_player, 'timeline') else ""
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            obs = data.setdefault("video_observation", {})
            obs["events_motor"] = self._strip_events_motor_placeholder(obs.get("events_motor"))
            obs["events_motor"].append({
                "event_id": event_uid,
                "time_code": timecode,
                "frame_number": frame_number,
                "description_fr": "Rotation moteur",
                "description_en": "Motor rotation",
                "comment": "",
            })
            print(f"[TEMP_JSON] {os.path.basename(self.current_json_path)} ← events_motor += "
                  f"{{frame_number={frame_number}, time_code={timecode!r}}}")
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            # Marqueur sur la timeline (ajout, pas de remplacement : plusieurs rotations possibles)
            if hasattr(self, 'event_player') and getattr(self.event_player, 'timeline', None):
                tl = self.event_player.timeline
                tl.events.append({
                    "start": pos_ms, "end": pos_ms,
                    "title": label,
                    "type": "timecode_marker",
                    "zone": 0,
                    "_json_key": "events_motor",
                    "_event_uid": event_uid,
                })
                tl.update()
            if hasattr(self, 'tree_captures') and self.tree_captures:
                tree_item = QtWidgets.QTreeWidgetItem([timecode, "-", "Déploiement", label, "", ""])
                tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#2778A2")))
                self.tree_captures.addTopLevelItem(tree_item)
                self.add_tree_thumbnail(tree_item, pos_ms)
            s_dep = self._ZONE_STYLES[0]
            self._apply_evt_btn_style(btn, s_dep, "selected")
            QtCore.QTimer.singleShot(600, lambda: self._apply_evt_btn_style(btn, s_dep, "normal"))
            if self._on_events_changed:
                self._on_events_changed()
        except Exception as e:
            print(f"[EVENTS] Erreur capture rotation moteur : {e}")

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

    # --- Event button panel ---

    _ZONE_STYLES = [
        {  # 0 — Déploiement (bleu)
            "header_bg": "#0d1825", "header_fg": "#7ec8e3",
            "btn_bg": "#0f1e2e", "btn_border": "#2778A2", "btn_fg": "#a0c8e8",
            "btn_hover": "#1a3a5a", "btn_active_bg": "#2778A2",
        },
        {  # 1 — Faune / Animal (rouge)
            "header_bg": "#1a0d0d", "header_fg": "#ff9090",
            "btn_bg": "#1e0f0f", "btn_border": "#D94F38", "btn_fg": "#e89090",
            "btn_hover": "#3a1a1a", "btn_active_bg": "#9a2a1a",
        },
        {  # 2 — Image intéressante (orange)
            "header_bg": "#1a1000", "header_fg": "#ffc97a",
            "btn_bg": "#1e1400", "btn_border": "#E68C14", "btn_fg": "#e8c080",
            "btn_hover": "#3a2800", "btn_active_bg": "#9a5a00",
        },
    ]

    def _initialize_event_dropdown_menus(self):
        """Crée le panneau de sélection d'événements par boutons colorés par catégorie."""
        if not self.choose_event_container:
            return
        if self.choose_event_container.layout() is None:
            menu_layout = QtWidgets.QVBoxLayout(self.choose_event_container)
        else:
            menu_layout = self.choose_event_container.layout()
        menu_layout.setContentsMargins(8, 8, 8, 8)
        menu_layout.setSpacing(6)
        self.choose_event_container.setStyleSheet(
            "QFrame { background-color: #181c24; border: 1px solid #2778a2; border-radius: 14px; }"
        )

        if hasattr(self, 'combo_type_event') and self.combo_type_event is not None:
            return  # Déjà initialisé

        # ── Combos cachés pour compat charger_evenements_du_json ────────
        self.combo_type_event = QtWidgets.QComboBox()
        self.combo_valeur_event = QtWidgets.QComboBox()
        self.combo_type_event.setVisible(False)
        self.combo_valeur_event.setVisible(False)
        self.combo_type_event.currentTextChanged.connect(self.on_event_type_changed)
        self.combo_valeur_event.currentTextChanged.connect(self.on_event_value_changed)

        # ── Bouton CAPTURER caché pour compat _update_capture_mode ──────
        self.btn_capturer = QtWidgets.QPushButton()
        self.btn_capturer.setVisible(False)
        self.btn_capturer.clicked.connect(self.on_capturer_clicked)

        # ── État interne ─────────────────────────────────────────────────
        self._selected_type: str = ""
        self._selected_value: str = ""
        self._active_event_btn = None
        self._event_buttons_all: list = []

        # ── Titre ────────────────────────────────────────────────────────
        self.lbl_title_event = QtWidgets.QLabel(
            self.translate("Sélection d'événement", "Event Selection"))
        self.lbl_title_event.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #7ec8e3; border: none;")
        menu_layout.addWidget(self.lbl_title_event)

        # ── Zone de boutons (scroll) ─────────────────────────────────────
        self._event_btn_scroll = QtWidgets.QScrollArea()
        self._event_btn_scroll.setWidgetResizable(True)
        self._event_btn_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._event_btn_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: #111820; width: 5px; border-radius: 2px; }"
            "QScrollBar::handle:vertical { background: #2a4a62; border-radius: 2px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._event_btn_container = QtWidgets.QWidget()
        self._event_btn_container.setStyleSheet("background: transparent;")
        self._event_btn_layout = QtWidgets.QVBoxLayout(self._event_btn_container)
        self._event_btn_layout.setContentsMargins(2, 2, 2, 2)
        self._event_btn_layout.setSpacing(4)
        self._event_btn_layout.addStretch()
        self._event_btn_scroll.setWidget(self._event_btn_container)
        menu_layout.addWidget(self._event_btn_scroll, stretch=1)

        # ── Séparateur ───────────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #1e3448; max-height: 1px;")
        menu_layout.addWidget(sep)

        # ── Commentaire ──────────────────────────────────────────────────
        self.lbl_commentaire_input = QtWidgets.QLabel(
            self.translate("Commentaire rapide", "Quick Comment"))
        self.lbl_commentaire_input.setStyleSheet(
            "color: #a0b8c8; font-size: 10px; font-weight: bold; border: none;")
        menu_layout.addWidget(self.lbl_commentaire_input)

        self.input_commentaire_event = QtWidgets.QLineEdit()
        self.input_commentaire_event.setPlaceholderText(
            self.translate("Écrivez un commentaire...", "Write a comment here..."))
        self.input_commentaire_event.setStyleSheet(
            "QLineEdit { background-color: #212a35; color: white; border: 1px solid #2778a2;"
            " border-radius: 5px; padding: 3px 6px; font-size: 10px; }"
        )
        menu_layout.addWidget(self.input_commentaire_event)

        # ── Bouton FIN (visible seulement pendant capture durée) ─────────
        self.btn_finir = QtWidgets.QPushButton(self.translate("⏹ FIN D'ÉVÉNEMENT", "⏹ END EVENT"))
        self.btn_finir.setStyleSheet(
            "QPushButton { background-color: #7a1e1e; color: white; font-weight: bold;"
            " border: 2px solid #D94F38; border-radius: 6px; padding: 7px 8px; font-size: 10px; }"
            "QPushButton:hover { background-color: #D94F38; }"
        )
        self.btn_finir.setMinimumHeight(34)
        self.btn_finir.setVisible(False)
        self.btn_finir.clicked.connect(self.on_finir_clicked)
        menu_layout.addWidget(self.btn_finir)

    def _apply_evt_btn_style(self, btn: QtWidgets.QPushButton, s: dict, state: str):
        """Applique le style visuel d'un bouton d'événement (normal / selected / active)."""
        if state == "active":
            style = (
                f"QPushButton {{ background-color: {s['btn_active_bg']}; color: white;"
                f" border: 2px solid white; border-radius: 5px;"
                f" padding: 5px 6px; font-size: 10px; font-weight: bold; }}"
                f"QPushButton:hover {{ background-color: {s['btn_hover']}; }}"
            )
        elif state == "selected":
            style = (
                f"QPushButton {{ background-color: {s['btn_hover']}; color: white;"
                f" border: 2px solid {s['btn_border']}; border-radius: 5px;"
                f" padding: 5px 6px; font-size: 10px; font-weight: bold; }}"
                f"QPushButton:hover {{ background-color: {s['btn_active_bg']}; }}"
            )
        else:
            style = (
                f"QPushButton {{ background-color: {s['btn_bg']}; color: {s['btn_fg']};"
                f" border: 1px solid {s['btn_border']}; border-radius: 5px;"
                f" padding: 5px 6px; font-size: 10px; font-weight: bold; }}"
                f"QPushButton:hover {{ background-color: {s['btn_hover']}; color: white; }}"
            )
        btn.setStyleSheet(style)

    def _rebuild_event_buttons(self):
        """Reconstruit les boutons colorés de sélection d'événements depuis event_dictionary."""
        if not hasattr(self, '_event_btn_layout'):
            return

        layout = self._event_btn_layout
        # Vider tout sauf le stretch final
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._event_buttons_all = []
        self._active_event_btn = None

        # --- Boutons dédiés Atterrissage / Décollage ---
        s_dep = self._ZONE_STYLES[0]  # bleu déploiement
        dep_header = QtWidgets.QLabel(f"  {self.translate('DÉPLOIEMENT', 'DEPLOYMENT').upper()}")
        dep_header.setStyleSheet(
            f"background-color: {s_dep['header_bg']}; color: {s_dep['header_fg']};"
            f" font-size: 9px; font-weight: bold; border-radius: 3px;"
            f" border: 1px solid {s_dep['btn_border']}; padding: 2px 6px;"
        )
        layout.insertWidget(layout.count() - 1, dep_header)

        dep_row_w = QtWidgets.QWidget()
        dep_row_w.setStyleSheet("background: transparent;")
        dep_row_l = QtWidgets.QHBoxLayout(dep_row_w)
        dep_row_l.setContentsMargins(0, 0, 0, 0)
        dep_row_l.setSpacing(4)

        btn_att = QtWidgets.QPushButton(self.translate("Atterrissage", "Landing"))
        btn_att.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self._apply_evt_btn_style(btn_att, s_dep, "normal")
        btn_att.clicked.connect(lambda: self._capture_timecode_field("timecode_landing", btn_att))
        dep_row_l.addWidget(btn_att)

        btn_dec = QtWidgets.QPushButton(self.translate("Décollage", "Takeoff"))
        btn_dec.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self._apply_evt_btn_style(btn_dec, s_dep, "normal")
        btn_dec.clicked.connect(lambda: self._capture_timecode_field("timecode_takeoff", btn_dec))
        dep_row_l.addWidget(btn_dec)

        btn_rot = QtWidgets.QPushButton(self.translate("Rotation moteur", "Motor rotation"))
        btn_rot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self._apply_evt_btn_style(btn_rot, s_dep, "normal")
        btn_rot.clicked.connect(lambda: self._capture_motor_rotation_event(btn_rot))
        dep_row_l.addWidget(btn_rot)

        layout.insertWidget(layout.count() - 1, dep_row_w)

        self._btn_atterrissage = btn_att
        self._btn_decollage = btn_dec
        self._btn_rotation_moteur = btn_rot

        gap0 = QtWidgets.QWidget()
        gap0.setFixedHeight(6)
        gap0.setStyleSheet("background: transparent;")
        layout.insertWidget(layout.count() - 1, gap0)

        # --- Catégories depuis event_dictionary (sans Déploiement) ---
        deployment_keys = {"déploiement", "deployment"}

        if not self.event_dictionary or all(
            k.lower() in deployment_keys for k in self.event_dictionary
        ):
            placeholder = QtWidgets.QLabel(
                self.translate("Aucune catégorie d'événement disponible.",
                               "No event categories available."))
            placeholder.setStyleSheet(
                "color: #3a5568; font-size: 10px; border: none; padding: 8px;")
            placeholder.setWordWrap(True)
            layout.insertWidget(layout.count() - 1, placeholder)
            return

        for cat_label, values in self.event_dictionary.items():
            if not values:
                continue
            # Exclure la catégorie déploiement — gérée par les boutons dédiés ci-dessus
            if cat_label.lower() in deployment_keys:
                continue
            zone_idx = self._zone_index_for_event_type(cat_label)
            s = self._ZONE_STYLES[zone_idx] if zone_idx < len(self._ZONE_STYLES) else self._ZONE_STYLES[0]

            # En-tête de catégorie
            lbl = QtWidgets.QLabel(f"  {cat_label.upper()}")
            lbl.setStyleSheet(
                f"background-color: {s['header_bg']}; color: {s['header_fg']};"
                f" font-size: 9px; font-weight: bold; border-radius: 3px;"
                f" border: 1px solid {s['btn_border']}; padding: 2px 6px;"
            )
            layout.insertWidget(layout.count() - 1, lbl)

            # Grille de boutons (2 par ligne)
            COLS = 2
            row_w = None
            row_l = None
            for i, value in enumerate(values):
                if i % COLS == 0:
                    row_w = QtWidgets.QWidget()
                    row_w.setStyleSheet("background: transparent;")
                    row_l = QtWidgets.QHBoxLayout(row_w)
                    row_l.setContentsMargins(0, 0, 0, 0)
                    row_l.setSpacing(4)
                    layout.insertWidget(layout.count() - 1, row_w)

                btn = QtWidgets.QPushButton(str(value).capitalize())
                btn.setProperty("_zone_s", s)
                btn.setProperty("_cat", cat_label)
                btn.setProperty("_val", str(value))
                btn.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Fixed,
                )
                self._apply_evt_btn_style(btn, s, "normal")
                btn.clicked.connect(
                    lambda _=False, tl=cat_label, v=str(value), b=btn:
                    self._on_event_btn_clicked(tl, v, b)
                )
                row_l.addWidget(btn)
                self._event_buttons_all.append(btn)

            if row_l and len(values) % COLS != 0:
                row_l.addStretch()

            # Espace entre catégories
            gap = QtWidgets.QWidget()
            gap.setFixedHeight(6)
            gap.setStyleSheet("background: transparent;")
            layout.insertWidget(layout.count() - 1, gap)

    def _on_event_btn_clicked(self, type_label: str, value: str, btn: QtWidgets.QPushButton):
        """Gère le clic sur un bouton d'événement : capture immédiate ou armer une durée."""
        self._selected_type = type_label
        self._selected_value = value

        # Réinitialiser le style de tous les boutons
        for b in self._event_buttons_all:
            s = b.property("_zone_s") or self._ZONE_STYLES[0]
            self._apply_evt_btn_style(b, s, "normal")

        s = btn.property("_zone_s") or self._ZONE_STYLES[0]

        if self._is_single_frame_event(type_label, value):
            # Flash visuel puis capture
            self._apply_evt_btn_style(btn, s, "active")
            QtCore.QTimer.singleShot(
                500,
                lambda b=btn: self._apply_evt_btn_style(
                    b, b.property("_zone_s") or self._ZONE_STYLES[0], "normal"
                ) if b else None
            )
            self.on_capturer_clicked()
        else:
            if self.capture_start_time is not None:
                # Annule la capture en cours avant d'en démarrer une nouvelle
                self.capture_start_time = None
                if self._active_event_btn:
                    sb = self._active_event_btn.property("_zone_s") or self._ZONE_STYLES[0]
                    self._apply_evt_btn_style(self._active_event_btn, sb, "normal")

            # Armer la capture de durée
            self._active_event_btn = btn
            self._apply_evt_btn_style(btn, s, "selected")
            self.on_capturer_clicked()  # positionne capture_start_time et affiche btn_finir

    # --- Export UI ---

    def _save_analysis_field(self, field_key: str, value: str):
        """Écrit field_key dans video_observation du JSON courant."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            vob = data.setdefault("video_observation", {})
            if field_key in vob and isinstance(vob[field_key], dict):
                vob[field_key]["value"] = value or None
            else:
                vob[field_key] = {"value": value or None}
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Analyse] Erreur sauvegarde {field_key}: {e}")

    def _load_analysis_fields(self):
        """Peuple les widgets d'analyse depuis le JSON courant."""
        if not self._analysis_widgets:
            return
        data = {}
        if self.current_json_path and os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        vob = data.get("video_observation", {})
        for field_key, widget in self._analysis_widgets.items():
            entry = vob.get(field_key, {})
            val = entry.get("value", "") if isinstance(entry, dict) else (entry or "")
            widget.blockSignals(True)
            widget.setText(str(val) if val is not None else "")
            widget.blockSignals(False)

    def _initialize_export_ui(self):
        """Crée le bouton d'export, la barre de progression et le label de statut."""
        if not self.export_container:
            return
        layout = self.export_container.layout() or QtWidgets.QVBoxLayout(self.export_container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.export_button = QtWidgets.QPushButton("EXPORTER LES ÉVÉNEMENTS", self.export_container)
        self.export_button.setStyleSheet(
            "QPushButton { background-color: #e68c14; color: white; font-weight: bold; "
            "font-size: 13px; border: 1px solid #f09624; border-radius: 6px; padding: 8px 10px; }"
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
        self.export_status_label.setStyleSheet("color: #F2BFB4; font-size: 12px; border: none;")
        self.export_status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)

        layout.addWidget(self.export_button)
        layout.addWidget(self.export_progress)
        layout.addWidget(self.export_status_label)

        # ── Analyse vidéo ────────────────────────────────────────────────
        sep_analyse = QtWidgets.QFrame()
        sep_analyse.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep_analyse.setStyleSheet("border: none; border-top: 1px solid #1e3448; max-height: 1px;")
        layout.addWidget(sep_analyse)

        lbl_analyse = QtWidgets.QLabel("Analyse vidéo")
        lbl_analyse.setStyleSheet("color: #7ec8e3; font-size: 15px; font-weight: bold; border: none;")
        layout.addWidget(lbl_analyse)

        _lbl_s = "color: #7ec8e3; font-size: 14px; border: none;"
        _inp_s = ("background-color: #162433; color: #F2BFB4; border: 1px solid #2a4057;"
                  " border-radius: 4px; padding: 6px 8px; font-size: 14px;")

        analyse_grid = QtWidgets.QWidget()
        analyse_grid.setStyleSheet("background: transparent;")
        analyse_grid.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        ag = QtWidgets.QGridLayout(analyse_grid)
        ag.setContentsMargins(0, 8, 0, 8)
        ag.setHorizontalSpacing(10)
        ag.setVerticalSpacing(16)

        def _albl(text):
            l = QtWidgets.QLabel(text)
            l.setStyleSheet(_lbl_s)
            return l

        def _ainput(field_key, placeholder=""):
            w = QtWidgets.QLineEdit()
            w.setPlaceholderText(placeholder)
            w.setStyleSheet(_inp_s)
            w.setMinimumHeight(30)
            w.editingFinished.connect(lambda fk=field_key, widget=w: self._save_analysis_field(fk, widget.text()))
            self._analysis_widgets[field_key] = w
            return w

        ag.addWidget(_albl("Analyseur poisson"), 0, 0)
        ag.addWidget(_ainput("fish_annotator", "ex : Jean Dupont"), 0, 1)
        ag.addWidget(_albl("Analyseur habitat"), 1, 0)
        ag.addWidget(_ainput("habitat_annotator", "ex : Marie Martin"), 1, 1)
        ag.addWidget(_albl("Substrat"), 2, 0)
        ag.addWidget(_ainput("substrat", "ex : Sable, Roche, Herbier…"), 2, 1)
        ag.addWidget(_albl("Visibilité (m)"), 3, 0)
        ag.addWidget(_ainput("estimated_visibility", "ex : 5"), 3, 1)

        dist_w = QtWidgets.QWidget()
        dist_w.setStyleSheet("background: transparent;")
        dist_row = QtWidgets.QHBoxLayout(dist_w)
        dist_row.setContentsMargins(0, 0, 0, 0)
        dist_row.setSpacing(6)
        lbl_min = QtWidgets.QLabel("min")
        lbl_min.setStyleSheet(_lbl_s)
        lbl_max = QtWidgets.QLabel("max")
        lbl_max.setStyleSheet(_lbl_s)
        dist_row.addWidget(lbl_min)
        dist_row.addWidget(_ainput("distance_min", "0"))
        dist_row.addWidget(lbl_max)
        dist_row.addWidget(_ainput("distance_max", "5"))
        ag.addWidget(_albl("Distance analysable (m)"), 4, 0)
        ag.addWidget(dist_w, 4, 1)

        layout.addWidget(analyse_grid)
        layout.addStretch(1)

        self.export_button.clicked.connect(self.on_export_segment_clicked)
        self.export_worker = None

    def _update_export_button_state(self):
        """Active le bouton Export seulement si une vidéo est chargée."""
        has_video = bool(self.current_video_path)
        if hasattr(self, 'export_button') and self.export_button:
            self.export_button.setEnabled(has_video)

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
        if any(kw in value_lower for kw in [
            "atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff", "take_off",
            "ardoise", "slate", "tableau blanc", "whiteboard",
            "début annotation", "debut annotation", "annotation start", "début_annotation",
            "fin annotation", "annotation end", "fin_annotation",
            "rotation moteur", "motor rotation",
        ]):
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

    def _is_annotation_start_event(self, value: str) -> bool:
        v = (value or "").strip().lower()
        return any(kw in v for kw in ["début annotation", "debut annotation", "annotation start", "début_annotation", "annotation_start"])

    def _is_annotation_end_event(self, value: str) -> bool:
        v = (value or "").strip().lower()
        return any(kw in v for kw in ["fin annotation", "annotation end", "fin_annotation", "annotation_end"])

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
        """Aucune action requise : la gestion du mode est assurée par _on_event_btn_clicked."""
        pass

    # --- Capture button handlers ---

    def on_capturer_clicked(self):
        """Enregistre un événement ponctuel ou démarre la capture d'un événement avec durée."""
        if not hasattr(self, 'event_player') or self.event_player is None:
            return
        current_type = getattr(self, '_selected_type', '') or self.combo_type_event.currentText()
        current_value = getattr(self, '_selected_value', '') or self.combo_valeur_event.currentText()
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
            # Marquer le bouton actif en "active" et afficher FIN
            if hasattr(self, '_active_event_btn') and self._active_event_btn:
                s = self._active_event_btn.property("_zone_s") or self._ZONE_STYLES[0]
                self._apply_evt_btn_style(self._active_event_btn, s, "active")
            if hasattr(self, 'btn_finir'):
                self.btn_finir.setText(
                    self.translate(f"⏹ FIN  (début {time_str})", f"⏹ END  (start {time_str})")
                )
                self.btn_finir.setVisible(True)

    def on_finir_clicked(self):
        """Clôture la capture en cours et enregistre l'événement avec sa durée start→end."""
        if not hasattr(self, 'event_player') or self.capture_start_time is None:
            return
        current_type = getattr(self, '_selected_type', '') or self.combo_type_event.currentText()
        current_value = getattr(self, '_selected_value', '') or self.combo_valeur_event.currentText()
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
        # Réinitialiser le bouton actif et cacher FIN
        if hasattr(self, '_active_event_btn') and self._active_event_btn:
            s = self._active_event_btn.property("_zone_s") or self._ZONE_STYLES[0]
            self._apply_evt_btn_style(self._active_event_btn, s, "normal")
            self._active_event_btn = None
        if hasattr(self, 'btn_finir'):
            self.btn_finir.setVisible(False)
            self.btn_finir.setText(self.translate("⏹ FIN D'ÉVÉNEMENT", "⏹ END EVENT"))

    def _saisir_ardoise(self):
        """Capture un événement ardoise ponctuel à la position courante du lecteur."""
        if not hasattr(self, 'event_player') or self.event_player is None:
            return
        value = "ardoise" if self.current_language == 'fr' else "slate"
        deploy_label = self._get_label_from_json_key("events_motor")
        pos_ms = self.event_player.timeline.get_current_position() if hasattr(self.event_player, 'timeline') else 0
        time_str = self.event_player.timeline._format_ms(pos_ms) if hasattr(self.event_player, 'timeline') else "00:00:00"
        new_evt = {
            "start": pos_ms, "end": pos_ms,
            "title": f"Pic: {value}",
            "type": "custom_event",
            "zone": 0,
            "single_frame": True,
            "comment": "",
            "_json_key": "events_motor",
            "_event_uid": self._generate_event_uid()
        }
        self.event_player.timeline.events.append(new_evt)
        self.event_player.timeline.update()
        if hasattr(self, 'tree_captures') and self.tree_captures:
            clean_cat = deploy_label.split(' ')[0]
            tree_item = QtWidgets.QTreeWidgetItem(
                [time_str, "-", clean_cat, value, "", ""]
            )
            tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#e68c14")))
            self.tree_captures.addTopLevelItem(tree_item)
            self.add_tree_thumbnail(tree_item, pos_ms)
        self.save_event_to_json(new_evt, deploy_label)

    def _saisir_debut_annotation(self):
        """Capture un événement début annotation à la position courante."""
        self._saisir_annotation_event(
            "début annotation", "annotation start",
            self.event_player.btn_debut_annotation
        )

    def _saisir_fin_annotation(self):
        """Capture un événement fin annotation à la position courante."""
        self._saisir_annotation_event(
            "fin annotation", "annotation end",
            self.event_player.btn_fin_annotation
        )

    def _saisir_annotation_event(self, value_fr: str, value_en: str, button=None):
        """Capture un événement annotation ponctuel et le sauvegarde dans le JSON."""
        if not hasattr(self, 'event_player') or self.event_player is None:
            return
        value = value_fr if self.current_language == 'fr' else value_en
        deploy_label = self._get_label_from_json_key("events_motor")
        pos_ms = self.event_player.timeline.get_current_position() if hasattr(self.event_player, 'timeline') else 0
        time_str = self.event_player.timeline._format_ms(pos_ms) if hasattr(self.event_player, 'timeline') else "00:00:00"
        new_evt = {
            "start": pos_ms, "end": pos_ms,
            "title": f"Pic: {value}",
            "type": "custom_event",
            "zone": 0,
            "single_frame": True,
            "comment": "",
            "_json_key": "events_motor",
            "_event_uid": self._generate_event_uid()
        }
        self.event_player.timeline.events.append(new_evt)
        self.event_player.timeline.update()
        if hasattr(self, 'tree_captures') and self.tree_captures:
            clean_cat = deploy_label.split(' ')[0]
            tree_item = QtWidgets.QTreeWidgetItem([time_str, "-", clean_cat, value, "", ""])
            tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#2778A2")))
            self.tree_captures.addTopLevelItem(tree_item)
            self.add_tree_thumbnail(tree_item, pos_ms)
        self.save_event_to_json(new_evt, deploy_label)
        if button is not None:
            orig_text = button.text()
            button.setText(f"✓ {time_str}")
            QtCore.QTimer.singleShot(2000, lambda: button.setText(orig_text))

    # --- Video selection ---

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Charge la vidéo sélectionnée, reconstruit la timeline avec les événements JSON et moteur."""
        original_index = self.proxy_model.mapToSource(index)
        item = self.video_model.itemFromIndex(original_index.siblingAtColumn(0))
        if not item or not item.data(QtCore.Qt.ItemDataRole.UserRole):
            return

        self.current_video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        video_dir = os.path.dirname(self.current_video_path)
        self.current_json_path = resolve_video_json_path(self._working_dir, self.current_video_path)
        if self._on_video_focused:
            self._on_video_focused(item.text())

        is_stereo, video_to_load = check_stereo_status(self.current_video_path)

        if hasattr(self, 'tree_captures') and self.tree_captures:
            self.tree_captures.blockSignals(True)
            self.tree_captures.clear()

        self.capture_start_time = None
        self._selected_type = ""
        self._selected_value = ""
        if hasattr(self, '_active_event_btn') and self._active_event_btn:
            s = self._active_event_btn.property("_zone_s") or self._ZONE_STYLES[0]
            self._apply_evt_btn_style(self._active_event_btn, s, "normal")
            self._active_event_btn = None
        if hasattr(self, 'btn_finir'):
            self.btn_finir.setVisible(False)
        if hasattr(self, 'event_player') and self.event_player:
            self.event_player.btn_debut_annotation.setEnabled(True)
            self.event_player.btn_fin_annotation.setEnabled(True)

        self.charger_evenements_du_json()
        self._nettoyer_json_misplaced_events()
        self._update_export_button_state()
        self._load_analysis_fields()

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

                for json_key in ["events_motor", "events_animal", "events_interesting_images"]:
                    # Rétro-compat : lire events_deployment si events_motor absent
                    raw = video_obs.get(json_key) or (video_obs.get("events_deployment") if json_key == "events_motor" else None)
                    if not isinstance(raw, list) or not raw:
                        continue
                    # events_motor : tableau plat (nouveau) ou wrapper values (ancien events_deployment)
                    if json_key == "events_motor":
                        first = raw[0] if raw else {}
                        if isinstance(first, dict) and "values" in first:
                            # ancien format events_deployment
                            old_vals = first.get("values", [])
                            values_list = [
                                {"frame_number": v.get("frame_number_start", 0),
                                 "description_fr": v.get("value", ""),
                                 "event_id": v.get("event_id"),
                                 "comment": v.get("comment", "")}
                                for v in old_vals if isinstance(v, dict)
                            ]
                        else:
                            values_list = [v for v in raw if isinstance(v, dict) and "frame_number" in v]
                    else:
                        values_list = raw[0].get("values", []) if isinstance(raw[0], dict) else []
                    category_name = self._get_label_from_json_key(json_key)

                    for val in values_list:
                        if json_key == "events_motor":
                            frame_start = val.get("frame_number", 0)
                            frame_end = frame_start
                        else:
                            frame_start = val.get("frame_number_start", 0)
                            frame_end = val.get("frame_number_end", 0)
                        # events_motor utilise description_fr comme label
                        if json_key == "events_motor":
                            value = val.get("description_fr") or val.get("value", "rotation")
                        else:
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
                # --- Marqueurs timecode_landing / timecode_takeoff ---
                _TC_MARKERS = {
                    "timecode_landing":  self.translate("Atterrissage", "Landing"),
                    "timecode_takeoff":  self.translate("Décollage",    "Takeoff"),
                }
                for tc_key, tc_label in _TC_MARKERS.items():
                    tc_val = (video_obs.get(tc_key) or {}).get("value")
                    if not tc_val:
                        continue
                    try:
                        parts = str(tc_val).split(":")
                        if len(parts) == 3:
                            tc_ms = int(parts[0])*3600000 + int(parts[1])*60000 + int(parts[2])*1000
                        elif len(parts) == 2:
                            tc_ms = int(parts[0])*60000 + int(parts[1])*1000
                        else:
                            continue
                        evt_dict = {
                            "start": tc_ms, "end": tc_ms,
                            "title": tc_label,
                            "type": "timecode_marker",
                            "zone": 0,
                            "_json_key": tc_key,
                        }
                        timeline_events.append(evt_dict)
                        if hasattr(self, 'tree_captures') and self.tree_captures:
                            txt_tc = self.event_player.timeline._format_ms(tc_ms)
                            tree_item = QtWidgets.QTreeWidgetItem(
                                [txt_tc, "-", "Déploiement", tc_label, "", ""]
                            )
                            tree_item.setFlags(tree_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                            tree_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#2778A2")))
                            self.tree_captures.addTopLevelItem(tree_item)
                            self.add_tree_thumbnail(tree_item, tc_ms)
                    except Exception:
                        pass

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

    def charger_evenements_du_json(self):
        """Lit le JSON vidéo courant, construit event_dictionary et reconstruit les boutons."""
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
        self._rebuild_event_buttons()

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
                json_key = "events_motor"
                event_dict["_json_key"] = "events_motor"

            fps = self._get_video_fps()
            frame_start = self._ms_to_frame(event_dict["start"], fps)
            frame_end = self._ms_to_frame(event_dict["end"], fps)
            event_uid = self._ensure_event_uid(event_dict)
            label = event_dict["title"].replace("Pic: ", "")

            if json_key == "events_motor":
                # Structure plate : tableau direct d'événements instantanés
                data["video_observation"][json_key] = self._strip_events_motor_placeholder(
                    data["video_observation"].get(json_key))
                saved_value = {
                    "event_id": event_uid,
                    "time_code": self.event_player.timeline._format_ms(event_dict["start"]),
                    "frame_number": frame_start,
                    "description_fr": label,
                    "description_en": label,
                    "comment": event_dict.get("comment", "")
                }
                flat_list = data["video_observation"][json_key]
                existing_index = next((i for i, v in enumerate(flat_list) if v.get("event_id") == event_uid), -1)
                if existing_index == -1:
                    tolerance = max(1, int(fps * 0.25))
                    existing_index = next(
                        (i for i, v in enumerate(flat_list)
                         if v.get("description_fr") == label and abs(v.get("frame_number", 0) - frame_start) <= tolerance),
                        -1
                    )
                if existing_index != -1:
                    flat_list[existing_index] = saved_value
                else:
                    flat_list.append(saved_value)
            else:
                if json_key not in data["video_observation"] or not data["video_observation"][json_key]:
                    data["video_observation"][json_key] = [{"authorized_values_fr": [], "values": []}]
                saved_value = {
                    "event_id": event_uid,
                    "time_code_start": self.event_player.timeline._format_ms(event_dict["start"]),
                    "time_code_end": self.event_player.timeline._format_ms(event_dict["end"]),
                    "frame_number_start": frame_start,
                    "frame_number_end": frame_end,
                    "description_fr": None,
                    "description_en": None,
                    "value": label,
                    "comment": event_dict.get("comment", "")
                }
                values_list = data["video_observation"][json_key][0].get("values", [])
                existing_index = next((i for i, v in enumerate(values_list) if v.get("event_id") == event_uid), -1)
                if existing_index == -1:
                    tolerance = max(1, int(fps * 0.25))
                    existing_index = next(
                        (i for i, v in enumerate(values_list)
                         if v.get("value") == label and abs(v.get("frame_number_start", 0) - frame_start) <= tolerance),
                        -1
                    )
                if existing_index != -1:
                    values_list[existing_index] = saved_value
                else:
                    values_list.append(saved_value)
                data["video_observation"][json_key][0]["values"] = values_list

            event_dict["_json_key"] = json_key
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            if self._on_events_changed:
                self._on_events_changed()
        except Exception as e:
            print(f"[BACKEND] Exception writing JSON: {e}")

    def delete_event_from_json(self, event_dict: dict):
        """Supprime l'événement correspondant du JSON vidéo courant (tolérance d'un quart de seconde)."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        # Cas spécial : marqueurs timecode_landing / timecode_takeoff → remettre à null
        json_key = event_dict.get("_json_key", "")
        if json_key in ("timecode_landing", "timecode_takeoff"):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                obs = data.get("video_observation", {})
                if json_key in obs and isinstance(obs[json_key], dict):
                    obs[json_key]["value"] = None
                print(f"[TEMP_JSON] {os.path.basename(self.current_json_path)} ← video_observation.{json_key} = null")
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                if self._on_events_changed:
                    self._on_events_changed()
            except Exception as e:
                print(f"[BACKEND] Error clearing {json_key}: {e}")
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            video_obs = data.get("video_observation", {})
            target_value = event_dict["title"].replace("Pic: ", "")
            fps = self._get_video_fps()
            target_frame_start = self._ms_to_frame(event_dict["start"], fps)
            tolerance = max(1, int(fps * 0.25))
            for json_key in ["events_motor", "events_animal", "events_interesting_images"]:
                if json_key not in video_obs or not video_obs[json_key]:
                    continue
                if json_key == "events_motor":
                    video_obs[json_key] = [
                        v for v in video_obs[json_key]
                        if not (v.get("description_fr") == target_value
                                and abs(v.get("frame_number", 0) - target_frame_start) <= tolerance)
                    ]
                else:
                    values_list = video_obs[json_key][0].get("values", [])
                    video_obs[json_key][0]["values"] = [
                        v for v in values_list
                        if not (v.get("value") == target_value
                                and abs(v.get("frame_number_start", 0) - target_frame_start) <= tolerance)
                    ]
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            if self._on_events_changed:
                self._on_events_changed()
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

        display_type = getattr(self, '_selected_type', '') or self.combo_type_event.currentText()
        if "_json_key" in modified_event:
            display_type = self._get_label_from_json_key(modified_event["_json_key"])
        self.save_event_to_json(modified_event, display_type)

    def on_arbre_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int):
        """Persiste les éditions directes de l'arbre (type col 2, commentaire col 4) vers le JSON."""
        if column == 2:
            self._move_event_to_category(item, item.text(2))
            return
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
            for json_key in ["events_motor", "events_animal", "events_interesting_images"]:
                if json_key not in video_obs or not video_obs[json_key]:
                    continue
                if json_key == "events_motor":
                    items = video_obs[json_key]
                    key_field = "description_fr"
                else:
                    items = video_obs[json_key][0].get("values", [])
                    key_field = "value"
                for val in items:
                    if val.get(key_field) == target_value:
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

    def _move_event_to_category(self, item: QtWidgets.QTreeWidgetItem, new_label: str):
        """Déplace un événement vers une nouvelle catégorie dans la timeline et le JSON."""
        new_json_key = self._get_json_key_from_label(new_label)
        value = item.text(3)

        if hasattr(self, 'event_player') and getattr(self.event_player, 'timeline', None):
            for evt in self.event_player.timeline.events:
                if evt.get("title", "").replace("Pic: ", "") == value:
                    evt["_json_key"] = new_json_key
                    evt["zone"] = self._zone_index_for_event_type(new_label)
                    self.event_player.timeline.update()
                    break

        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            video_obs = data.get("video_observation", {})

            moved_entry = None
            for json_key in ["events_motor", "events_animal", "events_interesting_images"]:
                if json_key == new_json_key:
                    continue
                cat = video_obs.get(json_key)
                if not isinstance(cat, list) or not cat:
                    continue
                values = cat[0].get("values", [])
                for i, v in enumerate(values):
                    if v.get("value") == value:
                        moved_entry = values.pop(i)
                        break
                if moved_entry is not None:
                    break

            if moved_entry is not None:
                if new_json_key not in video_obs or not isinstance(video_obs[new_json_key], list) or not video_obs[new_json_key]:
                    video_obs[new_json_key] = [{"authorized_values_fr": [], "values": []}]
                video_obs[new_json_key][0].setdefault("values", []).append(moved_entry)
                data["video_observation"] = video_obs
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[MOVE CATEGORY] Error: {e}")

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
        thumbnail_label.setStyleSheet(
            "background-color: #0c141c; margin: 3px; border: 1px solid #2a4057; border-radius: 4px;")
        vignette_pixmap = None
        if self.current_video_path and os.path.exists(self.current_video_path):
            frame_rgb = extract_frame_at_time(self.current_video_path, timestamp_ms / 1000.0)
            if frame_rgb is not None:
                h, w, ch = frame_rgb.shape
                q_img = QtGui.QImage(frame_rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
                vignette_pixmap = QtGui.QPixmap.fromImage(q_img)
        if vignette_pixmap and not vignette_pixmap.isNull():
            thumbnail_label.setPixmap(
                vignette_pixmap.scaled(58, 32, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                       QtCore.Qt.TransformationMode.SmoothTransformation)
            )
        else:
            thumbnail_label.setText("—")
            thumbnail_label.setStyleSheet(
                "background-color: #0c141c; margin: 3px; border: 1px solid #2a4057; border-radius: 4px;"
                " color: #4a6478; font-size: 10px; font-weight: bold;")
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
            event_categories = [k for k in video_obs if isinstance(k, str) and k.startswith("events_") and k != "events_motor"]
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
                    if "events_motor" not in video_obs or not video_obs["events_motor"]:
                        video_obs["events_motor"] = [{"authorized_values_fr": [], "values": []}]
                    existing_deploy = video_obs["events_motor"][0].get("values", [])
                    for evt in deployment_events:
                        if not any(
                            e.get("value") == evt.get("value")
                            and e.get("frame_number_start") == evt.get("frame_number_start")
                            for e in existing_deploy
                        ):
                            existing_deploy.append(evt)
                    video_obs["events_motor"][0]["values"] = existing_deploy
            if modified:
                data["video_observation"] = video_obs
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                if self._on_events_changed:
                    self._on_events_changed()
        except Exception as e:
            print(f"[CLEANUP] Error: {e}")

    # --- Export ---

    def _read_events_motor(self, video_obs: dict) -> list:
        """Retourne la liste normalisée des événements 'events_motor' (frame_number, description_fr),
        avec repli sur l'ancien format 'events_deployment' (wrapper {"values": [...]})
        pour les JSON pas encore migrés vers le nouveau format à plat."""
        raw = video_obs.get("events_motor") or video_obs.get("events_deployment")
        if not isinstance(raw, list) or not raw:
            return []
        first = raw[0] if raw else {}
        if isinstance(first, dict) and "values" in first:
            old_vals = first.get("values", [])
            return [
                {"frame_number": v.get("frame_number_start", 0),
                 "description_fr": v.get("value", "")}
                for v in old_vals if isinstance(v, dict)
            ]
        return [v for v in raw if isinstance(v, dict) and "frame_number" in v]

    def _get_export_segment_bounds(self):
        """Lit les frames atterrissage et décollage du JSON et retourne (start_ms, end_ms), ou None."""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            return None
        # Utilise le JSON actif (répertoire de travail si disponible, sinon source)
        json_path = self.current_json_path or get_video_json_path(self.current_video_path)
        if not json_path or not os.path.exists(json_path):
            return None
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            events_motor = self._read_events_motor(json_data.get('video_observation', {}))
            if not events_motor:
                return None
            landing_frame = takeoff_frame = None
            for item in events_motor:
                if not isinstance(item, dict):
                    continue
                val = str(item.get('description_fr') or item.get('value', '')).strip()
                fn = item.get('frame_number')
                if fn is None:
                    continue
                if self._is_landing_event(val) and landing_frame is None:
                    landing_frame = fn
                elif self._is_takeoff_event(val) and takeoff_frame is None:
                    takeoff_frame = fn
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

    def _get_annotation_segment_bounds(self):
        """Lit les frames début/fin annotation du JSON et retourne (start_ms, end_ms), ou None."""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            return None
        json_path = self.current_json_path or get_video_json_path(self.current_video_path)
        if not json_path or not os.path.exists(json_path):
            return None
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            events_motor = self._read_events_motor(json_data.get('video_observation', {}))
            if not events_motor:
                return None
            start_frame = end_frame = None
            for item in events_motor:
                if not isinstance(item, dict):
                    continue
                val = str(item.get('description_fr') or item.get('value', '')).strip()
                fn = item.get('frame_number')
                if fn is None:
                    continue
                if self._is_annotation_start_event(val) and start_frame is None:
                    start_frame = fn
                elif self._is_annotation_end_event(val) and end_frame is None:
                    end_frame = fn
            if start_frame is None or end_frame is None:
                return None
            cap = cv2.VideoCapture(self.current_video_path)
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.release()
            start_ms = ((float(int(start_frame)) - 1.0) / float(video_fps)) * 1000.0
            end_ms = ((float(int(end_frame)) - 1.0) / float(video_fps)) * 1000.0
            return start_ms, end_ms
        except Exception as e:
            print(f"[EXPORT] Annotation bounds exception: {e}")
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

        parent_video_directory = os.path.dirname(self.current_video_path)
        session_root = os.path.dirname(parent_video_directory)   # = dossier campagne
        json_path = os.path.join(session_root, "matrices.json")
        is_stereo_mode = getattr(self.event_player, "is_stereo", False)
        video_out_dir = self._get_video_out_dir(self.current_video_path)

        dialog = ExportOptionsDialog(self.page, is_stereo=is_stereo_mode)
        dialog.set_language(self.current_language)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        options = dialog.get_processing_options()
        export_range = options.get("export_range", "landing_takeoff")
        if export_range == "annotation":
            bounds = self._get_annotation_segment_bounds()
            missing_msg = self.translate(
                "Événements 'début annotation' et 'fin annotation' introuvables dans le JSON.",
                "'annotation start' and 'annotation end' events not found in the JSON."
            )
        else:
            bounds = self._get_export_segment_bounds()
            missing_msg = self.translate("Bornes temporelles manquantes.", "Missing time bounds.")

        if bounds is None:
            QtWidgets.QMessageBox.warning(self.page,
                self.translate("Export Impossible", "Export Impossible"),
                missing_msg)
            return

        target_fps = options.get("target_fps", 5)
        apply_he = options.get("apply_he", False)
        apply_dh = options.get("apply_dh", False)
        is_water = options.get("is_water", False)
        apply_rectify = options.get("apply_rectify", False)
        include_images = options.get("include_images", True)
        event_categories = options.get("event_categories", ["events_motor", "events_animal", "events_interesting_images"])

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
        self._export_event_categories = event_categories

        if not include_images:
            self.export_button.setEnabled(False)
            self.export_status_label.setText(self.translate("Génération du CSV...", "Generating CSV..."))
            self._copy_companion_files(self.current_video_path)
            ok = self._generate_events_csv_no_images(self.current_video_path, start_ms, end_ms, event_categories)
            msg = (self.translate("CSV d'événements généré.", "Events CSV generated.")
                   if ok else
                   self.translate("Échec de la génération du CSV.", "Failed to generate CSV."))
            self.export_status_label.setText(msg)
            self.export_button.setEnabled(bool(self.current_video_path))
            return

        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)
        self.export_status_label.setText(self.translate(f"Export en cours ({target_fps} FPS)...", f"Exporting ({target_fps} FPS)..."))
        self.export_button.setEnabled(False)

        self.export_worker = ExportWorker(
            video_path=self.current_video_path,
            base_output_dir=video_out_dir,
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

    def _copy_companion_files(self, video_path: str):
        """Copie uniquement le JSON source dans le sous-dossier de travail (si absent)."""
        if not self._working_dir:
            return
        src_dir = os.path.dirname(os.path.normpath(video_path))
        dst_dir = self._get_video_out_dir(video_path)
        os.makedirs(dst_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(video_path))[0]
        json_fname = f"{stem}.json"
        src_file = os.path.join(src_dir, json_fname)
        if os.path.isfile(src_file):
            dst_file = os.path.join(dst_dir, json_fname)
            if not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)

    def _on_export_finished(self, saved_count: int):
        """Affiche le résultat de l'export et génère le CSV d'événements."""
        self._copy_companion_files(self.current_video_path)
        message = self.translate(f"Export terminé : {saved_count} images sauvegardées.", f"Export complete: {saved_count} images saved.")
        categories = getattr(self, '_export_event_categories', ["events_motor", "events_animal", "events_interesting_images"])
        if self._generate_events_csv(self.current_video_path, self.export_start_ms, self.export_end_ms, categories):
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

    def set_working_dir(self, path: str):
        """Définit le répertoire de travail IHM pour les exports."""
        self._working_dir = path
        if hasattr(self, '_bar_delegate'):
            self._bar_delegate.set_working_dir(path)

    def _get_video_out_dir(self, video_path: str) -> str:
        """Retourne le dossier de sortie pour une vidéo : répertoire de travail si défini, sinon fallback campagne."""
        if self._working_dir:
            return get_working_video_dir(self._working_dir, video_path)
        parent_dir = os.path.dirname(os.path.normpath(video_path))
        campaign_folder = os.path.dirname(parent_dir)
        return get_video_output_dir(campaign_folder, video_path)

    def _generate_events_csv_no_images(self, video_path, start_ms, end_ms, event_categories=None):
        """Génère events_VIAME.csv avec références vidéo+frame, sans lot d'images."""
        if event_categories is None:
            event_categories = ['events_motor', 'events_animal', 'events_interesting_images']
        template_json_path = get_video_json_path(video_path)
        video_out = self._get_video_out_dir(video_path)
        events_csv_path = os.path.normpath(os.path.join(video_out, "events_VIAME.csv"))
        parent_dir = os.path.dirname(os.path.normpath(video_path))

        if not os.path.exists(template_json_path):
            return False
        try:
            with open(template_json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            cap = cv2.VideoCapture(video_path)
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.release()

            video_obs = json_data.get('video_observation', {})
            video_name = os.path.basename(video_path)
            start_frame = int((start_ms / 1000.0) * video_fps)

            events_list = []
            track_id = 0
            for category in event_categories:
                raw = video_obs.get(category)
                if not raw:
                    continue
                if category == "events_motor":
                    items = [v for v in raw if isinstance(v, dict) and "frame_number" in v]
                    for item in items:
                        f = item.get('frame_number')
                        name = str(item.get('description_fr', 'rotation')).strip()
                        if f is not None:
                            f = int(f)
                            events_list.append({'id': track_id, 'start': f, 'end': f, 'name': name})
                            track_id += 1
                else:
                    for item in raw[0].get('values', []) if isinstance(raw[0], dict) else []:
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
            os.makedirs(video_out, exist_ok=True)
            with open(events_csv_path, 'w', newline='', encoding='utf-8') as f:
                f.write(
                    "# 1: Detection or Track-id,2: Video or Image Identifier,3: Unique Frame Identifier,"
                    "4-7: Img-bbox(TL_x,TL_y,BR_x,BR_y),8: Detection or Length Confidence,"
                    "9: Target Length (0 or -1 if invalid),10-11+: Repeated Species,Confidence Pairs or Attributes\n"
                )
                f.write(
                    f"# metadata,fps: {video_fps:.1f},\"exported_by: \"\"dive:kosmos\"\"\","
                    f"\"exported_time: \"\"{datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}\"\"\"\n"
                )
                for ev in events_list:
                    for frame in range(ev['start'], ev['end'] + 1):
                        f.write(f"{ev['id']},{video_name},{frame},0,0,0,0,1,-1,{ev['name']},1,\n")
                for m_ev in motor_events:
                    f_s = int(m_ev['timestamp'] * video_fps)
                    f_e = int((m_ev['timestamp'] + m_ev['duration']) * video_fps)
                    for frame in range(f_s, f_e + 1):
                        f.write(f"{m_ev['track_id']},{video_name},{frame},0,0,0,0,1,-1,{m_ev['type']},1,\n")
            return True
        except Exception as e:
            print(f"[CSV NO-IMG ERROR] {e}")
            return False

    def _generate_events_csv(self, video_path, start_ms, end_ms, event_categories=None):
        """Génère events_VIAME.csv dans le sous-dossier vidéo du répertoire de travail."""
        if event_categories is None:
            event_categories = ['events_motor', 'events_animal', 'events_interesting_images']
        parent_dir = os.path.dirname(os.path.normpath(video_path))
        template_json_path = get_video_json_path(video_path)
        video_out = self._get_video_out_dir(video_path)
        events_csv_path = os.path.normpath(os.path.join(video_out, "events_VIAME.csv"))
        img_dir_root_dehaze = os.path.normpath(os.path.join(video_out, "img_dehaze"))
        img_dir_root = img_dir_root_dehaze if os.path.exists(img_dir_root_dehaze) else \
                       os.path.normpath(os.path.join(video_out, "img"))
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
            for category in event_categories:
                cat_data = video_obs.get(category, [])
                if not isinstance(cat_data, list) or not cat_data:
                    continue
                if category == "events_motor":
                    for item in [v for v in cat_data if isinstance(v, dict) and "frame_number" in v]:
                        f = item.get('frame_number')
                        name = str(item.get('description_fr', 'rotation')).strip()
                        if f is not None:
                            f = int(f)
                            events_list.append({'id': track_id, 'start': f, 'end': f, 'name': name})
                            track_id += 1
                else:
                    for item in cat_data[0].get('values', []) if isinstance(cat_data[0], dict) else []:
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
