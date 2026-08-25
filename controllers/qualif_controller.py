import os
import io
import csv
import json
import math
import shutil
import threading
import folium
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWebChannel import QWebChannel

from services.video_service import get_all_mp4_files, get_sequential_segments, check_stereo_status, get_system_name
from services.campaign_service import (
    get_video_gps_coords, get_working_video_json_path,
    get_working_video_dir, sync_video_to_working_dir, resolve_video_json_path,
    get_temp_json_path,
)
from services.migration_service import initialise_temp_json_if_needed, update_temp_json_paths
from services.motor_service import get_motor_stable_timestamps
from services.image_service import extract_frame_at_time
from services.thumbnail_service import ThumbnailWorkerMulti, THUMB_W, THUMB_H
from services.sound_service import get_sound_service
from views.dialogs.map_dialog import MapDialog, MapBridge
from views.widgets.video_bar_delegate import VideoBarDelegate

_STATION_TIME_SORT_MISSING = "99:99"


def _get_station_time(video_path: str, cache: dict) -> str:
    """Retourne 'HH:MM' depuis systemEvent.csv du dossier vidéo, '99:99' si absent."""
    folder = os.path.dirname(video_path)
    if folder in cache:
        return cache[folder]
    result = _STATION_TIME_SORT_MISSING
    csv_path = os.path.join(folder, "systemEvent.csv")
    if os.path.exists(csv_path):
        for enc in ("utf-8", "cp1252"):
            try:
                with open(csv_path, "r", encoding=enc, errors="replace") as _f:
                    content = _f.read()
                dialect = csv.Sniffer().sniff(content[:2048])
                rows = list(csv.reader(content.splitlines(), dialect))
                if not rows:
                    break
                header = [h.strip().lower() for h in rows[0]]
                if "heure" not in header:
                    break
                h_idx = header.index("heure")
                ev_idx = header.index("event") if "event" in header else -1
                t_str = ""
                for r in rows[1:]:
                    if len(r) > h_idx:
                        if ev_idx >= 0 and len(r) > ev_idx and r[ev_idx].strip().upper() == "START ENCODER":
                            t_str = r[h_idx].strip()
                            break
                        elif not t_str:
                            t_str = r[h_idx].strip()
                if t_str:
                    t = datetime.strptime(t_str, "%Hh%Mm%Ss")
                    result = t.strftime("%H:%M")
                break
            except Exception:
                continue
    cache[folder] = result
    return result


def _get_point_name(video_path: str, working_dir: str) -> str:
    """Retourne le numéro du point depuis le JSON de la vidéo, '' si absent."""
    try:
        json_path = resolve_video_json_path(working_dir, video_path)
        if not os.path.exists(json_path):
            return ""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        val = data.get("video_observation", {}).get("point_name", {})
        if isinstance(val, dict):
            v = val.get("value")
        else:
            v = val
        if v is None:
            return ""
        try:
            return str(int(str(v)))  # supprime les zéros de tête pour l'affichage
        except ValueError:
            return str(v)
    except Exception:
        return ""


class _CameraFrameWorker(QtCore.QThread):
    """Extrait les frames de rotation moteur en parallèle via un pool de threads."""
    frame_ready = QtCore.pyqtSignal(int, object)   # (slot_id, ndarray or None)

    def __init__(self, tasks: list, parent=None):
        super().__init__(parent)
        self._tasks = tasks   # list of (slot_id, video_path, timestamp_s)

    def run(self):
        def _extract(task):
            slot_id, video_path, ts = task
            return slot_id, extract_frame_at_time(video_path, ts)

        n_workers = min(4, len(self._tasks) or 1)
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_extract, t): t for t in self._tasks}
            for fut in as_completed(futures):
                if self.isInterruptionRequested():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    slot_id, frame = fut.result()
                    self.frame_ready.emit(slot_id, frame)
                except Exception:
                    pass


class QualifController:
    """Contrôleur de la page Qualification : gestion de l'arbre vidéo, de la poubelle et de la carte."""

    def __init__(self, widget: QtWidgets.QWidget, parent=None, on_before_delete=None, on_qualification_changed=None):
        """
        Args:
            on_before_delete: Callback appelé avec le chemin vidéo avant exclusion
                              (libère les handles fichiers des autres controllers).
        """
        self.widget = widget
        self.parent = parent
        self._on_before_delete = on_before_delete
        self._on_qualification_changed = on_qualification_changed
        self.on_qualification_resumed = None  # callback → appelé quand GARDER/JETER après qualif terminée
        self.current_language = 'en'
        self.system_data = None
        self.video_model = QtGui.QStandardItemModel()
        self.trash_model = QtGui.QStandardItemModel()
        self.selected_video_name = None
        self._selected_video_path: str | None = None
        self._video_row_icon_labels: dict = {}
        self._video_row_widgets: dict = {}
        self._miniature_pixmaps: list = []   # pixmaps de la vue courante (None = en cours de chargement)
        self._camera_slot_labels: dict = {}  # slot_id → (QFrame, QLabel_img, angle, ts)
        self.all_coords = {}
        self.campaign_fields = {}
        self._working_dir = ""
        self.current_campaign_folder = None
        self.current_json_path = None

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
            self.btn_save_campaign = QtWidgets.QPushButton(
                self.translate("Sauvegarder", "Save"))
            self.btn_save_campaign.setFixedHeight(28)
            self.btn_save_campaign.setStyleSheet(
                "QPushButton { background-color: #1a3a4a; color: #7ec8e3;"
                " border: 1px solid #2778a2; border-radius: 4px; font-size: 11px;"
                " font-weight: bold; }"
                "QPushButton:hover { background-color: #2778a2; color: white; }"
                "QPushButton:pressed { background-color: #1a5a7a; }"
            )
            self.btn_save_campaign.clicked.connect(self.save_all_campaign_fields)
            layout.addWidget(self.btn_save_campaign)

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
        if hasattr(self, 'map_dialog'):
            self.map_dialog.set_language(language)
        self.map_initialized = False
        if hasattr(self, 'lbl_section_title'):
            self.lbl_section_title.setText(self.translate("Propriétés de campagne", "Campaign Properties"))
        if hasattr(self, 'lbl_videos_title'):
            self.lbl_videos_title.setText(self.translate("Vidéos de campagne", "Campaign Videos"))
        if hasattr(self, 'lbl_trash_title'):
            self.lbl_trash_title.setText(self.translate("Vidéos supprimées", "Removed Videos"))
        header_labels = [
            self.translate("Fichier", "File"),
            self.translate("Durée", "Duration"),
            self.translate("Taille", "Size"),
        ]
        self.video_model.setHorizontalHeaderLabels(header_labels)
        self.trash_model.setHorizontalHeaderLabels(header_labels)
        if hasattr(self, 'btn_save_campaign'):
            self.btn_save_campaign.setText(self.translate("Sauvegarder", "Save"))
        if hasattr(self, '_video_row_widgets'):
            self._rebuild_video_rows()
        if getattr(self, '_campaign_properties_json_path', None):
            self.load_and_display_campaign_json(self._campaign_properties_json_path)

    # --- Init helpers ---

    def _init_video_list(self):
        """Configure le backend vidéo et crée le widget de liste personnalisé GARDER/JETER."""
        self.video_model.setHorizontalHeaderLabels(["File", "Duration", "Size", "Date"])
        self.video_tree.setModel(self.video_model)
        self.video_tree.setVisible(False)

        splitter = self.video_tree.parentWidget()
        self.widget_video_container = QtWidgets.QWidget()
        layout_block = QtWidgets.QVBoxLayout(self.widget_video_container)
        layout_block.setContentsMargins(0, 0, 0, 0)
        layout_block.setSpacing(3)

        self.lbl_videos_title = QtWidgets.QLabel("Campaign Videos")
        self.lbl_videos_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #F2BFB4;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif; padding-bottom: 2px;"
        )
        self.lbl_videos_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout_block.addWidget(self.lbl_videos_title)

        self._videos_scroll = QtWidgets.QScrollArea()
        self._videos_scroll.setWidgetResizable(True)
        self._videos_scroll.setStyleSheet("background-color: #0d1b2a; border: none;")
        self._videos_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._videos_scroll_content = QtWidgets.QWidget()
        self._videos_scroll_layout = QtWidgets.QVBoxLayout(self._videos_scroll_content)
        self._videos_scroll_layout.setContentsMargins(4, 4, 4, 4)
        self._videos_scroll_layout.setSpacing(2)
        self._videos_scroll_layout.addStretch()
        self._videos_scroll.setWidget(self._videos_scroll_content)
        layout_block.addWidget(self._videos_scroll)

        if hasattr(splitter, "indexOf"):
            index = splitter.indexOf(self.video_tree)
            splitter.insertWidget(index, self.widget_video_container)

    def _init_trash_list(self):
        """Configure le backend poubelle (modèle uniquement — arbre masqué dans la liste unifiée)."""
        if not self.trash_video_tree:
            return
        self.trash_model.setHorizontalHeaderLabels(["File", "Duration", "Size"])
        self.trash_video_tree.setModel(self.trash_model)
        self.trash_video_tree.setVisible(False)

        splitter_trash = self.trash_video_tree.parentWidget()
        self.widget_trash_container = QtWidgets.QWidget()
        layout_block_trash = QtWidgets.QVBoxLayout(self.widget_trash_container)
        layout_block_trash.setContentsMargins(0, 0, 0, 0)
        self.lbl_trash_title = QtWidgets.QLabel("Removed Videos")  # conservé pour set_language

        if hasattr(splitter_trash, "indexOf"):
            index_trash = splitter_trash.indexOf(self.trash_video_tree)
            layout_block_trash.addWidget(self.trash_video_tree)
            splitter_trash.insertWidget(index_trash, self.widget_trash_container)

        self.widget_trash_container.setVisible(False)

    def _configure_left_splitter(self):
        """Abaisse les minimums du splitter vertical gauche et fixe les facteurs d'étirement."""
        if not self.frame_campaign:
            return
        splitter = self.frame_campaign.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            return

        self.frame_campaign.setMinimumHeight(120)
        if hasattr(self, 'widget_video_container'):
            self.widget_video_container.setMinimumHeight(80)

        # Section campagne fixe (stretch 0), liste vidéo prend le reste (stretch 2)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 0)  # container poubelle masqué

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
        campaign_h = max(320, int(total * 0.45))
        video_h = max(80, total - campaign_h)
        splitter.setSizes([campaign_h, video_h, 0])

    # --- Liste GARDER / JETER ---

    def _rebuild_video_rows(self):
        """Reconstruit la liste unifiée des vidéos avec les boutons GARDER et JETER."""
        if not hasattr(self, '_videos_scroll_layout'):
            return

        # Mémorise la position du scroll pour la restaurer après rebuild
        _scroll_bar = self._videos_scroll.verticalScrollBar() if hasattr(self, '_videos_scroll') else None
        _saved_scroll = _scroll_bar.value() if _scroll_bar else 0

        self._video_row_icon_labels.clear()
        self._video_row_widgets.clear()

        # Bloque les repaints pendant le rebuild pour éviter N passes de rendu
        _scroll_content = getattr(self, '_videos_scroll_content', None)
        if _scroll_content:
            _scroll_content.setUpdatesEnabled(False)

        # Vider le layout (garder le stretch en dernier)
        while self._videos_scroll_layout.count() > 1:
            item = self._videos_scroll_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # Pré-calcule une seule fois les fichiers de chaque répertoire pour la
        # détection des segments (évite N appels os.listdir sur le même dossier)
        import re as _re
        _dir_cache: dict[str, list[str]] = {}

        def _check_has_segments(vpath: str, vstem: str) -> bool:
            if _re.search(r'_\d+$', vstem):
                return False
            d = os.path.dirname(vpath)
            if d not in _dir_cache:
                _dir_cache[d] = os.listdir(d) if os.path.isdir(d) else []
            pat = _re.compile(rf'^{_re.escape(vstem)}_\d+\.mp4$', _re.IGNORECASE)
            return any(pat.match(f) for f in _dir_cache[d])

        # Collecte toutes les vidéos (gardées + jetées) — heure déjà stockée en UserRole+2
        all_rows = []
        for _model, _is_trash in ((self.video_model, False), (self.trash_model, True)):
            for row in range(_model.rowCount()):
                item = _model.item(row, 0)
                if not item:
                    continue
                video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if not video_path:
                    continue
                st = item.data(QtCore.Qt.ItemDataRole.UserRole + 2) or _STATION_TIME_SORT_MISSING
                all_rows.append({
                    "video_path": str(video_path),
                    "video_name": item.text(),
                    "duration": (_model.item(row, 1).text() if _model.item(row, 1) else ""),
                    "size": (_model.item(row, 2).text() if _model.item(row, 2) else ""),
                    "icon": item.icon(),
                    "is_trash": _is_trash,
                    "station_time": st if st != _STATION_TIME_SORT_MISSING else "",
                })

        # Tri par heure de station, puis numéro de fichier caméra
        def _chrono_key(entry: dict) -> tuple:
            item0 = None
            for _m in (self.video_model, self.trash_model):
                for r in range(_m.rowCount()):
                    it = _m.item(r, 0)
                    if it and str(it.data(QtCore.Qt.ItemDataRole.UserRole)) == entry["video_path"]:
                        item0 = it
                        break
                if item0:
                    break
            time_key = (item0.data(QtCore.Qt.ItemDataRole.UserRole + 2) or _STATION_TIME_SORT_MISSING) if item0 else _STATION_TIME_SORT_MISSING
            stem = os.path.splitext(os.path.basename(entry["video_path"]))[0]
            try:
                nums = _re.findall(r'\d+', stem)
                num = int(nums[-1]) if nums else 9_999_999
            except Exception:
                num = 9_999_999
            return (time_key, num)

        all_rows.sort(key=lambda e: (
            e.get("station_time") or _STATION_TIME_SORT_MISSING,
            int(_re.findall(r'\d+', os.path.splitext(os.path.basename(e["video_path"]))[0])[-1])
            if _re.findall(r'\d+', os.path.splitext(os.path.basename(e["video_path"]))[0]) else 9_999_999
        ))

        # Rendu de la liste unifiée triée
        prev_was_primary = False
        for entry in all_rows:
            video_path = entry["video_path"]
            stem = os.path.splitext(os.path.basename(video_path))[0]
            is_seg = bool(_re.search(r"_\d+$", stem))
            segs = _check_has_segments(video_path, stem)
            link_pos = ""
            if segs:
                link_pos = "primary"
            elif is_seg and prev_was_primary:
                link_pos = "segment"

            if link_pos == "segment":
                color = self._get_completion_color(video_path)
                bridge = QtWidgets.QWidget()
                bridge.setFixedHeight(2)
                b_lay = QtWidgets.QHBoxLayout(bridge)
                b_lay.setContentsMargins(4, 0, 0, 0)
                b_lay.setSpacing(0)
                connector = QtWidgets.QFrame()
                connector.setFixedSize(4, 2)
                connector.setStyleSheet(
                    f"background-color: {color.name()}; border: none;"
                )
                b_lay.addWidget(connector)
                b_lay.addStretch()
                self._videos_scroll_layout.insertWidget(
                    self._videos_scroll_layout.count() - 1, bridge
                )

            row_widget = self._build_video_row_widget(
                video_path=video_path,
                video_name=entry["video_name"],
                duration=entry["duration"],
                size=entry["size"],
                icon=entry["icon"],
                is_trash=entry["is_trash"],
                link_pos=link_pos,
                station_time=entry.get("station_time", ""),
            )
            self._videos_scroll_layout.insertWidget(
                self._videos_scroll_layout.count() - 1, row_widget
            )
            prev_was_primary = (link_pos == "primary")

        # Réactive les repaints et force un seul repaint global
        if _scroll_content:
            _scroll_content.setUpdatesEnabled(True)

        # Restaure la position du scroll après rebuild (via QTimer pour laisser le
        # layout se recalculer avant de forcer la valeur)
        if _scroll_bar and _saved_scroll > 0:
            QtCore.QTimer.singleShot(0, lambda v=_saved_scroll: _scroll_bar.setValue(v))

    def _build_video_row_widget(self, video_path: str, video_name: str,
                                duration: str, size: str,
                                icon: "QtGui.QIcon", is_trash: bool,
                                link_pos: str = "",
                                station_time: str = "") -> QtWidgets.QFrame:
        # link_pos : "" = normal, "primary" = connecté en bas, "segment" = connecté en haut
        """Construit un widget de ligne vidéo avec indicateur couleur, vignette et boutons."""
        is_selected = video_path == (self._selected_video_path or "")
        bg = "#1e3a50" if is_selected else ("#111820" if is_trash else "#1a2a3a")
        border = "#2778a2" if is_selected else ("#111820" if is_trash else "#1a2a3a")

        frame = QtWidgets.QFrame()
        frame.setFixedHeight(56)
        frame.setStyleSheet(
            f"QFrame#vrow {{ background-color: {bg}; border-radius: 4px;"
            f" border: 1px solid {border}; }}"
        )
        frame.setObjectName("vrow")

        hlayout = QtWidgets.QHBoxLayout(frame)
        hlayout.setContentsMargins(4, 4, 4, 4)
        hlayout.setSpacing(5)

        # Barre de couleur (indicateur de complétion)
        color = self._get_completion_color(video_path)
        if is_trash:
            color = QtGui.QColor("#555555")
        # Arrondi selon la position dans un groupe de segments liés
        if link_pos == "primary":
            bar_radius = "border-top-left-radius: 2px; border-top-right-radius: 2px; border-bottom-left-radius: 0px; border-bottom-right-radius: 0px;"
        elif link_pos == "segment":
            bar_radius = "border-top-left-radius: 0px; border-top-right-radius: 0px; border-bottom-left-radius: 2px; border-bottom-right-radius: 2px;"
        else:
            bar_radius = "border-radius: 2px;"
        color_bar = QtWidgets.QFrame()
        color_bar.setFixedWidth(4)
        color_bar.setStyleSheet(
            f"background-color: {color.name()}; {bar_radius} border: none;"
        )
        hlayout.addWidget(color_bar)

        # Vignette
        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setFixedSize(THUMB_W, THUMB_H)
        icon_lbl.setScaledContents(True)
        icon_lbl.setStyleSheet("background-color: #0a1520; border-radius: 3px; border: none;")
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(THUMB_W, THUMB_H))
        hlayout.addWidget(icon_lbl)
        self._video_row_icon_labels[video_path] = icon_lbl

        # Nom + infos
        info_col = QtWidgets.QWidget()
        info_col.setStyleSheet("background: transparent;")
        info_col.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        info_layout = QtWidgets.QVBoxLayout(info_col)
        info_layout.setContentsMargins(2, 0, 2, 0)
        info_layout.setSpacing(2)

        lbl_name = QtWidgets.QLabel(video_name)
        lbl_name.setStyleSheet(
            f"color: {'#777777' if is_trash else '#d4e8f5'};"
            " font-size: 11px; font-weight: bold; background: transparent;"
        )
        lbl_name.setToolTip(video_name)
        lbl_name.setWordWrap(False)

        time_label = self.translate("Heure de prise", "Recording time")
        dur_label = self.translate("Durée", "Duration")
        time_part = f"{time_label} : {station_time}    " if station_time else ""

        duration_min = VideoBarDelegate._parse_duration_minutes(duration)
        size_mb = VideoBarDelegate._parse_size_mb(size)
        is_short_or_light = (
            (duration_min is not None and duration_min < 9)
            or (size_mb is not None and size_mb < 500)
        )
        warn_color = "#FF3B30" if is_short_or_light else "#90b8d0"
        lbl_info = QtWidgets.QLabel(
            f"{time_part}<span style=\"color:{warn_color};\">{dur_label} : {duration}    {size}</span>"
        )
        lbl_info.setStyleSheet("color: #90b8d0; font-size: 10px; background: transparent;")
        lbl_info.setTextFormat(QtCore.Qt.TextFormat.RichText)

        info_layout.addWidget(lbl_name)
        info_layout.addWidget(lbl_info)
        hlayout.addWidget(info_col)

        # Bouton GARDER
        btn_garder = QtWidgets.QPushButton(self.translate("GARDER", "KEEP"))
        btn_garder.setFixedSize(68, 28)
        if not is_trash:
            btn_garder.setStyleSheet(
                "QPushButton { background-color: #1e5c30; color: #7dffaa;"
                " border: 1px solid #4CAF50; border-radius: 4px;"
                " font-size: 10px; font-weight: bold; }"
                " QPushButton:hover { background-color: #2e7a42; }"
            )
        else:
            btn_garder.setStyleSheet(
                "QPushButton { background-color: #111e14; color: #3a5a42;"
                " border: 1px solid #223322; border-radius: 4px;"
                " font-size: 10px; font-weight: bold; }"
                " QPushButton:hover { background-color: #1e4028; color: #7dffaa; }"
            )

        # Bouton JETER
        btn_jeter = QtWidgets.QPushButton(self.translate("JETER", "DISCARD"))
        btn_jeter.setFixedSize(68, 28)
        if is_trash:
            btn_jeter.setStyleSheet(
                "QPushButton { background-color: #5c1e1e; color: #ff8080;"
                " border: 1px solid #D94F38; border-radius: 4px;"
                " font-size: 10px; font-weight: bold; }"
                " QPushButton:hover { background-color: #7a2e2e; }"
            )
        else:
            btn_jeter.setStyleSheet(
                "QPushButton { background-color: #1e1111; color: #5a3a3a;"
                " border: 1px solid #331111; border-radius: 4px;"
                " font-size: 10px; font-weight: bold; }"
                " QPushButton:hover { background-color: #402020; color: #ff8080; }"
            )

        hlayout.addWidget(btn_garder)
        hlayout.addWidget(btn_jeter)

        self._video_row_widgets[video_path] = frame

        # Connexions
        if not is_trash:
            btn_garder.clicked.connect(
                lambda _, p=video_path: self._on_video_row_clicked(p)
            )
            btn_jeter.clicked.connect(
                lambda _, p=video_path: self._move_to_trash_by_path(p)
            )
        else:
            btn_garder.clicked.connect(
                lambda _, p=video_path: self._restore_from_trash_by_path(p)
            )
            btn_jeter.clicked.connect(
                lambda _, p=video_path: self._on_video_row_clicked(p)
            )
        frame.mousePressEvent = lambda _e, p=video_path: self._on_video_row_clicked(p)

        return frame

    def _on_video_row_clicked(self, video_path: str):
        """Sélectionne une vidéo depuis la liste personnalisée."""
        prev_path = self._selected_video_path
        self._selected_video_path = video_path

        # Mettre à jour le style des lignes affectées sans reconstruire la liste
        for path, frame in self._video_row_widgets.items():
            if path not in (prev_path, video_path):
                continue
            is_sel = path == video_path
            is_t = not any(
                self.video_model.item(r, 0) is not None
                and str(self.video_model.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole)) == path
                for r in range(self.video_model.rowCount())
            )
            bg = "#1e3a50" if is_sel else ("#111820" if is_t else "#1a2a3a")
            bd = "#2778a2" if is_sel else ("#111820" if is_t else "#1a2a3a")
            frame.setStyleSheet(
                f"QFrame#vrow {{ background-color: {bg}; border-radius: 4px;"
                f" border: 1px solid {bd}; }}"
            )

        # Résoudre le nom
        video_name = None
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == video_path:
                video_name = item.text()
                break
        if video_name is None:
            for row in range(self.trash_model.rowCount()):
                item = self.trash_model.item(row, 0)
                if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == video_path:
                    video_name = item.text()
                    break

        if video_name:
            self.selected_video_name = video_name

        video_dir = os.path.dirname(video_path)
        csv_system = os.path.join(video_dir, "systemEvent.csv")
        if os.path.exists(csv_system):
            self.update_camera_views(video_path, csv_system)

        self.current_json_path = resolve_video_json_path(self._working_dir, video_path)
        self.update_minimap(selected_name=video_name, show_dialog=False)

    def _move_to_trash_by_path(self, video_path: str):
        """Déplace une vidéo vers la corbeille depuis son chemin."""
        if self.on_qualification_resumed:
            self.on_qualification_resumed()
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == video_path:
                self.delete_video_by_index(self.video_model.index(row, 0))
                return

    def _restore_from_trash_by_path(self, video_path: str):
        """Restaure une vidéo depuis la corbeille."""
        if self.on_qualification_resumed:
            self.on_qualification_resumed()
        for row in range(self.trash_model.rowCount()):
            item = self.trash_model.item(row, 0)
            if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == video_path:
                self.restore_video_by_index(self.trash_model.index(row, 0))
                return

    def _init_minimap(self):
        """Crée le MapBridge, le WebChannel et le QDialog carte de campagne."""
        self.bridge = MapBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.bridge)
        self.bridge.videoSelected.connect(self.select_video_by_name)
        self.map_dialog = MapDialog(self.bridge, self.channel, parent=self.widget, language=self.current_language)
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

    def refresh_item_indicator(self, item, video_path):
        """Colore l'item en vert si qualifiée, sinon gris-bleu — préserve les badges de type."""
        # Ne pas écraser la couleur de badge (stéréo/segments)
        if item.data(QtCore.Qt.ItemDataRole.UserRole + 1):
            return
        json_path = resolve_video_json_path(self._working_dir, video_path)
        is_processed = False
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                val = str(data.get("video_observation", {}).get("exploitable", {}).get("value", "") or "").strip()
                if val and val != '?':
                    is_processed = True
            except Exception:
                pass
        color = "#4CAF50" if is_processed else "#b0bec5"
        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))

    def initialize_tree_indicators(self):
        """Initialise la couleur de tous les items de l'arbre au chargement d'une campagne."""
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    self.refresh_item_indicator(item, path)

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

        _time_cache: dict = {}
        for video in videos:
            stem = os.path.splitext(video["name"])[0]
            # Les fichiers _stereo.mp4 ne sont pas des entrées indépendantes
            if stem.lower().endswith("_stereo"):
                continue
            col_name = QtGui.QStandardItem(video["name"])
            col_dur = QtGui.QStandardItem(video["duration"])
            size_str = video.get("size") or (
                f"{os.path.getsize(video['path']) / (1024 * 1024):.2f} MB"
                if os.path.exists(video["path"]) else "--"
            )
            col_size = QtGui.QStandardItem(size_str)
            col_date = QtGui.QStandardItem(video["date"])
            col_name.setData(video["path"], QtCore.Qt.ItemDataRole.UserRole)
            col_name.setData(_get_station_time(video["path"], _time_cache), QtCore.Qt.ItemDataRole.UserRole + 2)
            col_name.setData(_get_point_name(video["path"], self._working_dir), QtCore.Qt.ItemDataRole.UserRole + 3)
            sys_name = get_system_name(video["path"])
            is_stereo_video, _ = check_stereo_status(video["path"])
            segs = get_sequential_segments(video["path"])
            if is_stereo_video:
                col_name.setToolTip("Vidéo stéréo — flux gauche + flux droit")
                col_name.setForeground(QtGui.QBrush(QtGui.QColor("#4a9fcf")))
                col_name.setData("#4a9fcf", QtCore.Qt.ItemDataRole.UserRole + 1)
                col_name.setText(video["name"] + f"  {sys_name} · STEREO")
            elif segs:
                names = ", ".join(os.path.basename(s) for s in segs)
                col_name.setToolTip(f"Vidéo scindée — segment(s) lié(s) : {names}")
                col_name.setForeground(QtGui.QBrush(QtGui.QColor("#E8C838")))
                col_name.setData("#E8C838", QtCore.Qt.ItemDataRole.UserRole + 1)
                col_name.setText(video["name"] + f"  {sys_name} · [+{len(segs)}]")
            else:
                col_name.setText(video["name"] + f"  {sys_name} · MONO")
            self.video_model.appendRow([col_name, col_dur, col_size, col_date])

            coords = get_video_gps_coords(video["path"])
            if coords:
                self.all_coords[video["name"]] = coords

        self.update_minimap(self.selected_video_name, show_dialog=False)
        self._start_thumbnail_generation()

        for video in videos:
            initialise_temp_json_if_needed(video["path"])    # crée <stem>_temp.json (valeurs nulles)
            update_temp_json_paths(video["path"])             # remplit les champs chemin si absents

        # Doit s'exécuter avant le choix du JSON de référence ci-dessous : une vidéo
        # mise à la corbeille (qualifiable='no') sort de video_model et ne reçoit plus
        # les écritures de synchronize_campaign_field. Il ne faut donc jamais choisir
        # sa _temp.json comme référence pour les propriétés de campagne.
        self._restore_qualifiable_state()

        # JSON de référence pour les propriétés de campagne + infos système : on prend la
        # première vidéo encore présente dans video_model (donc synchronisée par
        # synchronize_campaign_field), jamais une vidéo trouvée dans le dossier mais
        # déjà écartée.
        first_loaded_json = None
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            vp = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if not vp:
                continue
            json_path = get_temp_json_path(str(vp))
            if os.path.exists(json_path):
                first_loaded_json = json_path
                break

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
        self._rebuild_video_rows()

    # ── Indicateur de complétion ─────────────────────────────────────────

    def _get_completion_color(self, video_path: str) -> QtGui.QColor:
        """Rouge / orange / vert selon le remplissage des champs critiques du JSON.

        Résultat mis en cache pour éviter de relire le JSON à chaque rebuild de liste.
        """
        if not hasattr(self, '_completion_cache'):
            self._completion_cache: dict[str, QtGui.QColor] = {}
        if video_path in self._completion_cache:
            return self._completion_cache[video_path]

        json_path = resolve_video_json_path(self._working_dir, video_path)
        if not os.path.exists(json_path):
            color = QtGui.QColor("#D94F38")
            self._completion_cache[video_path] = color
            return color
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            color = QtGui.QColor("#D94F38")
            self._completion_cache[video_path] = color
            return color

        def _filled(block: dict, key: str) -> bool:
            entry = block.get(key, {})
            val = entry.get("value") if isinstance(entry, dict) else entry
            return bool(val and str(val).strip() not in ("", "None", "null"))

        obs  = data.get("video_observation", {})
        surv = data.get("survey", {})
        critical  = [_filled(obs, "codeObs"), _filled(obs, "exploitable")]
        important = [_filled(obs, "habitat"), _filled(obs, "depth"), _filled(surv, "date")]

        if not all(critical):
            color = QtGui.QColor("#D94F38")
        elif sum(important) < 2:
            color = QtGui.QColor("#E8A838")
        else:
            color = QtGui.QColor("#5DBB63")
        self._completion_cache[video_path] = color
        return color

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
        # Invalide le cache pour que _get_completion_color relise le JSON
        if hasattr(self, '_completion_cache'):
            self._completion_cache.pop(str(video_path), None)
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == str(video_path):
                self._apply_completion_color(row)
                self._rebuild_video_rows()
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
        """Applique la vignette sur l'item du modèle et sur la liste personnalisée."""
        model = self.video_model if model_key == 'main' else self.trash_model
        item = model.item(row, 0)
        if item:
            item.setIcon(icon)
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if video_path:
                lbl = self._video_row_icon_labels.get(str(video_path))
                if lbl:
                    lbl.setPixmap(icon.pixmap(THUMB_W, THUMB_H))

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
            stem = os.path.splitext(video["name"])[0]
            if stem.lower().endswith("_stereo"):
                continue  # fichier secondaire stéréo, non affiché séparément
            if video["path"] not in all_known:
                col_name = QtGui.QStandardItem(video["name"])
                col_name.setData(video["path"], QtCore.Qt.ItemDataRole.UserRole)
                sys_name = get_system_name(video["path"])
                is_stereo_video, _ = check_stereo_status(video["path"])
                segs = get_sequential_segments(video["path"])
                if is_stereo_video:
                    col_name.setToolTip("Vidéo stéréo — flux gauche + flux droit")
                    col_name.setForeground(QtGui.QBrush(QtGui.QColor("#4a9fcf")))
                    col_name.setData("#4a9fcf", QtCore.Qt.ItemDataRole.UserRole + 1)
                    col_name.setText(video["name"] + f"  {sys_name} · STEREO")
                elif segs:
                    names = ", ".join(os.path.basename(s) for s in segs)
                    col_name.setToolTip(f"Vidéo scindée — segment(s) lié(s) : {names}")
                    col_name.setForeground(QtGui.QBrush(QtGui.QColor("#E8C838")))
                    col_name.setData("#E8C838", QtCore.Qt.ItemDataRole.UserRole + 1)
                    col_name.setText(video["name"] + f"  {sys_name} · [+{len(segs)}]")
                else:
                    col_name.setText(video["name"] + f"  {sys_name} · MONO")
                self.video_model.appendRow([
                    col_name,
                    QtGui.QStandardItem(video["duration"]),
                    QtGui.QStandardItem(video.get("size", "--")),
                    QtGui.QStandardItem(video.get("date", "")),
                ])
                coords = get_video_gps_coords(video["path"])
                if coords:
                    self.all_coords[video["name"]] = coords

        self._start_watching_campaign(self.current_campaign_folder)
        self._rebuild_video_rows()

    def load_and_display_campaign_json(self, json_path: str):
        if not hasattr(self, 'scroll_campaign') or not self.scroll_campaign:
            return
        # Mémorisé pour pouvoir reconstruire le formulaire (labels name_fr/name) sans
        # relire le disque quand set_language() change la langue en cours de session.
        self._campaign_properties_json_path = json_path

        # Remplacer le widget interne — évite "QWidget already has a layout"
        # causé par deleteLater() asynchrone sur l'ancien layout.
        new_container = QtWidgets.QWidget()
        self.scroll_campaign.setWidget(new_container)   # QScrollArea supprime l'ancien
        self.dynamic_form_container = new_container
        self.campaign_fields.clear()

        # Charge le template pour avoir la liste complète et ordonnée des champs survey
        _template_path = os.path.join(os.path.dirname(__file__), '..', 'template.json')
        template_survey: dict = {}
        try:
            with open(_template_path, 'r', encoding='utf-8') as _tf:
                template_survey = json.load(_tf).get("survey", {})
        except Exception:
            pass

        # Charge les valeurs actuelles depuis le JSON de campagne
        campaign_survey: dict = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    _payload = json.load(f)
                campaign_survey = _payload.get("survey", {})
            except Exception as e:
                print(f"Error loading campaign JSON: {e}")

        # Fusion : template donne l'ordre et les métadonnées, campagne donne les valeurs
        merged: dict = {}
        for key, tmpl_meta in template_survey.items():
            merged[key] = dict(tmpl_meta)
            if key in campaign_survey:
                merged[key]["value"] = campaign_survey[key].get("value")
        # Champs présents dans la campagne mais absents du template (rétrocompat)
        for key, meta in campaign_survey.items():
            if key not in merged:
                merged[key] = meta

        _HIDDEN_SURVEY_KEYS = {"campagne", "site", "protectionStatus1", "protectionStatus2",
                               "campaign", "campaign_code", "campaign_name", "mission",
                               # Gérés ailleurs : datawork_folder/video_subfolder sont
                               # recalculés automatiquement depuis le chemin (jamais saisis
                               # à la main) ; survey_name est le champ "Nom de campagne" de
                               # la page Métadonnées, pas un champ de cette page.
                               "datawork_folder", "video_subfolder", "survey_name"}
        _HIDDEN_SURVEY_LABELS = {"campagne", "site", "statut de protection 1",
                                  "statut de protection 2", "campaign"}

        if merged:
            form_layout = QtWidgets.QFormLayout(self.dynamic_form_container)
            form_layout.setContentsMargins(6, 4, 6, 4)
            form_layout.setSpacing(4)
            form_layout.setVerticalSpacing(4)
            form_layout.setHorizontalSpacing(8)
            form_layout.setFieldGrowthPolicy(
                QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for key, meta in merged.items():
                if key in _HIDDEN_SURVEY_KEYS:
                    continue
                name_key = "name_fr" if self.current_language == 'fr' else "name"
                display_name = str(meta.get(name_key) or meta.get("name_fr", key)).capitalize()
                if display_name.lower() in _HIDDEN_SURVEY_LABELS:
                    continue
                value_str = str(meta.get("value") or "")
                input_field = QtWidgets.QLineEdit()
                input_field.setText(value_str)
                input_field.setFixedHeight(24)
                input_field.setStyleSheet(
                    "QLineEdit { font-size: 11px; padding: 1px 5px;"
                    " color: #ffffff; background-color: #1a1a1a;"
                    " border: 1px solid #555555; border-radius: 3px; }"
                )
                if meta.get("example"):
                    input_field.setPlaceholderText(str(meta["example"]))
                if value_str:
                    input_field.setToolTip(value_str)
                self.campaign_fields[key] = input_field
                input_field.editingFinished.connect(
                    lambda tk=key: self.on_campaign_field_modified(tk))
                input_field.textChanged.connect(
                    lambda txt, f=input_field: f.setToolTip(txt))
                lbl = QtWidgets.QLabel(f"{display_name} :")
                lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #a0b8c8;")
                form_layout.addRow(lbl, input_field)
            return

        fallback_layout = QtWidgets.QVBoxLayout(self.dynamic_form_container)
        lbl_error = QtWidgets.QLabel(self.translate(
            "Aucune donnée de campagne active.", "No active campaign data found."))
        lbl_error.setStyleSheet("color: #aaaaaa; font-style: italic; font-size: 11px;")
        lbl_error.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        fallback_layout.addWidget(lbl_error)

    def on_campaign_field_modified(self, key: str):
        """Synchronise un champ campagne dans tous les _temp.json quand l'utilisateur l'édite."""
        widget = self.campaign_fields.get(key)
        if widget:
            self.synchronize_campaign_field(key, widget.text())

    def save_all_campaign_fields(self):
        """Sauvegarde tous les champs de campagne dans les _temp.json de toutes les vidéos."""
        if not self.campaign_fields:
            return
        count = 0
        for key, widget in self.campaign_fields.items():
            self.synchronize_campaign_field(key, widget.text())
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                count += 1
        print(f"[CAMPAIGN] {len(self.campaign_fields)} champs sauvegardés dans {count} vidéos")
        if hasattr(self, 'btn_save_campaign'):
            self.btn_save_campaign.setText(self.translate("✓ Sauvegardé", "✓ Saved"))
            QtCore.QTimer.singleShot(2000, lambda: self.btn_save_campaign.setText(
                self.translate("Sauvegarder", "Save")))

        if self.frame_campaign:
            self.frame_campaign.setStyleSheet(
                "background-color: rgb(32, 65, 93);"
                "border-radius: 10px;"
                "border: 2px solid #5bb8f5;"
            )
            QtCore.QTimer.singleShot(2000, lambda: self.frame_campaign.setStyleSheet(
                "background-color: rgb(32, 65, 93);"
                "border-radius: 10px;"
                "border: 1px solid #152d42;"
            ))

    def synchronize_campaign_field(self, key: str, value: str):
        """Écrit value dans le champ key de la section survey de chaque _temp.json vidéo."""
        # Un champ vide reste "non renseigné" (null), jamais une chaîne vide : sinon
        # "Sauvegarder" écrase le null d'origine par "" pour tous les champs jamais
        # remplis, ce qui casse les vérifications type "if not value" ailleurs dans
        # le code qui s'attendent à une absence de donnée cohérente.
        normalized_value = value if value else None
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path or not os.path.exists(video_path):
                continue
            json_path = get_temp_json_path(str(video_path))
            if not os.path.isfile(json_path):
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                survey = data.setdefault("survey", {})
                if key in survey:
                    survey[key]["value"] = normalized_value
                else:
                    survey[key] = {"value": normalized_value}
                print(f"[TEMP_JSON] {os.path.basename(json_path)} ← survey.{key} = {normalized_value!r}")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[CAMPAIGN SYNC] {key} → {os.path.basename(json_path)} : {e}")

    # --- Video selection ---

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Met à jour la minimap et le panneau d'exploitabilité quand l'utilisateur clique sur une vidéo."""
        item = self.video_model.itemFromIndex(index.siblingAtColumn(0))
        if not item:
            return
        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        video_name = item.text()
        self.selected_video_name = video_name

        video_dir = os.path.dirname(video_path)
        csv_system = os.path.join(video_dir, "systemEvent.csv")
        if os.path.exists(csv_system):
            self.update_camera_views(video_path, csv_system)

        self.current_json_path = resolve_video_json_path(self._working_dir, video_path)
        self.update_minimap(selected_name=video_name, show_dialog=False)

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
            jpath = get_temp_json_path(vpath)
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
                    tooltip=self.translate("Tracé GPS (ordre chronologique)", "GPS track (chronological order)"),
                ).add_to(m)

            for name, coords in valid_coords.items():
                wp = waypoints.get(name, "")
                popup_html = (
                    f'<div style="font-family:\'Segoe UI\',sans-serif;font-size:12px;'
                    f'min-width:120px;">'
                    f'<b style="font-size:13px;">{name}</b>'
                    + (f'<br><span style="color:#607080;">{self.translate("GPS Waypoint :", "GPS Waypoint:")}</span> '
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
                no_gps_text = self.translate(
                    "Aucune donnée GPS disponible pour cette campagne",
                    "No GPS data available for this campaign",
                )
                no_gps_html = f"""
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
                    {no_gps_text}
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
                video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if video_path:
                    self._on_video_row_clicked(str(video_path))
                break

    # --- Camera views / thumbnails ---

    def update_camera_views(self, video_path: str, csv_path: str):
        """Affiche immédiatement des placeholders puis charge les frames en parallèle en arrière-plan."""
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._miniature_pixmaps.clear()
        self._camera_slot_labels.clear()

        # Arrêter le worker précédent si actif
        if hasattr(self, '_cam_worker') and self._cam_worker and self._cam_worker.isRunning():
            self._cam_worker.requestInterruption()
            self._cam_worker.wait(400)

        try:
            motor_events = get_motor_stable_timestamps(csv_path, delay=6.0)
            if not motor_events:
                lbl = QtWidgets.QLabel(self.translate(
                    "Aucune rotation moteur trouvée dans le fichier CSV.",
                    "No motor rotation found in the CSV file."))
                lbl.setStyleSheet("color: white; font-size: 14px;")
                self.scroll_layout.addWidget(lbl)
                self.scroll_layout.addStretch()
                return

            tasks = []
            slot_id = 0
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
                    is_360 = evt_type == "rotation_360"
                    fw, fh = (248, 188) if is_360 else (240, 180)
                    border = "3px solid #ff3333" if is_360 else "1px solid #555555"

                    w_photo = QtWidgets.QFrame()
                    w_photo.setFixedSize(fw, fh)
                    w_photo.setStyleSheet(
                        f"background-color: #111a24; border-radius: 6px; border: {border};"
                    )

                    # Placeholder spinner
                    ph_layout = QtWidgets.QVBoxLayout(w_photo)
                    ph_layout.setContentsMargins(0, 0, 0, 0)
                    ph_lbl = QtWidgets.QLabel("⏳")
                    ph_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                    ph_lbl.setStyleSheet(
                        "color: #405060; font-size: 22px; background: transparent;"
                    )
                    ph_layout.addWidget(ph_lbl)

                    self._miniature_pixmaps.append(None)
                    self._camera_slot_labels[slot_id] = (w_photo, angle, ts)
                    tasks.append((slot_id, video_path, ts))
                    slot_id += 1
                    hbox.addWidget(w_photo)

                if len(rotation_events) < 6:
                    for _ in range(6 - len(rotation_events)):
                        hbox.addSpacing(240)
                hbox.addStretch()
                self.scroll_layout.addWidget(frame_rotation)

            self.scroll_layout.addStretch()

            if tasks:
                self._cam_worker = _CameraFrameWorker(tasks)
                self._cam_worker.frame_ready.connect(self._on_camera_frame_ready)
                self._cam_worker.start()

        except Exception as e:
            print(f"Error updating camera views: {e}")

    def _on_camera_frame_ready(self, slot_id: int, frame_data):
        """Appelé dans le thread principal quand une frame est prête : remplace le placeholder."""
        if frame_data is None or slot_id not in self._camera_slot_labels:
            return

        w_photo, angle, ts = self._camera_slot_labels[slot_id]

        # Construire le pixmap
        h_f, w_f, ch = frame_data.shape
        q_img = QtGui.QImage(
            frame_data.tobytes(), w_f, h_f, ch * w_f,
            QtGui.QImage.Format.Format_RGB888
        )
        pixmap = QtGui.QPixmap.fromImage(q_img)
        self._miniature_pixmaps[slot_id] = pixmap

        # Vider le layout placeholder
        old = w_photo.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(old)

        new_layout = QtWidgets.QVBoxLayout(w_photo)
        new_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QtWidgets.QLabel(w_photo)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setPixmap(pixmap.scaled(
            w_photo.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        ))
        new_layout.addWidget(lbl)

        # Overlay angle
        minutes = int(ts // 60)
        seconds_i = int(ts % 60)
        ms = int((ts - int(ts)) * 1000)

        angle_lbl = QtWidgets.QLabel(f" {angle}° ", lbl)
        angle_lbl.setStyleSheet(
            "background-color: rgba(0,0,0,160); color: #55ff55;"
            " font-weight: bold; border-radius: 3px; font-size: 10px;"
        )
        angle_lbl.adjustSize()
        angle_lbl.move(5, 5)
        angle_lbl.show()

        time_lbl = QtWidgets.QLabel(f" {minutes:02d}:{seconds_i:02d}.{ms:03d} ", lbl)
        time_lbl.setStyleSheet(
            "background-color: rgba(0,0,0,160); color: #ffffff;"
            " font-weight: bold; border-radius: 3px; font-size: 10px;"
        )
        time_lbl.adjustSize()
        time_lbl.move(w_photo.width() - time_lbl.width() - 5, 5)
        time_lbl.show()

        # Clic simple → plein écran
        for target in (w_photo, lbl):
            target.mousePressEvent = lambda _e, i=slot_id: self._show_fullscreen_image(i)
            target.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def _show_fullscreen_image(self, idx: int = 0):
        """Affiche une miniature en plein écran avec navigation ← → (flèches clavier + boutons)."""
        # Filtre les slots qui ont un pixmap réel (les autres sont encore en chargement)
        valid = [(i, p) for i, p in enumerate(self._miniature_pixmaps) if p is not None]
        if not valid:
            return

        # Trouve la position dans la liste filtrée la plus proche de idx demandé
        cur = 0
        for j, (orig_i, _) in enumerate(valid):
            if orig_i >= idx:
                cur = j
                break

        screen = QtWidgets.QApplication.primaryScreen().size()

        dlg = QtWidgets.QDialog(self.widget)
        dlg.setWindowFlags(
            QtCore.Qt.WindowType.Window |
            QtCore.Qt.WindowType.FramelessWindowHint
        )
        dlg.setStyleSheet("background-color: black;")
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

        outer = QtWidgets.QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        lbl_img = QtWidgets.QLabel()
        lbl_img.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl_img.setStyleSheet("background-color: black;")
        outer.addWidget(lbl_img, 1)

        bar = QtWidgets.QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background-color: rgba(0,0,0,180);")
        bar_layout = QtWidgets.QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 0, 16, 0)
        bar_layout.setSpacing(12)

        _btn_style = (
            "QPushButton{background:rgba(255,255,255,15);color:white;"
            "border:1px solid rgba(255,255,255,40);border-radius:5px;"
            "font-size:16px;font-weight:bold;padding:4px 14px;}"
            "QPushButton:hover{background:rgba(255,255,255,35);}"
            "QPushButton:disabled{color:rgba(255,255,255,30);border-color:rgba(255,255,255,15);}"
        )

        btn_prev = QtWidgets.QPushButton("←")
        btn_prev.setFixedSize(48, 32)
        btn_prev.setStyleSheet(_btn_style)

        lbl_counter = QtWidgets.QLabel()
        lbl_counter.setStyleSheet(
            "color:rgba(255,255,255,160);font-size:12px;background:transparent;"
        )
        lbl_counter.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        btn_next = QtWidgets.QPushButton("→")
        btn_next.setFixedSize(48, 32)
        btn_next.setStyleSheet(_btn_style)

        hint = QtWidgets.QLabel(self.translate(
            "Échap pour fermer  |  ← →  pour naviguer",
            "Escape to close  |  ← →  to navigate"))
        hint.setStyleSheet("color:rgba(255,255,255,60);font-size:10px;background:transparent;")

        btn_close = QtWidgets.QPushButton("✕")
        btn_close.setFixedSize(32, 32)
        btn_close.setStyleSheet(_btn_style)
        btn_close.clicked.connect(dlg.close)

        bar_layout.addWidget(btn_prev)
        bar_layout.addWidget(lbl_counter)
        bar_layout.addWidget(btn_next)
        bar_layout.addStretch()
        bar_layout.addWidget(hint)
        bar_layout.addWidget(btn_close)
        outer.addWidget(bar)

        state = {"cur": cur}

        def _show(j):
            j = max(0, min(j, len(valid) - 1))
            state["cur"] = j
            _, pix = valid[j]
            scaled = pix.scaled(
                screen,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            lbl_img.setPixmap(scaled)
            lbl_counter.setText(f"{j + 1} / {len(valid)}")
            btn_prev.setEnabled(j > 0)
            btn_next.setEnabled(j < len(valid) - 1)

        btn_prev.clicked.connect(lambda: _show(state["cur"] - 1))
        btn_next.clicked.connect(lambda: _show(state["cur"] + 1))

        def _key(event):
            k = event.key()
            if k == QtCore.Qt.Key.Key_Escape:
                dlg.close()
            elif k == QtCore.Qt.Key.Key_Left:
                _show(state["cur"] - 1)
            elif k == QtCore.Qt.Key.Key_Right:
                _show(state["cur"] + 1)

        dlg.keyPressEvent = _key
        # Pas de mousePressEvent sur lbl_img : évite de fermer par erreur au lieu de naviguer

        _show(state["cur"])
        dlg.showFullScreen()
        dlg.setFocus()  # indispensable avec FramelessWindowHint pour recevoir les touches

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

    def _restore_qualifiable_state(self):
        """Remet en corbeille les vidéos dont qualifiable='no' dans leur _temp.json (après chargement)."""
        rows_to_trash = []
        for row in range(self.video_model.rowCount()):
            name_item = self.video_model.item(row, 0)
            if not name_item:
                continue
            video_path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            json_path = resolve_video_json_path(self._working_dir, str(video_path))
            if not os.path.isfile(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as _f:
                    data = json.load(_f)
                val = (data.get("video_observation", {}).get("qualifiable") or {}).get("value")
                if str(val).lower() == "no":
                    rows_to_trash.append(row)
            except Exception:
                pass

        for row in reversed(rows_to_trash):
            name_item = self.video_model.item(row, 0)
            video_path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
            video_name = name_item.text()
            col_name = QtGui.QStandardItem(video_name)
            col_name.setData(video_path, QtCore.Qt.ItemDataRole.UserRole)
            col_name.setData(
                name_item.data(QtCore.Qt.ItemDataRole.UserRole + 2),
                QtCore.Qt.ItemDataRole.UserRole + 2,
            )
            col_name.setData(
                name_item.data(QtCore.Qt.ItemDataRole.UserRole + 3),
                QtCore.Qt.ItemDataRole.UserRole + 3,
            )
            items = [self.video_model.item(row, c) for c in range(5)]
            self.trash_model.appendRow(
                [col_name] + [QtGui.QStandardItem(items[c].text() if items[c] else "") for c in range(1, 5)]
            )
            self.video_model.removeRow(row)
            print(f"[QUALIF] Restauré en corbeille : {video_name}")

    def _set_qualifiable(self, video_path: str, value: str):
        """Écrit video_observation.qualifiable dans le JSON de travail ('yes' ou 'no')."""
        video_name = os.path.basename(str(video_path))
        if not self._working_dir or not video_path:
            print(f"[QUALIF] _set_qualifiable ignoré pour {video_name} : working_dir ou chemin manquant")
            return
        json_path = resolve_video_json_path(self._working_dir, str(video_path))
        if not os.path.exists(json_path):
            print(f"[QUALIF] _set_qualifiable ignoré pour {video_name} : JSON introuvable ({json_path})")
            return
        try:
            with open(json_path, "r", encoding="utf-8") as _f:
                data = json.load(_f)
            obs = data.setdefault("video_observation", {})
            previous = (obs.get("qualifiable") or {}).get("value", "<absent>")
            if "qualifiable" in obs:
                obs["qualifiable"]["value"] = value
            else:
                obs["qualifiable"] = {"value": value}
            with open(json_path, "w", encoding="utf-8") as _f:
                json.dump(data, _f, ensure_ascii=False, indent=2)
            print(f"[QUALIF] qualifiable mis à jour : {video_name}  {previous!r} → {value!r}  ({json_path})")
        except Exception as e:
            print(f"[QUALIF] Erreur _set_qualifiable pour {video_name} : {e}")

    def delete_video_by_index(self, index: QtCore.QModelIndex):
        """Déplace la vidéo dans la liste 'supprimées' (en mémoire) et supprime son dossier de sortie."""
        row = index.row()
        name_item = self.video_model.item(row, 0)
        if not name_item:
            return
        video_name = name_item.text()
        video_path = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
        get_sound_service().play("discard")

        if self._on_before_delete:
            self._on_before_delete(video_path)

        # Supprimer le sous-dossier de sortie en arrière-plan pour ne pas bloquer l'UI
        if self._working_dir and video_path:
            output_dir = get_working_video_dir(self._working_dir, video_path)
            if os.path.isdir(output_dir):
                def _rm(path):
                    try:
                        shutil.rmtree(path)
                    except Exception as e:
                        print(f"[QUALIF] Impossible de supprimer le dossier de sortie : {e}")
                threading.Thread(target=_rm, args=(output_dir,), daemon=True).start()

        items = [self.video_model.item(row, c) for c in range(5)]
        col_name = QtGui.QStandardItem(video_name)
        col_name.setData(video_path, QtCore.Qt.ItemDataRole.UserRole)
        col_name.setData(
            name_item.data(QtCore.Qt.ItemDataRole.UserRole + 2),
            QtCore.Qt.ItemDataRole.UserRole + 2,
        )
        col_name.setData(
            name_item.data(QtCore.Qt.ItemDataRole.UserRole + 3),
            QtCore.Qt.ItemDataRole.UserRole + 3,
        )
        self.trash_model.appendRow(
            [col_name] + [QtGui.QStandardItem(items[c].text() if items[c] else "") for c in range(1, 5)]
        )
        self.video_model.removeRow(row)
        self._set_qualifiable(video_path, "no")
        if self.selected_video_name == video_name:
            self.selected_video_name = None
            self._selected_video_path = None
        self._rebuild_video_rows()
        if self._on_qualification_changed:
            self._on_qualification_changed()

    def restore_video_by_index(self, index: QtCore.QModelIndex):
        """Remet la vidéo dans la liste principale et recrée son dossier de sortie."""
        row = index.row()
        item_name = self.trash_model.item(row, 0)
        if not item_name:
            return
        video_name = item_name.text()
        video_path = item_name.data(QtCore.Qt.ItemDataRole.UserRole)
        get_sound_service().play("keep")

        items = [self.trash_model.item(row, c) for c in range(5)]
        col_name = QtGui.QStandardItem(video_name)
        col_name.setData(video_path, QtCore.Qt.ItemDataRole.UserRole)
        col_name.setData(
            item_name.data(QtCore.Qt.ItemDataRole.UserRole + 2),
            QtCore.Qt.ItemDataRole.UserRole + 2,
        )
        col_name.setData(
            item_name.data(QtCore.Qt.ItemDataRole.UserRole + 3),
            QtCore.Qt.ItemDataRole.UserRole + 3,
        )
        self.video_model.appendRow(
            [col_name] + [QtGui.QStandardItem(items[c].text() if items[c] else "") for c in range(1, 5)]
        )
        self.trash_model.removeRow(row)
        self._set_qualifiable(video_path, "yes")

        # Régénérer la miniature pour cette ligne (stocker sur self pour éviter le GC)
        new_row = self.video_model.rowCount() - 1
        if video_path:
            if hasattr(self, '_thumb_worker') and self._thumb_worker and self._thumb_worker.isRunning():
                self._thumb_worker.requestInterruption()
                self._thumb_worker.wait(200)
            self._thumb_worker = ThumbnailWorkerMulti([('main', new_row, video_path)])
            self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._thumb_worker.start()
        self._rebuild_video_rows()

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
