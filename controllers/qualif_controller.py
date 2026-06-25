import os
import io
import json
import math
import shutil
import folium

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWebChannel import QWebChannel

from services.video_service import get_all_mp4_files, check_stereo_status
from services.campaign_service import (
    get_video_gps_coords, get_video_json_path, get_working_video_json_path,
    get_working_video_dir, sync_video_to_working_dir, resolve_video_json_path,
)
from services.migration_service import migrate_json_file_if_needed, initialise_video_json_if_needed
from services.motor_service import get_motor_stable_timestamps
from services.image_service import extract_frame_at_time
from services.thumbnail_service import ThumbnailWorkerMulti, THUMB_W, THUMB_H
from views.widgets.video_player_dialog import VideoPlayerWindow
from views.dialogs.map_dialog import MapDialog, MapBridge


class QualifController:
    """Contrôleur de la page Qualification : gestion de l'arbre vidéo, de la poubelle et de la carte."""

    def __init__(self, widget: QtWidgets.QWidget, parent=None, on_before_delete=None):
        """
        Args:
            on_before_delete: Callback appelé avec le chemin vidéo avant exclusion
                              (libère les handles fichiers des autres controllers).
        """
        self.widget = widget
        self.parent = parent
        self._on_before_delete = on_before_delete
        self.current_language = 'en'
        self.system_data = None
        self.video_model = QtGui.QStandardItemModel()
        self.trash_model = QtGui.QStandardItemModel()
        self.selected_video_name = None
        self.all_coords = {}
        self.campaign_fields = {}
        self._working_dir = ""
        self.detached_player = None
        self.current_campaign_folder = None

        self.video_tree = self.widget.findChild(QtWidgets.QTreeView, "video_tree")
        self.trash_video_tree = self.widget.findChild(QtWidgets.QTreeView, "trash_video_tree")
        self.frame_campaign = self.widget.findChild(QtWidgets.QFrame, "frame_campagne")
        self.mini_map_container = self.widget.findChild(QtWidgets.QFrame, "mini_map_container")
        self.frame_miniature = self.widget.findChild(QtWidgets.QFrame, "frame_miniature")

        self._fs_watcher = QtCore.QFileSystemWatcher()
        self._fs_debounce = QtCore.QTimer()
        self._fs_debounce.setSingleShot(True)
        self._fs_debounce.setInterval(600)
        self._fs_debounce.timeout.connect(self._refresh_from_disk)
        self._fs_watcher.directoryChanged.connect(self._fs_debounce.start)
        self._fs_watcher.fileChanged.connect(self._fs_debounce.start)

        if self.frame_campaign:
            layout = QtWidgets.QVBoxLayout(self.frame_campaign)
            layout.setContentsMargins(5, 5, 5, 5)
            layout.setSpacing(10)
            self.lbl_section_title = QtWidgets.QLabel("Campaign Properties")
            self.lbl_section_title.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #F2BFB4;"
                " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 5px;"
            )
            self.lbl_section_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.lbl_section_title)
            self.scroll_campaign = QtWidgets.QScrollArea(self.frame_campaign)
            self.scroll_campaign.setWidgetResizable(True)
            self.scroll_campaign.setStyleSheet("background: transparent; border: none;")
            self.dynamic_form_container = QtWidgets.QWidget()
            self.scroll_campaign.setWidget(self.dynamic_form_container)
            layout.addWidget(self.scroll_campaign)

        self._init_video_list()
        self._init_trash_list()
        self._configure_left_splitter()
        self._init_minimap()
        self._init_miniature_area()
        self.set_language(self.current_language)

    # --- Language ---

    def set_working_dir(self, path: str):
        self._working_dir = path

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Traduit les en-têtes des modèles et les titres de section."""
        self.current_language = language
        if hasattr(self, 'lbl_section_title'):
            self.lbl_section_title.setText(self.translate("Propriétés de campagne", "Campaign Properties"))
        if hasattr(self, 'lbl_videos_title'):
            self.lbl_videos_title.setText(self.translate("Vidéos de campagne", "Campaign Videos"))
        if hasattr(self, 'lbl_trash_title'):
            self.lbl_trash_title.setText(self.translate("Vidéos supprimées", "Removed Videos"))
        header_labels = [
            self.translate("Fichier", "File"),
            self.translate("Durée", "Duration"),
            "FPS",
            self.translate("Résolution", "Resolution"),
            self.translate("Taille", "Size"),
        ]
        self.video_model.setHorizontalHeaderLabels(header_labels)
        self.trash_model.setHorizontalHeaderLabels(header_labels)

    # --- Init helpers ---

    def _init_video_list(self):
        """Configure le QTreeView vidéo avec ses en-têtes, drag-drop et menu contextuel."""
        self.video_model.setHorizontalHeaderLabels(["File", "Duration", "FPS", "Resolution", "Size", "Date"])
        self.video_tree.setModel(self.video_model)

        splitter = self.video_tree.parentWidget()
        self.widget_video_container = QtWidgets.QWidget()
        layout_block = QtWidgets.QVBoxLayout(self.widget_video_container)
        layout_block.setContentsMargins(0, 0, 0, 0)
        layout_block.setSpacing(5)
        self.lbl_videos_title = QtWidgets.QLabel("Campaign Videos")
        self.lbl_videos_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #F2BFB4;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 2px;"
        )
        self.lbl_videos_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if hasattr(splitter, "indexOf"):
            index = splitter.indexOf(self.video_tree)
            layout_block.addWidget(self.lbl_videos_title)
            layout_block.addWidget(self.video_tree)
            splitter.insertWidget(index, self.widget_video_container)

        self.video_tree.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))
        for i in range(self.video_model.columnCount()):
            self.video_tree.resizeColumnToContents(i)
        self.video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.video_tree.clicked.connect(self.on_video_selected)
        self.video_tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_tree.customContextMenuRequested.connect(self.show_context_menu)
        self.video_tree.setDragEnabled(True)
        self.video_tree.setAcceptDrops(True)
        self.video_tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.video_tree.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.video_tree.dragEnterEvent = self.video_drag_enter_event
        self.video_tree.dropEvent = self.video_drop_event

    def _init_trash_list(self):
        """Configure le QTreeView poubelle avec drag-drop bidirectionnel."""
        if not self.trash_video_tree:
            return
        self.trash_model.setHorizontalHeaderLabels(["File", "Duration", "FPS", "Resolution", "Size"])
        self.trash_video_tree.setModel(self.trash_model)

        splitter_trash = self.trash_video_tree.parentWidget()
        self.widget_trash_container = QtWidgets.QWidget()
        layout_block_trash = QtWidgets.QVBoxLayout(self.widget_trash_container)
        layout_block_trash.setContentsMargins(0, 0, 0, 0)
        layout_block_trash.setSpacing(5)
        self.lbl_trash_title = QtWidgets.QLabel("Removed Videos")
        self.lbl_trash_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #D94F38;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 2px;"
        )
        self.lbl_trash_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if hasattr(splitter_trash, "indexOf"):
            index_trash = splitter_trash.indexOf(self.trash_video_tree)
            layout_block_trash.addWidget(self.lbl_trash_title)
            layout_block_trash.addWidget(self.trash_video_tree)
            splitter_trash.insertWidget(index_trash, self.widget_trash_container)

        self.trash_video_tree.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))
        for i in range(self.trash_model.columnCount()):
            self.trash_video_tree.resizeColumnToContents(i)
        self.trash_video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.trash_video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.trash_video_tree.setAcceptDrops(True)
        self.trash_video_tree.setDragEnabled(True)
        self.trash_video_tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.trash_video_tree.dragEnterEvent = self.trash_drag_enter_event
        self.trash_video_tree.dropEvent = self.trash_drop_event

    def _configure_left_splitter(self):
        """Abaisse les minimums du splitter vertical gauche et fixe les facteurs d'étirement."""
        if not self.frame_campaign:
            return
        splitter = self.frame_campaign.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            return

        # Le .ui impose minimumHeight=430 sur frame_campagne et 200 sur chaque arbre,
        # soit 830 px minimum — infaisable sur la plupart des écrans.
        # On abaisse ces minimums : le contenu reste accessible via les scrollbars.
        self.frame_campaign.setMinimumHeight(120)
        if self.video_tree:
            self.video_tree.setMinimumHeight(80)
        if self.trash_video_tree:
            self.trash_video_tree.setMinimumHeight(60)

        # Facteurs : frame_campagne fixe (stretch 0), arbres se partagent le reste
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)

    def _reset_left_splitter_sizes(self):
        """Réinitialise les tailles du splitter gauche après chargement de campagne (fenêtre visible)."""
        if not self.frame_campaign:
            return
        splitter = self.frame_campaign.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            return
        total = splitter.height()
        if total <= 0:
            return
        # 40 % pour les propriétés de campagne, 40 % pour les vidéos, 20 % pour la poubelle
        campaign_h = max(120, int(total * 0.40))
        remaining = total - campaign_h
        video_h = max(80, int(remaining * 0.65))
        trash_h = max(60, remaining - video_h)
        splitter.setSizes([campaign_h, video_h, trash_h])

    def _init_minimap(self):
        """Crée le MapBridge, le WebChannel et le QDialog carte de campagne."""
        self.bridge = MapBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.bridge)
        self.bridge.videoSelected.connect(self.select_video_by_name)
        self.map_dialog = MapDialog(self.bridge, self.channel, parent=self.widget)
        self.map_initialized = False

    def _init_miniature_area(self):
        """Initialise la zone de miniatures scrollable dans frame_miniature."""
        if not self.frame_miniature:
            return
        if self.frame_miniature.layout():
            old = self.frame_miniature.layout()
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(old)

        scroll_area = QtWidgets.QScrollArea(self.frame_miniature)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: #111820; border: none;")

        scroll_content = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(15)
        self.scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        main_layout = QtWidgets.QVBoxLayout(self.frame_miniature)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll_area)

    # --- Campaign opening ---

    def open_system_explorer(self, derusher_name: str):
        """Ouvre un sélecteur de dossier puis charge la campagne (compatibilité)."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.parent or self.widget, "Select Campaign Folder"
        )
        if not directory:
            return
        self.load_campaign_folder(directory, derusher_name)

    def load_campaign_folder(self, directory: str, derusher_name: str):
        """Charge une campagne depuis *directory* sans ouvrir de QFileDialog."""
        self.current_campaign_folder = directory
        self.video_model.removeRows(0, self.video_model.rowCount())
        if self.trash_video_tree:
            self.trash_model.removeRows(0, self.trash_model.rowCount())
        self.all_coords.clear()
        self.map_initialized = False
        self._start_watching_campaign(directory)

        videos = get_all_mp4_files(directory)
        if not videos:
            print("[WARNING] No MP4 files found.")
            return

        for video in videos:
            col_name = QtGui.QStandardItem(video["name"])
            col_dur = QtGui.QStandardItem(video["duration"])
            col_fps = QtGui.QStandardItem(video["fps"])
            col_res = QtGui.QStandardItem(video["res"])
            size_str = video.get("size") or (
                f"{os.path.getsize(video['path']) / (1024 * 1024):.2f} MB"
                if os.path.exists(video["path"]) else "--"
            )
            col_size = QtGui.QStandardItem(size_str)
            col_date = QtGui.QStandardItem(video["date"])
            col_name.setData(video["path"], QtCore.Qt.ItemDataRole.UserRole)
            self.video_model.appendRow([col_name, col_dur, col_fps, col_res, col_size, col_date])

            coords = get_video_gps_coords(video["path"])
            if coords:
                self.all_coords[video["name"]] = coords

        self.update_minimap(self.selected_video_name, show_dialog=False)
        self._start_thumbnail_generation()

        update_counter = 0
        first_loaded_json = None

        for video in videos:
            initialise_video_json_if_needed(video["path"])   # template.json → stem.json
            json_path = get_video_json_path(video["path"])
            if not os.path.exists(json_path):
                continue
            migrate_json_file_if_needed(json_path)
            if not first_loaded_json:
                first_loaded_json = json_path
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    json_payload = json.load(f)
                if "survey" in json_payload and "derusher" in json_payload.get("video_observation", {}):
                    json_payload["video_observation"]["derusher"]["value"] = derusher_name
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(json_payload, f, indent=2, ensure_ascii=False)
                    update_counter += 1
            except Exception as e:
                print(f"Error patching {json_path}: {e}")

        print(f"[JSON] Derusher '{derusher_name}' written into {update_counter} files.")

        self.system_data = None
        if first_loaded_json:
            try:
                with open(first_loaded_json, 'r', encoding='utf-8') as f:
                    complete_dataset = json.load(f)
                if "system" in complete_dataset:
                    self.system_data = complete_dataset["system"]
            except Exception as e:
                print(f"[ERROR] Could not read system data: {e}")
            self.load_and_display_campaign_json(first_loaded_json)

        self._reset_left_splitter_sizes()
        self.refresh_completion_colors()

    # ── Indicateur de complétion ─────────────────────────────────────────

    def _get_completion_color(self, video_path: str) -> QtGui.QColor:
        """Rouge / orange / vert selon le remplissage des champs critiques du JSON."""
        json_path = resolve_video_json_path(self._working_dir, video_path)
        if not os.path.exists(json_path):
            return QtGui.QColor("#D94F38")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return QtGui.QColor("#D94F38")

        def _filled(block: dict, key: str) -> bool:
            entry = block.get(key, {})
            val = entry.get("value") if isinstance(entry, dict) else entry
            return bool(val and str(val).strip() not in ("", "None", "null"))

        obs  = data.get("video_observation", {})
        surv = data.get("survey", {})
        critical  = [_filled(obs, "codeObs"), _filled(obs, "exploitable")]
        important = [_filled(obs, "habitat"), _filled(obs, "depth"), _filled(surv, "date")]

        if not all(critical):
            return QtGui.QColor("#D94F38")   # rouge — champ critique absent
        if sum(important) < 2:
            return QtGui.QColor("#E8A838")   # orange — incomplet
        return QtGui.QColor("#5DBB63")       # vert — complet

    def _apply_completion_color(self, row: int):
        """Applique un fond semi-transparent sur la ligne selon la complétion JSON."""
        item0 = self.video_model.item(row, 0)
        if not item0:
            return
        video_path = item0.data(QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return
        color = self._get_completion_color(str(video_path))
        color.setAlpha(35)
        brush = QtGui.QBrush(color)
        for col in range(self.video_model.columnCount()):
            cell = self.video_model.item(row, col)
            if cell:
                cell.setBackground(brush)

    def refresh_completion_colors(self):
        """Recalcule les couleurs de complétion pour toutes les lignes du modèle vidéo."""
        for row in range(self.video_model.rowCount()):
            self._apply_completion_color(row)

    def refresh_completion_color_for_video(self, video_path: str):
        """Recalcule la couleur de complétion uniquement pour la vidéo donnée."""
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == str(video_path):
                self._apply_completion_color(row)
                return

    def _start_thumbnail_generation(self):
        """Lance un worker pour générer les vignettes de toutes les vidéos (modèle principal + corbeille)."""
        if hasattr(self, '_thumb_worker') and self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.requestInterruption()
        items = []
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    items.append(('main', row, path))
        for row in range(self.trash_model.rowCount()):
            item = self.trash_model.item(row, 0)
            if item:
                path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    items.append(('trash', row, path))
        if not items:
            return
        self._thumb_worker = ThumbnailWorkerMulti(items)
        self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_worker.start()

    def _on_thumbnail_ready(self, model_key: str, row: int, icon: QtGui.QIcon):
        """Applique la vignette sur l'item du modèle correspondant."""
        model = self.video_model if model_key == 'main' else self.trash_model
        item = model.item(row, 0)
        if item:
            item.setIcon(icon)

    def _start_watching_campaign(self, directory: str):
        """Surveille la racine campagne et ses sous-dossiers vidéo directs."""
        old = self._fs_watcher.directories()
        if old:
            self._fs_watcher.removePaths(old)
        old_files = self._fs_watcher.files()
        if old_files:
            self._fs_watcher.removePaths(old_files)

        dirs_to_watch = [directory]

        try:
            for name in os.listdir(directory):
                child = os.path.join(directory, name)
                if os.path.isdir(child) and name not in ('segments',):
                    dirs_to_watch.append(child)
        except OSError:
            pass

        existing = [d for d in dirs_to_watch if os.path.isdir(d)]
        if existing:
            self._fs_watcher.addPaths(existing)

    def _refresh_from_disk(self):
        """Resynchronise les trees vidéo et trash avec l'état réel du disque."""
        if not self.current_campaign_folder:
            return

        videos = get_all_mp4_files(self.current_campaign_folder)

        # Chemins actuellement dans les deux modèles (exclus = trash)
        excluded_paths = {
            self.trash_model.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole)
            for r in range(self.trash_model.rowCount())
            if self.trash_model.item(r, 0)
        }
        current_paths = {
            self.video_model.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole)
            for r in range(self.video_model.rowCount())
            if self.video_model.item(r, 0)
        }
        all_known = current_paths | excluded_paths

        # Supprimer les lignes dont le fichier n'existe plus
        for row in range(self.video_model.rowCount() - 1, -1, -1):
            item = self.video_model.item(row, 0)
            p = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if p and not os.path.exists(p):
                self.video_model.removeRow(row)

        # Ajouter les nouveaux fichiers (non exclus)
        for video in videos:
            if video["path"] not in all_known:
                col_name = QtGui.QStandardItem(video["name"])
                col_name.setData(video["path"], QtCore.Qt.ItemDataRole.UserRole)
                self.video_model.appendRow([
                    col_name,
                    QtGui.QStandardItem(video["duration"]),
                    QtGui.QStandardItem(video["fps"]),
                    QtGui.QStandardItem(video["res"]),
                    QtGui.QStandardItem(video.get("size", "--")),
                    QtGui.QStandardItem(video.get("date", "")),
                ])
                coords = get_video_gps_coords(video["path"])
                if coords:
                    self.all_coords[video["name"]] = coords

        self._start_watching_campaign(self.current_campaign_folder)

    def load_and_display_campaign_json(self, json_path: str):
        if not hasattr(self, 'scroll_campaign') or not self.scroll_campaign:
            return

        # Remplacer le widget interne — évite "QWidget already has a layout"
        # causé par deleteLater() asynchrone sur l'ancien layout.
        new_container = QtWidgets.QWidget()
        self.scroll_campaign.setWidget(new_container)   # QScrollArea supprime l'ancien
        self.dynamic_form_container = new_container
        self.campaign_fields.clear()

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    json_payload = json.load(f)
                if "survey" in json_payload:
                    form_layout = QtWidgets.QFormLayout(self.dynamic_form_container)
                    form_layout.setContentsMargins(5, 5, 5, 5)
                    form_layout.setSpacing(15)
                    form_layout.setFieldGrowthPolicy(
                        QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                    for key, meta in json_payload["survey"].items():
                        display_name = meta.get("name_fr", key).capitalize()
                        value = meta.get("value") or ""
                        input_field = QtWidgets.QLineEdit()
                        input_field.setText(str(value))
                        input_field.setStyleSheet("""
                            QLineEdit { font-size: 14px; font-weight: bold; padding: 6px;
                                        color: #ffffff; background-color: #1a1a1a;
                                        border: 1px solid #555555; border-radius: 4px; }
                        """)
                        if meta.get("example"):
                            input_field.setPlaceholderText(str(meta["example"]))
                        self.campaign_fields[key] = input_field
                        input_field.editingFinished.connect(
                            lambda tk=key: self.on_campaign_field_modified(tk))
                        lbl = QtWidgets.QLabel(f"{display_name} :")
                        lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #e0e0e0;")
                        form_layout.addRow(lbl, input_field)
                    return
            except Exception as e:
                print(f"Error loading campaign JSON: {e}")

        fallback_layout = QtWidgets.QVBoxLayout(self.dynamic_form_container)
        lbl_error = QtWidgets.QLabel("No active campaign data found.")
        lbl_error.setStyleSheet("color: #aaaaaa; font-style: italic; font-size: 11px;")
        lbl_error.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        fallback_layout.addWidget(lbl_error)

    def on_campaign_field_modified(self, key: str):
        """Synchronise un champ campagne dans tous les JSON vidéo quand l'utilisateur l'édite."""
        widget = self.campaign_fields.get(key)
        if widget:
            self.synchronize_campaign_field(key, widget.text())

    def synchronize_campaign_field(self, key: str, value: str):
        """Écrit value dans le champ key de la section survey de chaque JSON vidéo de la campagne."""
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path or not os.path.exists(video_path):
                continue
            if self._working_dir:
                json_path = get_working_video_json_path(self._working_dir, video_path)
            else:
                json_path = get_video_json_path(video_path)
            if not os.path.exists(json_path):
                continue  # ne jamais écrire dans les données source
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if "survey" in data and key in data["survey"]:
                    data["survey"][key]["value"] = value
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[IO SYNC ERROR] {e}")

    # --- Video selection ---

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Ouvre le lecteur détaché et met à jour la minimap quand l'utilisateur clique sur une vidéo."""
        item = self.video_model.itemFromIndex(index.siblingAtColumn(0))
        if not item:
            return
        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        video_name = item.text()
        self.selected_video_name = video_name

        is_stereo, video_payload = check_stereo_status(video_path)
        video_dir = os.path.dirname(video_path)
        csv_system = os.path.join(video_dir, "systemEvent.csv")
        engine_events = []
        if os.path.exists(csv_system):
            self.update_camera_views(video_path, csv_system)
            engine_events = get_motor_stable_timestamps(csv_path=csv_system, delay=6.0)

        self.update_minimap(selected_name=video_name, show_dialog=True)

        if self.detached_player is not None:
            try:
                self.detached_player.close()
                self.detached_player.deleteLater()
            except Exception:
                pass
        self.detached_player = VideoPlayerWindow(video_payload, events_data=engine_events, parent=self.widget)
        self.detached_player.show()

    # --- Minimap ---

    def update_minimap(self, selected_name=None, show_dialog=False):
        """Initialise ou rafraîchit la carte Folium et surligne le marqueur de selected_name en rouge.

        show_dialog=True → ouvre la fenêtre carte si elle n'est pas déjà visible (uniquement
        lors d'un clic explicite sur une vidéo).  Les autres appels passent False pour ne pas
        forcer la réouverture.
        """
        valid_coords = {}
        if self.all_coords:
            for name, coords in self.all_coords.items():
                if coords and len(coords) >= 2:
                    lat, lon = coords[0], coords[1]
                    if lat is not None and lon is not None:
                        try:
                            if not (math.isnan(float(lat)) or math.isnan(float(lon))):
                                valid_coords[name] = [float(lat), float(lon)]
                        except (ValueError, TypeError):
                            pass

        center = list(valid_coords.values())[0] if valid_coords else [48.356, -4.571]

        # --- Lire les infos survey + waypoints depuis les JSON ---
        survey_name, zone, site = "", "", ""
        waypoints: dict[str, str] = {}
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            jpath = get_video_json_path(vpath)
            if not os.path.exists(jpath):
                continue
            try:
                with open(jpath, 'r', encoding='utf-8') as f:
                    jdata = json.load(f)
                if not survey_name:
                    sv = jdata.get("survey", {})
                    survey_name = (sv.get("survey_name") or {}).get("value") or ""
                    zone        = (sv.get("zone")        or {}).get("value") or ""
                    site        = (sv.get("site")        or {}).get("value") or ""
                wp = (jdata.get("video_observation", {}).get("gps_waypoint") or {}).get("value")
                waypoints[item.text()] = str(wp) if wp is not None else ""
            except Exception:
                pass

        if not getattr(self, 'map_initialized', False):
            m = folium.Map(location=center, zoom_start=17, tiles=None)
            folium.TileLayer(tiles="openstreetmap", name="OpenStreetMap", max_zoom=19).add_to(m)
            folium.TileLayer(
                tiles="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
                attr="Map data: &copy; OpenSeaMap contributors",
                name="OpenSeaMap", overlay=True, control=True, max_zoom=19
            ).add_to(m)
            folium.LayerControl().add_to(m)

            # --- Bandeau campagne (survey / zone / site) ---
            header_parts = [p for p in [survey_name, zone, site] if p]
            if header_parts:
                header_html = (
                    '<div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);'
                    'background:rgba(20,41,61,0.88);color:#F2BFB4;'
                    'font-family:\'Segoe UI\',sans-serif;font-size:13px;font-weight:bold;'
                    'padding:5px 18px;border-radius:6px;border:1px solid #2778A2;'
                    'z-index:9999;pointer-events:none;white-space:nowrap;">'
                    + " &nbsp;|&nbsp; ".join(header_parts)
                    + '</div>'
                )
                m.get_root().html.add_child(folium.Element(header_html))

            m.get_root().header.add_child(
                folium.Element('<script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>')
            )
            main_script = """
            <script>
                var qtBackend = null; var allMarkers = {}; var lastRedMarker = null;
                document.addEventListener("DOMContentLoaded", function() {
                    if (typeof qt !== 'undefined' && qt.webChannelTransport) {
                        new QWebChannel(qt.webChannelTransport, function (channel) {
                            qtBackend = channel.objects.backend;
                        });
                    }
                });
                function notifyPython(videoName) { if (qtBackend) { qtBackend.select_video(videoName); } }
                function changeMarkerColorJS(videoName) {
                    if (lastRedMarker && allMarkers[lastRedMarker]) {
                        allMarkers[lastRedMarker].setIcon(L.AwesomeMarkers.icon({icon: 'camera', prefix: 'fa', markerColor: 'blue'}));
                        allMarkers[lastRedMarker].closePopup();
                    }
                    if (allMarkers[videoName]) {
                        var mNew = allMarkers[videoName];
                        mNew.setIcon(L.AwesomeMarkers.icon({icon: 'camera', prefix: 'fa', markerColor: 'red'}));
                        mNew.setZIndexOffset(1000); lastRedMarker = videoName;
                        setTimeout(function() { mNew.openPopup(); }, 50);
                        if (window.leafletMap) { window.leafletMap.panTo(mNew.getLatLng()); }
                    }
                }
            </script>"""
            m.get_root().html.add_child(folium.Element(main_script))
            js_map_linkage = f"""
            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    if (typeof {m.get_name()} !== 'undefined') {{ window.leafletMap = {m.get_name()}; }}
                }});
            </script>"""
            m.get_root().html.add_child(folium.Element(js_map_linkage))

            sorted_names = sorted(valid_coords.keys())
            polyline_coords = [valid_coords[n] for n in sorted_names]
            if len(polyline_coords) >= 2:
                folium.PolyLine(
                    locations=polyline_coords,
                    color="#2778A2",
                    weight=2.5,
                    opacity=0.85,
                    tooltip="Tracé GPS (ordre chronologique)",
                ).add_to(m)

            for name, coords in valid_coords.items():
                wp = waypoints.get(name, "")
                popup_html = (
                    f'<div style="font-family:\'Segoe UI\',sans-serif;font-size:12px;'
                    f'min-width:120px;">'
                    f'<b style="font-size:13px;">{name}</b>'
                    + (f'<br><span style="color:#607080;">GPS Waypoint :</span> '
                       f'<b>{wp}</b>' if wp else '')
                    + '</div>'
                )
                popup = folium.Popup(popup_html, max_width=220,
                                     auto_close=False, close_on_click=False)
                marker = folium.Marker(location=coords, popup=popup,
                                       icon=folium.Icon(color='blue', icon='camera', prefix='fa'))
                marker.add_to(m)
                js_reg = f"""
                <script>
                    document.addEventListener("DOMContentLoaded", function() {{
                        setTimeout(function() {{
                            var mInstance = {marker.get_name()};
                            if (mInstance) {{
                                allMarkers["{name}"] = mInstance;
                                mInstance.on('click', function(e) {{ notifyPython("{name}"); }});
                            }}
                        }}, 150);
                    }});
                </script>"""
                m.get_root().html.add_child(folium.Element(js_reg))

            if not valid_coords:
                no_gps_html = """
                <div style="
                    position: fixed; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    background: rgba(20,41,61,0.90);
                    color: #F2BFB4;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 14px; font-weight: bold;
                    padding: 16px 24px; border-radius: 8px;
                    border: 1px solid #2778A2;
                    z-index: 9999; text-align: center;
                    pointer-events: none;">
                    Aucune donnée GPS disponible pour cette campagne
                </div>"""
                m.get_root().html.add_child(folium.Element(no_gps_html))

            data = io.BytesIO()
            m.save(data, close_file=False)
            self.map_dialog.map_view.setHtml(data.getvalue().decode())
            self.map_initialized = True
            if show_dialog and not self.map_dialog.isVisible():
                self.map_dialog.show()
            if selected_name and selected_name in valid_coords:
                QtCore.QTimer.singleShot(600, lambda: self.apply_red_marker_js(selected_name))
        else:
            if show_dialog and not self.map_dialog.isVisible():
                self.map_dialog.show()
            if self.map_dialog.isVisible() and selected_name and selected_name in valid_coords:
                QtCore.QTimer.singleShot(80, lambda: self.apply_red_marker_js(selected_name))

    def apply_red_marker_js(self, selected_name: str):
        """Exécute le JS changeMarkerColorJS pour passer le marqueur selected_name en rouge."""
        if not selected_name:
            return
        script = f"""
        if (typeof changeMarkerColorJS === 'function' && typeof allMarkers !== 'undefined' && allMarkers['{selected_name}']) {{
            changeMarkerColorJS('{selected_name}');
        }} else {{
            setTimeout(function() {{
                if (typeof changeMarkerColorJS === 'function') {{ changeMarkerColorJS('{selected_name}'); }}
            }}, 100);
        }}"""
        self.map_dialog.map_view.page().runJavaScript(script)

    def select_video_by_name(self, video_name: str):
        """Sélectionne programmatiquement une vidéo par son nom (appelé depuis la carte ou un autre controller)."""
        if self.selected_video_name == video_name:
            return
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and item.text() == video_name:
                index = self.video_model.indexFromItem(item)
                self.video_tree.blockSignals(True)
                self.video_tree.selectionModel().setCurrentIndex(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect | QtCore.QItemSelectionModel.SelectionFlag.Rows
                )
                self.video_tree.scrollTo(index)
                self.video_tree.blockSignals(False)
                self.selected_video_name = video_name
                video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                video_dir = os.path.dirname(video_path)
                csv_system = os.path.join(video_dir, "systemEvent.csv")
                motor_events = []
                if os.path.exists(csv_system):
                    self.update_camera_views(video_path, csv_system)
                    motor_events = get_motor_stable_timestamps(csv_path=csv_system, delay=6.0)
                if self.detached_player is not None:
                    try:
                        self.detached_player.close()
                        self.detached_player.deleteLater()
                    except Exception:
                        pass
                self.detached_player = VideoPlayerWindow(video_path, events_data=motor_events, parent=self.widget)
                self.detached_player.show()
                self.update_minimap(video_name, show_dialog=False)
                break

    # --- Camera views / thumbnails ---

    def update_camera_views(self, video_path: str, csv_path: str):
        """Remplit la zone miniatures avec des captures aux timestamps de rotation moteur détectés dans csv_path."""
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            motor_events = get_motor_stable_timestamps(csv_path, delay=6.0)
            if not motor_events:
                lbl = QtWidgets.QLabel("No motor rotation found in the CSV file.")
                lbl.setStyleSheet("color: white; font-size: 14px;")
                self.scroll_layout.addWidget(lbl)
                self.scroll_layout.addStretch()
                return

            rotation_groups = [motor_events[i:i + 6] for i in range(0, len(motor_events), 6)]
            for index_rot, rotation_events in enumerate(rotation_groups):
                frame_rotation = QtWidgets.QFrame()
                frame_rotation.setFixedHeight(230)
                frame_rotation.setStyleSheet(
                    "background-color: #20415d; border-radius: 8px; border: 1px solid #3d3d3d;"
                )
                hbox = QtWidgets.QHBoxLayout(frame_rotation)
                hbox.setContentsMargins(15, 10, 15, 10)
                hbox.setSpacing(15)

                title_lbl = QtWidgets.QLabel(f"Rotation\n#{index_rot + 1}\n(360°)")
                title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 13px;")
                title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                title_lbl.setFixedWidth(90)
                hbox.addWidget(title_lbl)

                for evt in rotation_events:
                    ts, angle, evt_type = evt["timestamp"], evt["angle"], evt["type"]
                    w_photo = QtWidgets.QFrame()
                    if evt_type == "rotation_360":
                        w_photo.setFixedSize(248, 188)
                        w_photo.setStyleSheet(
                            "background-color: #1a1a1a; border-radius: 6px; border: 3px solid #ff3333;"
                        )
                    else:
                        w_photo.setFixedSize(240, 180)
                        w_photo.setStyleSheet(
                            "background-color: #1a1a1a; border-radius: 6px; border: 1px solid #555555;"
                        )
                    frame_data = extract_frame_at_time(video_path, ts)
                    if frame_data is not None:
                        self._display_in_frame(w_photo, frame_data, angle, ts)
                    hbox.addWidget(w_photo)

                if len(rotation_events) < 6:
                    for _ in range(6 - len(rotation_events)):
                        hbox.addSpacing(240)
                hbox.addStretch()
                self.scroll_layout.addWidget(frame_rotation)
        except Exception as e:
            print(f"Error updating camera views: {e}")

    def _display_in_frame(self, widget: QtWidgets.QFrame, cv_img, angle_degrees: int, ts_seconds: float):
        """Affiche cv_img dans widget avec des overlays angle et timestamp."""
        h, w, ch = cv_img.shape
        q_img = QtGui.QImage(cv_img.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(q_img)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QtWidgets.QLabel(widget)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setPixmap(pixmap.scaled(
            widget.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation
        ))
        layout.addWidget(lbl)
        angle_lbl = QtWidgets.QLabel(f" {angle_degrees}° ", lbl)
        angle_lbl.setStyleSheet(
            "background-color: rgba(0,0,0,160); color: #55ff55; font-weight: bold; border-radius: 3px; font-size: 10px;"
        )
        angle_lbl.move(5, 5)
        minutes = int(ts_seconds // 60)
        seconds = int(ts_seconds % 60)
        ms = int((ts_seconds - int(ts_seconds)) * 1000)
        time_lbl = QtWidgets.QLabel(f" {minutes:02d}:{seconds:02d}.{ms:03d} ", lbl)
        time_lbl.setStyleSheet(
            "background-color: rgba(0,0,0,160); color: #ffffff; font-weight: bold; border-radius: 3px; font-size: 10px;"
        )
        time_lbl.adjustSize()
        time_lbl.move(widget.width() - time_lbl.width() - 5, 5)

    # --- Context menu / drag-drop ---

    def show_context_menu(self, position: QtCore.QPoint):
        """Affiche un menu contextuel avec l'action Supprimer sur la ligne pointée."""
        index = self.video_tree.indexAt(position)
        if not index.isValid():
            return
        menu = QtWidgets.QMenu(self.video_tree)
        trash_action = menu.addAction("Delete")
        clicked_action = menu.exec(self.video_tree.viewport().mapToGlobal(position))
        if clicked_action == trash_action:
            self.delete_video_by_index(index.siblingAtColumn(0))

    def _close_detached_player(self):
        """Libère les handles fichiers du lecteur détaché avant tout déplacement sur disque."""
        if self.detached_player is not None:
            try:
                self.detached_player.release_files()
                self.detached_player.close()
                self.detached_player.deleteLater()
            except Exception:
                pass
            self.detached_player = None

    def delete_video_by_index(self, index: QtCore.QModelIndex):
        """Déplace la vidéo dans la liste 'supprimées' (en mémoire) et supprime son dossier de sortie."""
        row = index.row()
        name_item = self.video_model.item(row, 0)
        if not name_item:
            return
        video_name = name_item.text()
        video_path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)

        if self._on_before_delete:
            self._on_before_delete(video_path)
        self._close_detached_player()

        # Supprimer le sous-dossier de sortie de cette vidéo dans le working_dir
        if self._working_dir and video_path:
            output_dir = get_working_video_dir(self._working_dir, video_path)
            if os.path.isdir(output_dir):
                try:
                    shutil.rmtree(output_dir)
                    print(f"[QUALIF] Dossier de sortie supprimé : {output_dir}")
                except Exception as e:
                    print(f"[QUALIF] Impossible de supprimer le dossier de sortie : {e}")

        items = [self.video_model.item(row, c) for c in range(5)]
        col_name = QtGui.QStandardItem(video_name)
        col_name.setData(video_path, QtCore.Qt.ItemDataRole.UserRole)
        self.trash_model.appendRow(
            [col_name] + [QtGui.QStandardItem(items[c].text() if items[c] else "") for c in range(1, 5)]
        )
        self.video_model.removeRow(row)
        if self.selected_video_name == video_name:
            self.selected_video_name = None


    def restore_video_by_index(self, index: QtCore.QModelIndex):
        """Remet la vidéo dans la liste principale et recrée son dossier de sortie."""
        row = index.row()
        item_name = self.trash_model.item(row, 0)
        if not item_name:
            return
        video_name = item_name.text()
        video_path = item_name.data(QtCore.Qt.ItemDataRole.UserRole)

        # Recréer le sous-dossier de sortie dans le working_dir
        if self._working_dir and video_path and os.path.exists(video_path):
            try:
                sync_video_to_working_dir(self._working_dir, video_path)
                print(f"[QUALIF] Dossier de sortie recréé : {get_working_video_dir(self._working_dir, video_path)}")
            except Exception as e:
                print(f"[QUALIF] Impossible de recréer le dossier de sortie : {e}")

        items = [self.trash_model.item(row, c) for c in range(5)]
        col_name = QtGui.QStandardItem(video_name)
        col_name.setData(video_path, QtCore.Qt.ItemDataRole.UserRole)
        self.video_model.appendRow(
            [col_name] + [QtGui.QStandardItem(items[c].text() if items[c] else "") for c in range(1, 5)]
        )
        self.trash_model.removeRow(row)

        # Régénérer la miniature pour cette ligne (stocker sur self pour éviter le GC)
        new_row = self.video_model.rowCount() - 1
        if video_path:
            if hasattr(self, '_thumb_worker') and self._thumb_worker and self._thumb_worker.isRunning():
                self._thumb_worker.requestInterruption()
                self._thumb_worker.wait(200)
            self._thumb_worker = ThumbnailWorkerMulti([('main', new_row, video_path)])
            self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._thumb_worker.start()

    def trash_drag_enter_event(self, event: QtGui.QDragEnterEvent):
        """Accepte le glisser-déposer depuis video_tree vers la poubelle."""
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist") and event.source() == self.video_tree:
            event.acceptProposedAction()
        else:
            event.ignore()

    def trash_drop_event(self, event: QtGui.QDropEvent):
        """Supprime les vidéos déposées sur la poubelle (en les déplaçant dans .trash)."""
        if event.source() == self.video_tree:
            selected = self.video_tree.selectionModel().selectedRows()
            if selected:
                selected.sort(key=lambda idx: idx.row(), reverse=True)
                for idx in selected:
                    self.delete_video_by_index(idx)
                event.setDropAction(QtCore.Qt.DropAction.CopyAction)
                event.accept()
        else:
            event.ignore()

    def video_drag_enter_event(self, event: QtGui.QDragEnterEvent):
        """Accepte le glisser-déposer depuis trash_video_tree vers la liste vidéo."""
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist") and event.source() == self.trash_video_tree:
            event.acceptProposedAction()
        else:
            event.ignore()

    def video_drop_event(self, event: QtGui.QDropEvent):
        """Restaure les vidéos déposées depuis la poubelle vers la liste principale."""
        if event.source() == self.trash_video_tree:
            selected = self.trash_video_tree.selectionModel().selectedRows()
            if selected:
                selected.sort(key=lambda idx: idx.row(), reverse=True)
                for idx in selected:
                    self.restore_video_by_index(idx)
                event.setDropAction(QtCore.Qt.DropAction.CopyAction)
                event.accept()
        else:
            event.ignore()
