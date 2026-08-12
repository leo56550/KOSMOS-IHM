import csv
import os
import json
import re
import cv2
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

from PyQt6 import QtWidgets, QtCore, QtGui

from services.weather_service import WeatherWorker
from services.thumbnail_service import THUMB_W, THUMB_H
from services.campaign_service import (
    get_video_json_path, _find_first_json_in_folder,
    get_video_gps_coords,
    get_working_video_dir, get_infostation_path,
    resolve_video_json_path, get_working_video_json_path,
)
from views.dialogs.weather_dialog import WeatherWebDialog

# En-tête campagne (champs identiques pour toutes les vidéos) : widget_id → (block, json_key)
_INFOSTATION_FIELD_BLOCKS: dict[str, tuple] = {
    "ft_nom_campagne": ("survey", "survey_name"),
    "ft_zone":         ("survey", "zone"),
    "ft_type":         ("survey", "type"),
    "ft_region":       ("survey", "region"),
    "ft_site":         ("survey", "site"),
    "ft_codestatut":   ("survey", "protectionStatus1"),
    "ft_codestatut2":  ("survey", "protectionStatus2"),
    "ft_date":         ("survey", "date"),
    "ft_bateau":       ("survey", "boat_name"),
    "ft_pilote":       ("survey", "pilot_name"),
    "ft_equipage":     ("survey", "crew_names"),
}

# Colonnes du tableau infostation (une ligne = une vidéo).
# Tuple : (label CSV, block, json_key, read_only)
# read_only=True → dérivé automatiquement, non éditable.
_FT_TABLE_COLS: list[tuple] = [
    ("Codestation",                    "video_observation", "codeObs",                   False),
    ("Latitude",                       "video_observation", "latitude",                   False),
    ("Longitude",                      "video_observation", "longitude",                  False),
    ("Heure",                          "video_observation", "time",                       False),
    ("Exploitable",                    "video_observation", "exploitable",                False),
    ("Nom du point",                   "video_observation", "point_name",                 False),
    ("Nom du point GPS",               "video_observation", "gps_waypoint",               False),
    ("Pt de Suivi",                    "video_observation", "monitoring_program",          False),
    ("Profondeur",                     "video_observation", "depth",                       False),
    ("Commentaires terrain pose",      "video_observation", "deployment_comment",          False),
    ("Commentaires terrain localisation", "video_observation", "location_comment",          False),
    ("Nom du fichier",                 None,                None,                          True),
    ("Timecode ardoise",               "video_observation", "timecode_ardoise",            False),
    ("Timecode début",                 "video_observation", "timecode_debut",              False),
    ("Commentaires video",             "video_observation", "derush_comment",              False),
    ("Images interessantes",           "video_observation", "interesting_images",          False),
    ("Capture écran",                  "video_observation", "screenshot",                  False),
    ("Milieu/Habitat",                 "video_observation", "habitat",                     False),
    ("Visibilite",                     "video_observation", "estimated_visibility",        False),
    ("Camera",                         "system",            "camera",                      False),
    ("Modèle MCU",                     "system",            "model_mcu",                   False),
    ("Version système",                "system",            "system_version",               False),
    ("Moteur",                         "video_observation", "moteur",                      False),
    ("Systeme",                        "system",            "type_system",                  False),
    ("Maree",                          "video_observation", "tide",                        False),
    ("Coefficient marée",              "video_observation", "coefficient",                 False),
    ("Lune",                           "video_observation", "moon",                        False),
    ("Meteo",                          "video_observation", "weather",                     False),
    ("Vent (beaufort)",                "video_observation", "wind",                        False),
    ("Direction vent",                 "video_observation", "wind_direction",              False),
    ("Mer (beaufort)",                 "video_observation", "seaState",                    False),
    ("Houle",                          "video_observation", "swell_height",                False),
    ("Direction houle",                "video_observation", "swell_direction",             False),
    ("Température air",                "video_observation", "airTemp",                     False),
    ("Température eau",                "video_observation", "water_temperature",           False),
    ("Dérusher",                       "video_observation", "derusher",                    False),
    ("Analyseur poisson",              "video_observation", "fish_annotator",              False),
    ("Analyseur habitat",              "video_observation", "habitat_annotator",           False),
    ("Distance analysable min (m)",     "video_observation", "distance_min",                False),
    ("Distance analysable max (m)",     "video_observation", "distance_max",                False),
    ("Commentaire qualification",      "video_observation", "commentaire_qualification",   False),
    ("Chemin vidéo",                   None,                None,                          True),
]
# Champs du template non présents dans les anciens JSONs → à initialiser à null si absents
_CUSTOM_VOB_FIELDS: list[str] = [
    "habitat", "timecode_ardoise", "timecode_debut",
    "location_comment", "moteur", "derush_comment", "interesting_images",
    "screenshot", "fish_annotator", "habitat_annotator",
    "distance_min", "distance_max",
    "time", "latitude", "longitude",
]

# Colonnes du CSV infostation (source unique de vérité — utilisée dans upsert ET génération complète)
_INFOSTATION_COLUMNS: list[str] = [
    "Codestation", "Zone", "Type", "Région", "Nom campagne",
    "Latitude", "Longitude", "Date", "Heure",
    "Exploitable", "Nom du point", "Nom du point GPS",
    "Codestatut", "Codestatut2", "Site", "Pt de Suivi", "Profondeur",
    "Commentaires terrain pose", "Commentaires terrain localisation",
    "Nom du fichier", "Timecode ardoise", "Timecode début",
    "Commentaires video", "Images interessantes", "Capture écran",
    "Milieu/Habitat", "Visibilite",
    "Camera", "Modèle MCU", "Version système", "Moteur", "Systeme",
    "Maree", "Coefficient marée", "Lune",
    "Meteo", "Vent (beaufort)", "Direction vent",
    "Mer (beaufort)", "Houle", "Direction houle",
    "Température air", "Température eau",
    "Bateau", "Pilote", "Equipage",
    "Dérusher", "Analyseur poisson", "Analyseur habitat",
    "Distance analysable min (m)", "Distance analysable max (m)",
    "Commentaire qualification", "Chemin vidéo",
]

_FIELD_STYLE = ("background-color: #162433; color: #F2BFB4; border: 1px solid #2a4057;"
                " border-radius: 3px; padding: 3px 6px; font-family: 'Segoe UI', sans-serif;")
_EMPTY_STYLE = ("background-color: #162433; color: #5a7a8a; border: 1px solid #1e3448;"
                " border-radius: 3px; padding: 3px 6px; font-family: 'Segoe UI', sans-serif;")
_LABEL_STYLE  = ("color: #b0c8d8; font-weight: bold; font-size: 11px; border: none;"
                 " min-width: 130px; font-family: 'Segoe UI', sans-serif;")
_SECTION_TITLE_STYLE = ("font-weight: bold; color: #F2BFB4; font-size: 13px; padding-bottom: 2px;"
                        " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;")
_SECTION_LINE_STYLE  = "border-bottom: 1px solid #2778A2; margin-bottom: 6px;"
_COMBO_STYLE  = ("QComboBox { background-color: #162433; color: #F2BFB4;"
                 " border: 1px solid #2a4057; border-radius: 3px; padding: 2px 6px;"
                 " font-family: 'Segoe UI', sans-serif; }"
                 " QComboBox::drop-down { border: none; }"
                 " QComboBox QAbstractItemView { background-color: #162433; color: #F2BFB4;"
                 " selection-background-color: #2778A2; }")
_TEXT_STYLE   = ("QPlainTextEdit { background-color: #162433; color: #F2BFB4;"
                 " border: 1px solid #2a4057; border-radius: 3px; padding: 3px 6px;"
                 " font-family: 'Segoe UI', sans-serif; }")


class MetadonneesController:
    """Contrôleur de la page Métadonnées : affichage et édition des JSON vidéo, météo et statistiques."""

    def __init__(self, widget: QtWidgets.QWidget, video_model: QtGui.QStandardItemModel,
                 trash_model: QtGui.QStandardItemModel, on_metadata_saved=None,
                 on_video_selected=None):
        """Connecte les modèles, crée les scroll areas et initialise la jauge statistique."""
        self.widget = widget
        self.video_model = video_model
        self.trash_model = trash_model
        self._on_metadata_saved = on_metadata_saved
        self._on_video_selected = on_video_selected
        self._json_data = {}
        self.current_template_json = None
        self.current_video_path = None
        self.current_language = 'en'

        self.weather_sea_keys = [
            "moon", "tide", "coefficient", "wind", "wind_direction",
            "airTemp", "seaState", "swell_height", "swell_direction",
            "water_temperature", "weather"
        ]

        self._infostation_widgets: dict[str, QtWidgets.QWidget] = {}
        self._ft_table_video_paths: list = []
        self._working_dir: str = ""

        # Debounce pour l'upsert infostation (2 s après la dernière modif)
        self._infostation_timer = QtCore.QTimer()
        self._infostation_timer.setSingleShot(True)
        self._infostation_timer.setInterval(2000)
        self._infostation_timer.timeout.connect(self._flush_infostation_upsert)
        self._infostation_pending_path: str = ""

        self.video_model.rowsInserted.connect(self.refresh_statistics)
        self.video_model.rowsRemoved.connect(self.refresh_statistics)
        self.trash_model.rowsInserted.connect(self.refresh_statistics)
        self.trash_model.rowsRemoved.connect(self.refresh_statistics)
        self.video_model.modelReset.connect(self.refresh_statistics)
        self.trash_model.modelReset.connect(self.refresh_statistics)

        self.tree_videos = self.widget.findChild(QtWidgets.QTreeView, "tree_videos")
        self.graph_trash_container = self.widget.findChild(QtWidgets.QFrame, "graph_trash_container")
        self.container_weather_data = self.widget.findChild(QtWidgets.QFrame, "container_meteo_data")
        self.data_system_container = self.widget.findChild(QtWidgets.QFrame, "data_system_container")
        self.specific_container_data = self.widget.findChild(QtWidgets.QFrame, "specific_container_data")

        # Remove the 1200px minimum that was causing the toolbar to go off-screen
        meteo_outer = self.widget.findChild(QtWidgets.QFrame, "container_weather_data")
        if meteo_outer:
            meteo_outer.setMinimumWidth(0)

        self._setup_ui()
        self._init_scroll_areas()
        self._init_infostation_panel()

        if self.tree_videos:
            self.tree_videos.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self._save_timer = QtCore.QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_metadata_to_json)

    # ── Setup ─────────────────────────────────────────────────────────────

    def _setup_ui(self):
        """Configure le mode de sélection de l'arbre vidéo."""
        if self.tree_videos:
            self.tree_videos.setModel(self.video_model)
            self.tree_videos.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.tree_videos.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.tree_videos.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))

    def _make_scroll_area(self, container: QtWidgets.QFrame) -> QtWidgets.QScrollArea | None:
        """Installe un QScrollArea dans le container et retourne-le."""
        if not container:
            return None
        # Remove any existing layout
        old = container.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            dummy = QtWidgets.QWidget()
            dummy.setLayout(old)

        outer = QtWidgets.QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }"
                             "QScrollBar:vertical { width: 6px; background: #1a1a1a; }"
                             "QScrollBar::handle:vertical { background: #2778a2; border-radius: 3px; }")

        placeholder = QtWidgets.QWidget()
        placeholder.setStyleSheet("background: transparent;")
        scroll.setWidget(placeholder)
        outer.addWidget(scroll)
        return scroll

    def _init_scroll_areas(self):
        """Crée un QScrollArea dans chaque container de données."""
        self._scroll_system = self._make_scroll_area(self.data_system_container)
        self._scroll_weather = self._make_scroll_area(self.container_weather_data)
        self._scroll_video = self._make_scroll_area(self.specific_container_data)

    def _init_infostation_panel(self):
        """Construit le panneau feuille terrain : en-tête campagne + tableau des points + commentaire."""
        if not self.graph_trash_container:
            return

        self.graph_trash_container.setMaximumHeight(16777215)
        self.graph_trash_container.setMinimumHeight(0)

        old = self.graph_trash_container.layout()
        if old:
            while old.count():
                child = old.takeAt(0)
                if child.widget():
                    child.widget().setParent(None)
            QtWidgets.QWidget().setLayout(old)

        outer = QtWidgets.QVBoxLayout(self.graph_trash_container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Barre titre : compteurs + bouton export ───────────────────────
        title_bar = QtWidgets.QWidget()
        title_bar.setStyleSheet("background-color: #111f2e; border-bottom: 1px solid #1e3448;")
        title_bar.setFixedHeight(32)
        tb_row = QtWidgets.QHBoxLayout(title_bar)
        tb_row.setContentsMargins(10, 0, 10, 0)
        tb_row.setSpacing(10)

        lbl_title = QtWidgets.QLabel("Infostation")
        lbl_title.setStyleSheet(_SECTION_TITLE_STYLE)
        tb_row.addWidget(lbl_title)

        self.lbl_video_count = QtWidgets.QLabel("—")
        self.lbl_video_count.setStyleSheet(
            "color: #2778A2; font-size: 10px; border: none; font-family: 'Segoe UI', sans-serif;")
        self.lbl_trash_count = QtWidgets.QLabel("—")
        self.lbl_trash_count.setStyleSheet(
            "color: #D94F38; font-size: 10px; border: none; font-family: 'Segoe UI', sans-serif;")
        tb_row.addWidget(self.lbl_video_count)
        tb_row.addWidget(self.lbl_trash_count)
        tb_row.addStretch()

        btn_gpx = QtWidgets.QPushButton("IMPORT GPX")
        btn_gpx.setStyleSheet(
            "QPushButton{background:#1a3a4a;color:#7ec8e3;border:1px solid #2778a2;"
            "border-radius:4px;padding:2px 10px;font-size:10px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2778a2;color:white;}"
        )
        btn_gpx.clicked.connect(self._import_gpx)
        tb_row.addWidget(btn_gpx)
        outer.addWidget(title_bar)

        # ── En-tête campagne ─────────────────────────────────────────────
        _lbl_h = ("color: #7ec8e3; font-size: 10px; font-weight: bold; border: none;"
                  " font-family: 'Segoe UI', sans-serif;")
        _inp_h = ("background-color: #162433; color: #F2BFB4; border: 1px solid #2a4057;"
                  " border-radius: 2px; padding: 1px 5px; font-size: 10px;"
                  " font-family: 'Segoe UI', sans-serif;")

        def _hl(text):
            l = QtWidgets.QLabel(text + " :")
            l.setStyleSheet(_lbl_h)
            l.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
            return l

        def _hi(fid, placeholder="", width=100):
            w = QtWidgets.QLineEdit()
            w.setPlaceholderText(placeholder)
            w.setStyleSheet(_inp_h)
            w.setFixedHeight(20)
            w.setMinimumWidth(width)
            w.textChanged.connect(lambda t, fi=fid: self._on_infostation_changed(fi, t, w))
            self._infostation_widgets[fid] = w
            return w

        campaign_panel = QtWidgets.QWidget()
        campaign_panel.setStyleSheet("background-color: #0d1620; border-bottom: 1px solid #1e3448;")
        cp = QtWidgets.QVBoxLayout(campaign_panel)
        cp.setContentsMargins(10, 5, 10, 5)
        cp.setSpacing(4)

        # Ligne 1 : Nom campagne | Zone | Type | Région
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(_hl("Nom campagne"))
        row1.addWidget(_hi("ft_nom_campagne", "ATL_2026", 100))
        row1.addSpacing(8)
        row1.addWidget(_hl("Zone"))
        row1.addWidget(_hi("ft_zone", "ATL", 50))
        row1.addSpacing(8)
        row1.addWidget(_hl("Type"))
        row1.addWidget(_hi("ft_type", "KOSMOS", 60))
        row1.addSpacing(8)
        row1.addWidget(_hl("Région"))
        row1.addWidget(_hi("ft_region", "Bretagne", 80))
        row1.addStretch()
        cp.addLayout(row1)

        # Ligne 2 : Site | Codestatut | Codestatut2 | Date
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(_hl("Site"))
        row2.addWidget(_hi("ft_site", "Gléhan", 100))
        row2.addSpacing(8)
        row2.addWidget(_hl("Codestatut"))
        row2.addWidget(_hi("ft_codestatut", "", 60))
        row2.addSpacing(8)
        row2.addWidget(_hl("Codestatut2"))
        row2.addWidget(_hi("ft_codestatut2", "", 60))
        row2.addSpacing(8)
        row2.addWidget(_hl("Date"))
        row2.addWidget(_hi("ft_date", "09/07/2026", 80))
        row2.addStretch()
        cp.addLayout(row2)

        # Ligne 3 : Bateau | Pilote | Équipage
        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(6)
        row3.addWidget(_hl("Bateau"))
        row3.addWidget(_hi("ft_bateau", "Siliou", 80))
        row3.addSpacing(8)
        row3.addWidget(_hl("Pilote"))
        row3.addWidget(_hi("ft_pilote", "O.A", 70))
        row3.addSpacing(8)
        row3.addWidget(_hl("Équipage"))
        row3.addWidget(_hi("ft_equipage", "O.F – OA – CH", 130))
        row3.addStretch()

        btn_apply_all = QtWidgets.QPushButton(
            self.translate("Appliquer à toutes les vidéos", "Apply to all videos"))
        btn_apply_all.setStyleSheet(
            "QPushButton{background:#20415d;color:#F2BFB4;border:1px solid #2778a2;"
            "border-radius:4px;padding:2px 10px;font-size:10px;font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2778a2;}"
        )
        btn_apply_all.clicked.connect(self._apply_survey_to_all)
        row3.addWidget(btn_apply_all)
        cp.addLayout(row3)

        outer.addWidget(campaign_panel)

        # ── Tableau infostation (une ligne = une vidéo) ───────────────────
        self._ft_table = QtWidgets.QTableWidget()
        self._ft_table.setColumnCount(len(_FT_TABLE_COLS))
        self._ft_table.setHorizontalHeaderLabels([c[0] for c in _FT_TABLE_COLS])
        self._ft_table.horizontalHeader().setStretchLastSection(False)
        self._ft_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)
        self._ft_table.horizontalHeader().setMinimumSectionSize(40)
        self._ft_table.verticalHeader().setDefaultSectionSize(22)
        self._ft_table.verticalHeader().hide()
        self._ft_table.setAlternatingRowColors(True)
        self._ft_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._ft_table.setSortingEnabled(True)
        self._ft_table.setStyleSheet("""
            QTableWidget {
                background-color: #111820; alternate-background-color: #0d1620;
                color: #F2BFB4; border: none; gridline-color: #1a2e40;
                font-size: 10px; font-family: 'Segoe UI', sans-serif;
            }
            QHeaderView::section {
                background-color: #162433; color: #7ec8e3; font-weight: bold;
                border: 1px solid #1e3448; padding: 3px 4px; font-size: 10px;
            }
            QTableWidget::item { padding: 1px 4px; }
            QTableWidget::item:selected { background-color: #20415d; color: white; }
            QTableWidget::item:alternate { background-color: #0d1620; }
        """)
        # Largeurs par défaut selon le type de colonne
        _default_widths = {
            "Codestation": 80, "Latitude": 90, "Longitude": 90, "Heure": 52,
            "Exploitable": 70, "Nom du point": 70, "Nom du point GPS": 70,
            "Pt de Suivi": 70, "Profondeur": 65,
            "Commentaires terrain pose": 150, "Commentaires terrain localisation": 150,
            "Nom du fichier": 140, "Timecode ardoise": 85, "Timecode début": 85,
            "Commentaires video": 150, "Images interessantes": 130, "Capture écran": 80,
            "Milieu/Habitat": 90, "Visibilite": 65,
            "Camera": 80, "Modèle MCU": 75, "Version système": 90,
            "Moteur": 55, "Systeme": 70,
            "Maree": 55, "Coefficient marée": 90, "Lune": 50,
            "Meteo": 80, "Vent (beaufort)": 85, "Direction vent": 90,
            "Mer (beaufort)": 85, "Houle": 55, "Direction houle": 90,
            "Température air": 95, "Température eau": 95,
            "Dérusher": 70, "Analyseur poisson": 100, "Analyseur habitat": 100,
            "Distance analysable min (m)": 110, "Distance analysable max (m)": 110,
            "Commentaire qualification": 140, "Chemin vidéo": 200,
        }
        for col_i, (col_label, *_) in enumerate(_FT_TABLE_COLS):
            self._ft_table.setColumnWidth(col_i, _default_widths.get(col_label, 80))

        self._ft_table.cellChanged.connect(self._on_ft_table_cell_changed)
        self._ft_table.cellClicked.connect(self._on_ft_table_row_clicked)
        outer.addWidget(self._ft_table, stretch=1)

        self.refresh_statistics()

    # ── Tableau feuille terrain ───────────────────────────────────────────

    def _rebuild_ft_table(self):
        """Reconstruit le tableau infostation depuis les JSONs de toutes les vidéos."""
        if not hasattr(self, '_ft_table') or self._ft_table is None:
            return
        self._ft_table.setSortingEnabled(False)
        self._ft_table.blockSignals(True)
        self._ft_table.setRowCount(0)

        _ro_flags = (QtCore.Qt.ItemFlag.ItemIsSelectable |
                     QtCore.Qt.ItemFlag.ItemIsEnabled)
        _rw_flags = _ro_flags | QtCore.Qt.ItemFlag.ItemIsEditable

        for model_row in range(self.video_model.rowCount()):
            item = self.video_model.item(model_row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            video_path = str(video_path)

            # Utilise _build_infostation_row pour récupérer toutes les valeurs
            # (gère les champs dérivés : timecodes, GPS fallback, etc.)
            row_data = self._build_infostation_row(video_path)

            trow = self._ft_table.rowCount()
            self._ft_table.insertRow(trow)

            for col_i, (col_label, block_name, json_key, read_only) in enumerate(_FT_TABLE_COLS):
                val = str(row_data.get(col_label, "") or "")
                cell = QtWidgets.QTableWidgetItem(val)
                cell.setTextAlignment(
                    QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft)
                cell.setFlags(_ro_flags if read_only else _rw_flags)
                if read_only:
                    cell.setForeground(QtGui.QBrush(QtGui.QColor("#5a7a8a")))
                # Stocke le video_path dans la colonne 0
                if col_i == 0:
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole, video_path)
                self._ft_table.setItem(trow, col_i, cell)

        self._ft_table.blockSignals(False)
        self._ft_table.setSortingEnabled(True)

    def _on_ft_table_cell_changed(self, row: int, col: int):
        """Sauvegarde la valeur éditée dans le JSON de la vidéo correspondante."""
        first_item = self._ft_table.item(row, 0)
        if first_item is None:
            return
        video_path = first_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return

        _col_label, block_name, json_key, read_only = _FT_TABLE_COLS[col]
        if read_only or block_name is None or json_key is None:
            return

        cell = self._ft_table.item(row, col)
        new_value = cell.text().strip() if cell else ""

        json_path = resolve_video_json_path(self._working_dir, video_path)
        if not os.path.isfile(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                jdata = json.load(f)
            block = jdata.setdefault(block_name, {})
            if json_key in block and isinstance(block[json_key], dict):
                block[json_key]["value"] = new_value or None
            else:
                block[json_key] = {"value": new_value or None}
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(jdata, f, indent=4, ensure_ascii=False)
            self._schedule_infostation_upsert(video_path)
            if self._on_metadata_saved:
                self._on_metadata_saved()
        except Exception as e:
            print(f"[INFOSTATION TABLE] Error saving {block_name}.{json_key}: {e}")

    def _on_ft_table_row_clicked(self, row: int, _col: int):
        """Charge les données de la vidéo cliquée dans les panneaux de droite."""
        first_item = self._ft_table.item(row, 0)
        if first_item is None:
            return
        video_path = first_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return
        json_path = resolve_video_json_path(self._working_dir, str(video_path))
        if os.path.isfile(json_path):
            self.current_video_path = str(video_path)
            self.load_all_data(json_path)
            self._load_infostation_fields(str(video_path))

    # ── Public interface ─────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Change la langue et recharge l'affichage des données si un JSON est actif."""
        self.current_language = language
        self.refresh_statistics()
        if self.current_template_json and os.path.exists(self.current_template_json):
            self.load_all_data(self.current_template_json)

    def load_campaign_videos(self, model: QtGui.QStandardItemModel):
        """Remplace le modèle vidéo et reconnecte le signal de sélection au nouveau selectionModel."""
        self.video_model = model
        if self.tree_videos:
            # Déconnecter l'ANCIEN selectionModel avant setModel() pour éviter les connexions multiples
            old_sel = self.tree_videos.selectionModel()
            if old_sel is not None:
                try:
                    old_sel.selectionChanged.disconnect(self.on_selection_changed)
                except RuntimeError:
                    pass
            self.tree_videos.setModel(self.video_model)
            # setModel() crée un nouveau selectionModel — on se connecte à celui-ci
            self.tree_videos.selectionModel().selectionChanged.connect(self.on_selection_changed)

    def select_video_by_name(self, video_name: str):
        """Sélectionne une vidéo dans l'arbre depuis son nom (appel depuis la carte)."""
        if not self.tree_videos or not self.video_model:
            return
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and item.text() == video_name:
                index = self.video_model.indexFromItem(item)
                self.tree_videos.selectionModel().setCurrentIndex(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect |
                    QtCore.QItemSelectionModel.SelectionFlag.Rows
                )
                self.tree_videos.scrollTo(index)
                # selectionChanged se déclenche automatiquement → on_selection_changed chargera les données
                break

    def on_selection_changed(self, selected, deselected):
        """Charge le JSON de la vidéo sélectionnée et rafraîchit tous les panneaux de données."""
        # Sauvegarder immédiatement les modifications en cours avant de changer de vidéo
        if self._save_timer.isActive():
            self._save_timer.stop()
            self.save_metadata_to_json()

        indexes = selected.indexes()
        if not indexes:
            return
        col0_index = indexes[0].sibling(indexes[0].row(), 0)
        item = self.video_model.itemFromIndex(col0_index)
        if not item:
            return
        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return
        self.current_video_path = str(video_path)
        video_name = item.text()
        json_path = resolve_video_json_path(self._working_dir, self.current_video_path)
        if os.path.exists(json_path):
            self.load_all_data(json_path)
        self._load_infostation_fields(self.current_video_path)
        if self._on_video_selected:
            self._on_video_selected(video_name, self.current_video_path)

    def load_global_campaign_metadata(self, campaign_folder: str):
        """Charge les sections système et campagne depuis le premier JSON trouvé dans campaign_folder."""
        from services.campaign_service import get_campaign_json_data
        if get_campaign_json_data(campaign_folder, extract_system=False):
            for root, _, _files in os.walk(campaign_folder):
                if "trash" in root.split(os.sep):
                    continue
                first_json = _find_first_json_in_folder(root)
                if first_json:
                    self._load_common_data(first_json)
                    break

    def _load_common_data(self, json_path=None):
        """Affiche les blocs system et survey d'un JSON dans leurs scroll areas respectives."""
        if not json_path or not os.path.isfile(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ERROR] Unable to load common data: {e}")
            return

        if "system" in data:
            self._display_block_in_scroll("system", data["system"], self._scroll_system, self.translate("Système", "System"))

    def load_all_data(self, json_path: str):
        """Lit json_path et peuple tous les panneaux (système, campagne, vidéo, météo)."""
        if not os.path.isfile(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self._json_data = json.load(f)
                self.current_template_json = json_path
        except Exception as e:
            print(f"[ERROR] Unable to read JSON file: {e}")
            return

        if "system" in self._json_data:
            self._display_block_in_scroll("system", self._json_data["system"],
                                          self._scroll_system, self.translate("Système", "System"))
        if "video_observation" in self._json_data:
            self._ensure_custom_fields()
            obs = self._json_data["video_observation"]
            weather = {k: v for k, v in obs.items() if k in self.weather_sea_keys}
            # Champs gérés dans la feuille terrain ou dans la page Événements → masqués ici
            _feuille_terrain_keys = {
                "depth", "point_name", "gps_waypoint", "deployment_comment",
                "fish_annotator", "habitat_annotator",
                "distance_min", "distance_max",
                "timecode_ardoise", "timecode_debut",
                "derush_comment", "interesting_images",
                "moteur", "screenshot",
                "latitude", "longitude", "time",
            }
            specific = {k: v for k, v in obs.items()
                        if k not in self.weather_sea_keys and k not in _feuille_terrain_keys}
            self._display_block_in_scroll("video_observation", specific,
                                          self._scroll_video, self.translate("Vidéo", "Video"),
                                          extra_btn=(self.translate("Comparer avec l'ardoise", "Compare with slate"), self.on_compare_slate_clicked))
            self._display_weather_in_scroll(weather)

    # ── Rendering helpers ─────────────────────────────────────────────────

    def _build_form_widget(self, block_key: str, block_data: dict, title: str,
                           extra_btn: tuple | None = None) -> QtWidgets.QWidget:
        """Construit et retourne un widget formulaire pour un bloc de données."""
        root = QtWidgets.QWidget()
        root.setStyleSheet("background: transparent;")
        vbox = QtWidgets.QVBoxLayout(root)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # Section header
        hdr = QtWidgets.QWidget()
        hdr.setStyleSheet(_SECTION_LINE_STYLE)
        hdr_row = QtWidgets.QHBoxLayout(hdr)
        hdr_row.setContentsMargins(0, 0, 0, 4)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setStyleSheet(_SECTION_TITLE_STYLE)
        hdr_row.addWidget(title_lbl)
        if extra_btn:
            btn = QtWidgets.QPushButton(extra_btn[0])
            btn.setStyleSheet("""
                QPushButton { background-color: #20415d; color: #F2BFB4; border: 1px solid #2778a2;
                              border-radius: 4px; padding: 3px 8px; font-size: 11px; }
                QPushButton:hover { background-color: #2778a2; }
            """)
            btn.clicked.connect(extra_btn[1])
            hdr_row.addStretch()
            hdr_row.addWidget(btn)
        vbox.addWidget(hdr)

        if not isinstance(block_data, dict):
            vbox.addStretch()
            return root

        lang = self.current_language
        for field_id, structure in block_data.items():
            if not isinstance(structure, dict) or "name" not in structure:
                continue

            val = structure.get("value", "")
            example = structure.get("example", "")
            auth_values = structure.get(f"authorized_values_{lang}")
            label_text = structure.get(f"name_{lang}", structure.get("name", field_id))
            tooltip = structure.get("description_fr", "")

            row = QtWidgets.QWidget()
            row.setStyleSheet("background: transparent;")
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            row_layout.setSpacing(8)

            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet(_LABEL_STYLE)
            lbl.setWordWrap(False)
            if tooltip:
                lbl.setToolTip(tooltip)
            row_layout.addWidget(lbl, 1)

            if auth_values:
                combo = QtWidgets.QComboBox()
                combo.setStyleSheet(_COMBO_STYLE)
                combo.addItems([str(v) for v in auth_values])
                if val:
                    idx = combo.findText(str(val))
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                combo.currentTextChanged.connect(
                    lambda t, b=block_key, f=field_id: self._update_value(b, f, t))
                row_layout.addWidget(combo, 2)
            else:
                line = QtWidgets.QLineEdit()
                line.setText(str(val) if val else "")
                line.setPlaceholderText(str(example))
                line.setStyleSheet(_FIELD_STYLE if val else _EMPTY_STYLE)
                line.textChanged.connect(
                    lambda t, b=block_key, f=field_id, w=line: self._update_value(b, f, t, w))
                row_layout.addWidget(line, 2)

            vbox.addWidget(row)

        vbox.addStretch()
        return root

    def _display_block_in_scroll(self, block_key: str, block_data: dict,
                                  scroll: QtWidgets.QScrollArea | None, title: str,
                                  extra_btn: tuple | None = None):
        """Remplace le widget du QScrollArea par un formulaire reconstruit."""
        if not scroll:
            return
        form = self._build_form_widget(block_key, block_data, title, extra_btn)
        scroll.setWidget(form)

    def _display_weather_in_scroll(self, weather_sea_dict: dict):
        """Construit le panneau météo/mer avec bouton de comparaison web et l'insère dans _scroll_weather."""
        if not self._scroll_weather:
            return

        root = QtWidgets.QWidget()
        root.setStyleSheet("background: transparent;")
        vbox = QtWidgets.QVBoxLayout(root)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        hdr = QtWidgets.QWidget()
        hdr.setStyleSheet(_SECTION_LINE_STYLE)
        hdr_row = QtWidgets.QHBoxLayout(hdr)
        hdr_row.setContentsMargins(0, 0, 0, 4)
        title_lbl = QtWidgets.QLabel(self.translate("Météo & Mer", "Weather & Sea"))
        title_lbl.setStyleSheet(_SECTION_TITLE_STYLE)
        hdr_row.addWidget(title_lbl)
        btn_web = QtWidgets.QPushButton(self.translate("Comparer données web", "Compare web data"))
        btn_web.setStyleSheet("""
            QPushButton { background-color: #20415d; color: #F2BFB4; border: 1px solid #2778a2;
                          border-radius: 4px; padding: 3px 8px; font-size: 11px; }
            QPushButton:hover { background-color: #2778a2; }
        """)
        btn_web.clicked.connect(self.action_compare_weather_web)
        hdr_row.addStretch()
        hdr_row.addWidget(btn_web)
        vbox.addWidget(hdr)

        if isinstance(weather_sea_dict, dict):
            lang = self.current_language
            for field_id, structure in weather_sea_dict.items():
                if not isinstance(structure, dict) or "name" not in structure:
                    continue
                val = structure.get("value", "")
                example = structure.get("example", "")
                auth_values = structure.get(f"authorized_values_{lang}")
                label_text = structure.get(f"name_{lang}", structure.get("name", field_id))

                row = QtWidgets.QWidget()
                row.setStyleSheet("background: transparent;")
                row_layout = QtWidgets.QHBoxLayout(row)
                row_layout.setContentsMargins(2, 1, 2, 1)
                row_layout.setSpacing(8)

                lbl = QtWidgets.QLabel(label_text)
                lbl.setStyleSheet(_LABEL_STYLE)
                row_layout.addWidget(lbl, 1)

                if auth_values:
                    combo = QtWidgets.QComboBox()
                    combo.setStyleSheet("""
                        QComboBox { background-color: #162433; color: #F2BFB4;
                                    border: 1px solid #444; border-radius: 3px; padding: 2px 6px; }
                        QComboBox QAbstractItemView { background-color: #162433; color: white; }
                    """)
                    combo.addItems([str(v) for v in auth_values])
                    if val:
                        idx = combo.findText(str(val))
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                    combo.currentTextChanged.connect(
                        lambda t, f=field_id: self._update_value("video_observation", f, t))
                    row_layout.addWidget(combo, 2)
                else:
                    line = QtWidgets.QLineEdit()
                    line.setText(str(val) if val else "")
                    line.setPlaceholderText(str(example))
                    line.setStyleSheet(_FIELD_STYLE if val else _EMPTY_STYLE)
                    line.textChanged.connect(
                        lambda t, f=field_id, w=line: self._update_value("video_observation", f, t, w))
                    row_layout.addWidget(line, 2)

                vbox.addWidget(row)

        vbox.addStretch()
        self._scroll_weather.setWidget(root)

    # ── Statistics chart ──────────────────────────────────────────────────

    def refresh_statistics(self):
        """Met à jour les compteurs vidéo/poubelle et reconstruit le tableau feuille terrain."""
        if not hasattr(self, 'lbl_video_count'):
            return
        v = self.video_model.rowCount()
        t = self.trash_model.rowCount()
        self.lbl_video_count.setText(self.translate(f"● {v} vidéo(s)", f"● {v} video(s)"))
        self.lbl_trash_count.setText(self.translate(f"● {t} poubelle", f"● {t} trash"))
        self._rebuild_ft_table()

    # ── Infostation — persisté dans video_observation du JSON ────────────

    def _ensure_custom_fields(self):
        """Initialise les champs custom manquants dans _json_data['video_observation']."""
        vob = self._json_data.setdefault("video_observation", {})
        for key in _CUSTOM_VOB_FIELDS:
            if key not in vob:
                vob[key] = {"value": None}

    def _on_infostation_changed(self, field_id: str, value: str,
                                 widget: QtWidgets.QWidget | None = None):
        """Propage la valeur de l'en-tête campagne à tous les JSON vidéo du dossier de travail."""
        if not self._working_dir:
            return
        mapping = _INFOSTATION_FIELD_BLOCKS.get(field_id)
        if not mapping:
            return
        block_name, json_key = mapping
        if widget and isinstance(widget, QtWidgets.QLineEdit):
            widget.setStyleSheet(_FIELD_STYLE if value else _EMPTY_STYLE)
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            json_path = get_working_video_json_path(self._working_dir, str(video_path))
            if not os.path.isfile(json_path):
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                block = data.setdefault(block_name, {})
                if json_key in block and isinstance(block[json_key], dict):
                    block[json_key]["value"] = value or None
                else:
                    block[json_key] = {"value": value or None}
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[INFOSTATION HEADER] {field_id}: {e}")
        self._schedule_infostation_upsert("")
        if self._on_metadata_saved:
            self._on_metadata_saved()

    def _auto_derive_from_json(self):
        """Dérive timecode_ardoise, timecode_début et interesting_images depuis les événements JSON.

        Ne touche aux champs que s'ils sont vides dans _json_data (respecte les saisies manuelles).
        """
        obs = self._json_data.get("video_observation", {})

        def _tc_str(ev):
            return ev.get("time_code_start") or ""

        # ── Timecode ardoise ─────────────────────────────────────────────
        if not self._v(obs, "timecode_ardoise"):
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower()
                       for kw in ["ardoise", "slate", "tableau blanc", "whiteboard"]):
                    self._json_data["video_observation"]["timecode_ardoise"]["value"] = _tc_str(ev)
                    break

        # ── Timecode début (atterrissage) ────────────────────────────────
        if not self._v(obs, "timecode_debut"):
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower()
                       for kw in ["atterrissage", "landing"]):
                    self._json_data["video_observation"]["timecode_debut"]["value"] = _tc_str(ev)
                    break

        # ── Images intéressantes ─────────────────────────────────────────
        if not self._v(obs, "interesting_images"):
            parts = []
            for ev in (obs.get("events_interesting_images", [{}]) or [{}])[0].get("values", []):
                tc      = ev.get("time_code_start") or ""
                detail  = ev.get("comment") or ev.get("value") or ""
                parts.append(f"{tc} {detail}".strip())
            if parts:
                self._json_data["video_observation"]["interesting_images"]["value"] = " ; ".join(parts)

    def _load_infostation_fields(self, video_path: str):
        """Peuple les champs d'en-tête de la feuille terrain depuis _json_data."""
        self._ensure_custom_fields()
        self._auto_derive_from_json()

        for form_id, (block_name, json_key) in _INFOSTATION_FIELD_BLOCKS.items():
            widget = self._infostation_widgets.get(form_id)
            if widget is None:
                continue
            block = self._json_data.get(block_name, {})
            entry = block.get(json_key, {})
            val = entry.get("value", "") if isinstance(entry, dict) else (entry or "")
            val = str(val) if val is not None else ""

            widget.blockSignals(True)
            if isinstance(widget, QtWidgets.QComboBox):
                idx = widget.findText(val)
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            elif isinstance(widget, QtWidgets.QPlainTextEdit):
                widget.setPlainText(val)
            else:
                widget.setText(val)
                if not widget.isReadOnly():
                    widget.setStyleSheet(_FIELD_STYLE if val else _EMPTY_STYLE)
            widget.blockSignals(False)

    def refresh_feuille_terrain(self):
        """Ré-dérive les champs auto depuis le JSON, recharge l'en-tête et reconstruit le tableau.

        Appelé par app_controller quand des événements changent sur la vidéo courante.
        """
        if self.current_video_path:
            self._load_infostation_fields(self.current_video_path)
        self._rebuild_ft_table()

    def set_working_dir(self, path: str):
        """Définit le répertoire de travail IHM (choisi à l'accueil)."""
        self._working_dir = path

    # ── Infostation upsert (auto, debounced) ─────────────────────────────

    def _schedule_infostation_upsert(self, video_path: str):
        """Planifie un upsert infostation 2 s après la dernière modification."""
        if not self._working_dir:
            return
        self._infostation_pending_path = video_path
        self._infostation_timer.start()

    def _flush_infostation_upsert(self):
        """Effectue l'upsert différé de la ligne infostation pour la vidéo en attente."""
        if self._infostation_pending_path and self._working_dir:
            self._upsert_infostation_row(self._infostation_pending_path)

    def _upsert_infostation_row(self, video_path: str):
        """Met à jour (ou insère) la ligne de video_path dans le CSV infostation global."""
        csv_path = get_infostation_path(self._working_dir)
        columns = _INFOSTATION_COLUMNS
        try:
            new_row = self._build_infostation_row(video_path)
            new_row = {k: str(v).replace('\n', ' | ').replace('\r', '')
                       for k, v in new_row.items()}
            stem = os.path.splitext(os.path.basename(video_path))[0]

            # Lire les lignes existantes
            existing_rows = []
            if os.path.isfile(csv_path):
                with open(csv_path, 'r', newline='', encoding='cp1252', errors='replace') as f:
                    reader = csv.DictReader(f, delimiter=';')
                    existing_rows = list(reader)

            # Upsert : remplacer la ligne si même "Nom du fichier", sinon append
            updated = False
            for i, row in enumerate(existing_rows):
                if row.get("Nom du fichier", "") == stem:
                    existing_rows[i] = new_row
                    updated = True
                    break
            if not updated:
                existing_rows.append(new_row)

            os.makedirs(self._working_dir, exist_ok=True)
            with open(csv_path, 'w', newline='', encoding='cp1252', errors='replace') as f:
                writer = csv.DictWriter(f, fieldnames=columns, delimiter=';',
                                        extrasaction='ignore', quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                writer.writerows(existing_rows)
        except PermissionError:
            print("[Infostation] Impossible d'écrire le CSV : fichier ouvert par un autre programme (ex: Excel). Fermez-le puis relancez une sauvegarde.")
        except Exception as e:
            print(f"[Infostation] Erreur upsert : {e}")

    # ── Infostation CSV generation ────────────────────────────────────────

    @staticmethod
    def _v(block: dict, key: str) -> str:
        """Extrait la valeur d'un champ JSON (structure {value: ...}) ou renvoie ''."""
        entry = block.get(key, {})
        val = entry.get("value") if isinstance(entry, dict) else entry
        return str(val) if val is not None else ""

    @staticmethod
    def _fmt_date(yyyymmdd: str) -> str:
        """Convertit '20190819' → '19/08/2019'."""
        if len(yyyymmdd) == 8 and yyyymmdd.isdigit():
            return f"{yyyymmdd[6:8]}/{yyyymmdd[4:6]}/{yyyymmdd[0:4]}"
        return yyyymmdd

    @staticmethod
    def _extract_stem_parts(stem: str):
        """Extrait (codestation, heure_hhmm) depuis un stem de fichier vidéo.

        Formats reconnus :
          20190819140122_ATL_CC190001  → ('CC190001', '14:01')
          CC190001                     → ('CC190001', '')
        """
        m = re.match(r'^(\d{8})(\d{6})_[^_]+_(.+)$', stem)
        if m:
            time_raw = m.group(2)
            heure = f"{time_raw[0:2]}:{time_raw[2:4]}"
            return m.group(3), heure
        return stem, ""

    def _build_infostation_row(self, video_path: str) -> dict:
        """Construit un dictionnaire de valeurs pour une ligne Infostation depuis le JSON."""
        stem = os.path.splitext(os.path.basename(video_path))[0]
        codestat, heure_stem = self._extract_stem_parts(stem)

        json_path = resolve_video_json_path(self._working_dir, video_path)
        jdata = {}
        if os.path.isfile(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    jdata = json.load(f)
            except Exception:
                pass
        sys_ = jdata.get("system", {})
        surv = jdata.get("survey", {})
        obs  = jdata.get("video_observation", {})

        # Lat/lon : JSON en priorité, fallback fichier GPS
        gps = get_video_gps_coords(video_path)
        lat_gps = str(gps[0]).replace('.', ',') if gps else ""
        lon_gps = str(gps[1]).replace('.', ',') if gps else ""
        lat_json = self._v(obs, "latitude")
        lon_json = self._v(obs, "longitude")
        lat = lat_json.replace('.', ',') if lat_json else lat_gps
        lon = lon_json.replace('.', ',') if lon_json else lon_gps

        # codeObs : JSON en priorité, fallback stem du fichier
        code_obs   = self._v(obs, "codeObs") or codestat
        # point_name : JSON en priorité, fallback stem du fichier
        point_name = self._v(obs, "point_name") or codestat
        # heure : JSON en priorité, fallback extraite du stem
        heure      = self._v(obs, "time") or heure_stem

        def _derive_tc_ardoise():
            v = self._v(obs, "timecode_ardoise")
            if v: return v
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower()
                       for kw in ["ardoise", "slate", "tableau blanc", "whiteboard"]):
                    return ev.get("time_code_start") or ""
            return ""

        def _derive_tc_debut():
            v = self._v(obs, "timecode_debut")
            if v: return v
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower()
                       for kw in ["atterrissage", "landing"]):
                    return ev.get("time_code_start") or ""
            return ""

        def _derive_interesting_images():
            v = self._v(obs, "interesting_images")
            if v: return v
            parts = []
            for ev in (obs.get("events_interesting_images", [{}]) or [{}])[0].get("values", []):
                tc     = ev.get("time_code_start") or ""
                detail = ev.get("comment") or ev.get("value") or ""
                parts.append(f"{tc} {detail}".strip())
            return " ; ".join(parts)

        return {
            "Codestation":                       code_obs,
            "Zone":                              self._v(surv, "zone"),
            "Type":                              self._v(surv, "type"),
            "Région":                            self._v(surv, "region"),
            "Nom campagne":                      self._v(surv, "survey_name"),
            "Latitude":                          lat,
            "Longitude":                         lon,
            "Date":                              self._fmt_date(self._v(surv, "date")),
            "Heure":                             heure,
            "Exploitable":                       self._v(obs, "exploitable"),
            "Nom du point":                      point_name,
            "Nom du point GPS":                  self._v(obs, "gps_waypoint"),
            "Codestatut":                        self._v(surv, "protectionStatus1"),
            "Codestatut2":                       self._v(surv, "protectionStatus2"),
            "Site":                              self._v(surv, "site"),
            "Pt de Suivi":                       self._v(obs, "monitoring_program"),
            "Profondeur":                        self._v(obs, "depth"),
            "Commentaires terrain pose":         self._v(obs, "deployment_comment"),
            "Commentaires terrain localisation": self._v(obs, "location_comment"),
            "Nom du fichier":                    stem,
            "Timecode ardoise":                  _derive_tc_ardoise(),
            "Timecode début":                    _derive_tc_debut(),
            "Commentaires video":                self._v(obs, "derush_comment"),
            "Images interessantes":              _derive_interesting_images(),
            "Capture écran":                     self._v(obs, "screenshot"),
            "Milieu/Habitat":                    self._v(obs, "habitat"),
            "Visibilite":                        self._v(obs, "estimated_visibility"),
            "Camera":                            self._v(sys_, "camera"),
            "Modèle MCU":                        self._v(sys_, "model_mcu"),
            "Version système":                   self._v(sys_, "system_version"),
            "Moteur":                            self._v(obs, "moteur"),
            "Systeme":                           self._v(sys_, "type_system"),
            "Maree":                             self._v(obs, "tide"),
            "Coefficient marée":                 self._v(obs, "coefficient"),
            "Lune":                              self._v(obs, "moon"),
            "Meteo":                             self._v(obs, "weather"),
            "Vent (beaufort)":                   self._v(obs, "wind"),
            "Direction vent":                    self._v(obs, "wind_direction"),
            "Mer (beaufort)":                    self._v(obs, "seaState"),
            "Houle":                             self._v(obs, "swell_height"),
            "Direction houle":                   self._v(obs, "swell_direction"),
            "Température air":                   self._v(obs, "airTemp"),
            "Température eau":                   self._v(obs, "water_temperature"),
            "Bateau":                            self._v(surv, "boat_name"),
            "Pilote":                            self._v(surv, "pilot_name"),
            "Equipage":                          self._v(surv, "crew_names"),
            "Dérusher":                          self._v(obs, "derusher"),
            "Analyseur poisson":                 self._v(obs, "fish_annotator"),
            "Analyseur habitat":                 self._v(obs, "habitat_annotator"),
            "Distance analysable min (m)":       self._v(obs, "distance_min"),
            "Distance analysable max (m)":       self._v(obs, "distance_max"),
            "Commentaire qualification":          self._v(obs, "commentaire_qualification"),
            "Chemin vidéo":                      video_path,
        }

    # ── Feature : vérification cohérence ────────────────────────────────

    def _run_consistency_check(self, video_paths: list[str]) -> list[tuple]:
        """Scanne tous les champs de chaque JSON et retourne (nom_vidéo, [labels manquants])."""
        issues = []
        lang = self.current_language
        for vp in video_paths:
            json_path = resolve_video_json_path(self._working_dir, vp)
            name = os.path.basename(vp)
            if not os.path.exists(json_path):
                issues.append((name, ["JSON absent"]))
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                issues.append((name, ["JSON illisible"]))
                continue

            missing = []
            for block in data.values():
                if not isinstance(block, dict):
                    continue
                for field_key, field_def in block.items():
                    if not isinstance(field_def, dict) or "value" not in field_def:
                        continue  # liste d'événements ou entrée non-champ
                    val = field_def.get("value")
                    if val is None or str(val).strip() in ("", "None", "null"):
                        label = field_def.get(f"name_{lang}") or field_def.get("name") or field_key
                        missing.append(label)

            if missing:
                issues.append((name, missing))
        return issues

    def _show_consistency_dialog(self, issues: list[tuple]):
        """Affiche tous les champs manquants par vidéo dans un arbre expandable. Export bloqué."""
        dlg = QtWidgets.QDialog(self.widget)
        dlg.setWindowTitle(self.translate(
            "Métadonnées incomplètes — export bloqué",
            "Incomplete metadata — export blocked"
        ))
        dlg.setWindowFlags(dlg.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        dlg.setMinimumSize(640, 500)
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        total_fields = sum(len(probs) for _, probs in issues)
        banner = QtWidgets.QLabel(self.translate(
            f"⛔  {len(issues)} vidéo(s) incomplète(s) — {total_fields} champ(s) manquant(s).\n"
            "Complétez les champs manquants dans la page Métadonnées puis relancez l'export.",
            f"⛔  {len(issues)} incomplete video(s) — {total_fields} missing field(s).\n"
            "Fill the missing fields in the Metadata page then retry the export."
        ))
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background:#2a1a1a; color:#F2BFB4; border:1px solid #D94F38;"
            "border-radius:4px; padding:8px 10px; font-size:12px;"
        )
        layout.addWidget(banner)

        tree = QtWidgets.QTreeWidget()
        tree.setHeaderLabels([
            self.translate("Vidéo / Champ manquant", "Video / Missing field")
        ])
        tree.setColumnCount(1)
        tree.header().setStretchLastSection(True)
        tree.setAlternatingRowColors(True)
        tree.setStyleSheet(
            "QTreeWidget { background:#162433; color:#F2BFB4; border:1px solid #2a4057; }"
            "QHeaderView::section { background:#1a2e40; color:#2778a2; border:none; padding:4px; }"
            "QTreeWidget::item:alternate { background:#111f2e; }"
            "QTreeWidget::item { padding: 2px 0; }"
        )

        for name, probs in issues:
            parent = QtWidgets.QTreeWidgetItem(
                [f"🎬  {name}  ({len(probs)} champ(s) manquant(s))"]
            )
            parent.setForeground(0, QtGui.QBrush(QtGui.QColor("#F2BFB4")))
            parent.setFont(0, QtGui.QFont("Segoe UI", 10, QtGui.QFont.Weight.Bold))
            for label in probs:
                child = QtWidgets.QTreeWidgetItem([f"    ✗  {label}"])
                child.setForeground(0, QtGui.QBrush(QtGui.QColor("#E8A838")))
                parent.addChild(child)
            tree.addTopLevelItem(parent)
            parent.setExpanded(True)

        layout.addWidget(tree)

        btn_close = QtWidgets.QPushButton(self.translate("Fermer et corriger", "Close and fix"))
        btn_close.setStyleSheet(
            "QPushButton{background:#20415d;color:#F2BFB4;border:1px solid #2778a2;"
            "border-radius:4px;padding:5px 14px;font-size:11px;}"
            "QPushButton:hover{background:#2778a2;}"
        )
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        dlg.exec()

    # ── Feature : batch survey ────────────────────────────────────────────

    # ── Feature : import GPX ─────────────────────────────────────────────

    @staticmethod
    def _parse_gpx_points(gpx_path: str) -> list:
        """Retourne une liste triée de (datetime UTC, lat, lon) depuis un fichier GPX."""
        tree = ET.parse(gpx_path)
        root = tree.getroot()

        # Gestion des namespaces GPX 1.0, 1.1 et sans namespace
        tag = root.tag
        ns = ""
        if tag.startswith("{"):
            ns = tag[:tag.index("}") + 1]

        points = []
        for tag_name in (f"{ns}trkpt", f"{ns}wpt", f"{ns}rtept"):
            for pt in root.iter(tag_name):
                try:
                    lat = float(pt.get("lat"))
                    lon = float(pt.get("lon"))
                    time_elem = pt.find(f"{ns}time")
                    if time_elem is None or not time_elem.text:
                        continue
                    raw = time_elem.text.strip().replace("Z", "+00:00")
                    dt = datetime.fromisoformat(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    points.append((dt, lat, lon))
                except (ValueError, TypeError):
                    continue

        return sorted(points, key=lambda x: x[0])

    @staticmethod
    def _video_datetime_from_stem(stem: str) -> datetime | None:
        """Extrait le datetime UTC depuis un stem de fichier vidéo (format YYYYMMDDHHMMSS_...)."""
        m = re.match(r'^(\d{8})(\d{6})', stem)
        if not m:
            return None
        try:
            dt_str = m.group(1) + m.group(2)
            return datetime.strptime(dt_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _import_gpx(self):
        """Ouvre un explorateur pour choisir un .gpx et applique les coordonnées à toutes les vidéos."""
        if not self._working_dir:
            QtWidgets.QMessageBox.warning(
                self.widget,
                self.translate("Répertoire manquant", "Missing directory"),
                self.translate("Sélectionnez d'abord un répertoire de travail (page Accueil).",
                               "Select a working directory first (Home page).")
            )
            return

        gpx_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.widget,
            self.translate("Sélectionner un fichier GPX", "Select a GPX file"),
            "",
            "GPX files (*.gpx);;All files (*)"
        )
        if not gpx_path:
            return

        try:
            points = self._parse_gpx_points(gpx_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.widget,
                self.translate("Erreur GPX", "GPX Error"),
                self.translate(f"Impossible de lire le fichier GPX :\n{e}",
                               f"Cannot read GPX file:\n{e}")
            )
            return

        if not points:
            QtWidgets.QMessageBox.warning(
                self.widget,
                self.translate("GPX vide", "Empty GPX"),
                self.translate("Aucun point GPS trouvé dans ce fichier.",
                               "No GPS points found in this file.")
            )
            return

        matched, unmatched = 0, 0
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            video_path = str(video_path)
            stem = os.path.splitext(os.path.basename(video_path))[0]
            video_dt = self._video_datetime_from_stem(stem)

            # Trouver le waypoint le plus proche en temps
            if video_dt and points:
                closest = min(points, key=lambda p: abs((p[0] - video_dt).total_seconds()))
                lat, lon = closest[1], closest[2]
            elif points:
                # Pas de timestamp dans le nom → premier point du GPX
                lat, lon = points[0][1], points[0][2]
            else:
                unmatched += 1
                continue

            json_path = get_working_video_json_path(self._working_dir, video_path)
            if not os.path.isfile(json_path):
                unmatched += 1
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                obs = data.setdefault("video_observation", {})
                lat_str = str(lat).replace(".", ",")
                lon_str = str(lon).replace(".", ",")
                obs["latitude"] = {"value": lat_str}
                obs["longitude"] = {"value": lon_str}
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                matched += 1
            except Exception as e:
                print(f"[GPX] {os.path.basename(video_path)}: {e}")
                unmatched += 1

        self._rebuild_ft_table()
        if self._on_metadata_saved:
            self._on_metadata_saved()

        msg = self.translate(
            f"Coordonnées GPX appliquées à {matched} vidéo(s).",
            f"GPS coordinates applied to {matched} video(s)."
        )
        if unmatched:
            msg += self.translate(f"\n{unmatched} vidéo(s) ignorée(s) (JSON absent ou introuvable).",
                                   f"\n{unmatched} video(s) skipped (no output JSON).")
        QtWidgets.QMessageBox.information(
            self.widget,
            self.translate("Import GPX terminé", "GPX import done"),
            msg
        )

    def _apply_survey_to_all(self):
        """Propage les valeurs de l'en-tête campagne à toutes les vidéos du dossier de travail."""
        if not self._working_dir:
            QtWidgets.QMessageBox.warning(
                self.widget,
                self.translate("Impossible", "Impossible"),
                self.translate("Sélectionnez d'abord un répertoire de travail (page Accueil).",
                               "Select a working directory first (Home page).")
            )
            return
        for field_id in _INFOSTATION_FIELD_BLOCKS:
            w = self._infostation_widgets.get(field_id)
            if isinstance(w, QtWidgets.QLineEdit):
                self._on_infostation_changed(field_id, w.text().strip())
        n = self.video_model.rowCount()
        QtWidgets.QMessageBox.information(
            self.widget,
            self.translate("Propagation terminée", "Propagation complete"),
            self.translate(f"Propriétés campagne appliquées à {n} vidéo(s).",
                           f"Campaign properties applied to {n} video(s).")
        )

    # ── CSV export ────────────────────────────────────────────────────────

    def _collect_video_paths(self) -> list[str]:
        """Retourne la liste des chemins vidéo du modèle courant."""
        paths = []
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                vp = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if vp:
                    paths.append(str(vp))
        return paths

    def _export_infostation_action(self):
        """Point d'entrée utilisateur : vérifie toutes les métadonnées, bloque si incomplet."""
        if not self._working_dir:
            QtWidgets.QMessageBox.warning(
                self.widget,
                self.translate("Répertoire manquant", "Missing directory"),
                self.translate("Sélectionnez d'abord un répertoire de travail (page Accueil).",
                               "Please select a working directory first (Home page.")
            )
            return
        video_paths = self._collect_video_paths()
        if not video_paths:
            return

        issues = self._run_consistency_check(video_paths)
        if issues:
            # Des champs manquent → on affiche le bilan et on bloque l'export
            self._show_consistency_dialog(issues)
            return

        # Toutes les métadonnées sont complètes → export
        self.generate_infostation_csv()
        csv_path = get_infostation_path(self._working_dir)
        QtWidgets.QMessageBox.information(
            self.widget,
            self.translate("Export terminé", "Export complete"),
            self.translate(f"CSV Infostation généré :\n{csv_path}",
                           f"Infostation CSV generated:\n{csv_path}")
        )

    def generate_qualification_infostation(self, video_paths: list, working_dir: str) -> str | None:
        """Génère le CSV Infostation pour les vidéos retenues à la qualification.

        Retourne le chemin du CSV créé, ou None en cas d'échec.
        """
        if not working_dir or not video_paths:
            return None
        csv_path = get_infostation_path(working_dir)
        os.makedirs(working_dir, exist_ok=True)
        old_working_dir = self._working_dir
        self._working_dir = working_dir
        try:
            with open(csv_path, 'w', newline='', encoding='cp1252', errors='replace') as f:
                writer = csv.DictWriter(f, fieldnames=_INFOSTATION_COLUMNS, delimiter=';',
                                        extrasaction='ignore', quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                for vp in sorted(video_paths):
                    try:
                        row_data = self._build_infostation_row(vp)
                        row_data = {k: str(v).replace('\n', ' | ').replace('\r', '')
                                    for k, v in row_data.items()}
                        writer.writerow(row_data)
                    except Exception as e:
                        print(f"[INFOSTATION QUALIF] {os.path.basename(vp)}: {e}")
            return csv_path
        except Exception as e:
            print(f"[INFOSTATION QUALIF] Impossible d'écrire {csv_path}: {e}")
            return None
        finally:
            self._working_dir = old_working_dir

    def generate_infostation_csv(self):
        """Génère silencieusement le CSV Infostation (appelé aussi par l'auto-sync)."""
        if not self._working_dir:
            return
        video_paths = self._collect_video_paths()
        if not video_paths:
            return

        csv_path = get_infostation_path(self._working_dir)
        os.makedirs(self._working_dir, exist_ok=True)

        try:
            with open(csv_path, 'w', newline='', encoding='cp1252', errors='replace') as f:
                writer = csv.DictWriter(f, fieldnames=_INFOSTATION_COLUMNS, delimiter=';',
                                        extrasaction='ignore', quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                for vp in sorted(video_paths):
                    try:
                        row_data = self._build_infostation_row(vp)
                        row_data = {k: str(v).replace('\n', ' | ').replace('\r', '')
                                    for k, v in row_data.items()}
                        writer.writerow(row_data)
                    except Exception as e:
                        print(f"[INFOSTATION] {os.path.basename(vp)}: {e}")
        except Exception as e:
            print(f"[INFOSTATION] Impossible d'écrire {csv_path}: {e}")

    # ── Data updates ─────────────────────────────────────────────────────

    def _update_value(self, block_key: str, field_id: str, new_value: str,
                      source_widget: QtWidgets.QLineEdit | None = None):
        """Écrit new_value dans _json_data et propage le changement aux JSON sur disque."""
        if source_widget and isinstance(source_widget, QtWidgets.QLineEdit) and new_value:
            source_widget.setStyleSheet(_FIELD_STYLE)
        self._save_timer.start(800)

        if block_key in self._json_data:
            if field_id in self._json_data[block_key]:
                self._json_data[block_key][field_id]["value"] = new_value
            else:
                # Champ custom non encore présent → on l'initialise
                self._json_data[block_key][field_id] = {"value": new_value}

        if block_key in ("survey", "system"):
            # Propager le changement à TOUTES les vidéos du modèle,
            # mais uniquement dans le répertoire de travail (jamais dans les données source).
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
                    continue  # JSON de sortie absent → on ne touche pas aux données source
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if block_key in data and field_id in data[block_key]:
                        data[block_key][field_id]["value"] = new_value
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print(f"[SYNC ERROR] {e}")
        # Pour video_observation : uniquement _json_data en mémoire.
        # save_metadata_to_json (debounced 800 ms) écrit le JSON complet sur disque.

    def save_metadata_to_json(self):
        """Persiste _json_data dans current_template_json (appelé via timer debounce)."""
        if self.current_template_json:
            try:
                with open(self.current_template_json, 'w', encoding='utf-8') as f:
                    json.dump(self._json_data, f, indent=4, ensure_ascii=False)
                if self._on_metadata_saved:
                    self._on_metadata_saved()
                if self.current_video_path:
                    self._schedule_infostation_upsert(self.current_video_path)
            except Exception as e:
                print(f"[ERROR] Failed writing JSON: {e}")

    def inject_weather_data(self, data=None):
        """Rafraîchit le panneau météo depuis _json_data (appelé après réponse WeatherWorker)."""
        if "video_observation" in self._json_data:
            weather = {k: v for k, v in self._json_data["video_observation"].items()
                       if k in self.weather_sea_keys}
            self._display_weather_in_scroll(weather)

    # ── Weather web compare ───────────────────────────────────────────────

    def action_compare_weather_web(self):
        """Extrait lat/lon/date du JSON et lance WeatherWorker pour comparer avec les données web."""
        lat, lon, raw_date = None, None, None
        for block_content in self._json_data.values():
            if not isinstance(block_content, dict):
                continue
            if "date" in block_content and block_content["date"].get("value"):
                raw_date = block_content["date"]["value"]
            if not lat and "latitude" in block_content and block_content["latitude"].get("value"):
                lat = block_content["latitude"]["value"]
            if not lon and "longitude" in block_content and block_content["longitude"].get("value"):
                lon = block_content["longitude"]["value"]

        formatted_date = None
        if raw_date:
            date_str = str(raw_date).strip()
            if len(date_str) == 8 and date_str.isdigit():
                formatted_date = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
            elif "-" in date_str:
                formatted_date = date_str.split(" ")[0].split("T")[0]

        if not lat or not lon:
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Coordonnées manquantes", "Missing Coordinates"),
                self.translate(f"Latitude ({lat}) ou Longitude ({lon}) est manquante.",
                               f"Latitude ({lat}) or Longitude ({lon}) is missing."))
            return
        if not formatted_date:
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Date manquante ou invalide", "Missing or Invalid Date"),
                self.translate(f"La date lue est : '{raw_date}'.", f"The read date is: '{raw_date}'."))
            return

        self.weather_worker = WeatherWorker(lat, lon, formatted_date)
        self.weather_worker.weather_fetched.connect(self._open_web_weather_popup)
        self.weather_worker.start()

    def _open_web_weather_popup(self, fetched_api_data, relevant_date):
        """Ouvre WeatherWebDialog avec les données API récupérées par WeatherWorker."""
        if not fetched_api_data:
            QtWidgets.QMessageBox.critical(self.widget,
                self.translate("Erreur de connexion", "Connection Error"),
                self.translate("Impossible de récupérer les données.", "Unable to retrieve data."))
            return
        dialog = WeatherWebDialog(web_data=fetched_api_data, lang=self.current_language, parent=self.widget)
        dialog.exec()

    # ── Slate compare ─────────────────────────────────────────────────────

    def on_compare_slate_clicked(self):
        """Cherche l'événement 'slate' dans le JSON et affiche la frame correspondante."""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Erreur", "Error"),
                self.translate("Veuillez sélectionner une séquence vidéo valide.", "Please select a valid video sequence first."))
            return
        if not self.current_template_json or not os.path.exists(self.current_template_json):
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Ardoise introuvable", "Slate Not Found"),
                self.translate("Veuillez saisir l'entrée ardoise dans la vue événements d'abord.",
                               "Please input the slate record entry inside the events timeline view first."))
            return
        try:
            with open(self.current_template_json, 'r', encoding='utf-8') as f:
                self._json_data = json.load(f)
        except Exception as e:
            print(f"[SLATE] Failed reloading JSON: {e}")

        slate_frame = None
        obs = self._json_data.get("video_observation", {})
        for key in ["events_deployment", "events_interesting_images", "events_animal"]:
            if key in obs and isinstance(obs[key], list) and obs[key]:
                for evt in obs[key][0].get("values", []):
                    if any(kw in str(evt.get("value", "")).lower()
                           for kw in ["whiteboard", "slate", "tableau blanc", "ardoise"]):
                        slate_frame = evt.get("frame_number_start")
                        break
            if slate_frame is not None:
                break

        if slate_frame is None:
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Ardoise introuvable", "Slate Not Found"),
                self.translate("Veuillez saisir l'entrée ardoise dans la vue événements d'abord.",
                               "Please input the slate record entry inside the events timeline view first."))
            return
        self._display_slate_window(slate_frame)

    def _display_slate_window(self, frame_number: int):
        """Extrait frame_number de la vidéo et l'affiche dans une boîte de dialogue."""
        cap = cv2.VideoCapture(self.current_video_path)
        if not cap.isOpened():
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Erreur", "Error"),
                self.translate("Impossible d'ouvrir le fichier vidéo.", "Unable to open video file."))
            return
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number - 1)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Erreur", "Error"),
                self.translate(f"Impossible de lire la frame {frame_number}.", f"Unable to read frame {frame_number}."))
            return

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        q_img = QtGui.QImage(frame_rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(q_img)

        dialog = QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle(self.translate(f"Ardoise — Frame {frame_number}", f"Slate — Frame {frame_number}"))
        dialog.setMinimumSize(800, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        lbl = QtWidgets.QLabel()
        lbl.setPixmap(pixmap.scaled(780, 520, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                    QtCore.Qt.TransformationMode.SmoothTransformation))
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        btn = QtWidgets.QPushButton(self.translate("Fermer", "Close"))
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn)
        dialog.show()
