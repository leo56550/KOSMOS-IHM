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
    get_temp_json_path,
)
from views.dialogs.weather_dialog import WeatherWebDialog

# ── Chargement dynamique du schéma depuis template.json ─────────────────
_TEMPLATE_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'template.json')

# Champs calculés automatiquement (non éditables dans le tableau)
_COMPUTED_FIELDS = {"codeObs", "video_path"}

# Champs de l'en-tête campagne (identiques pour toutes les vidéos → read-only dans le tableau)
_CAMPAIGN_HEADER_KEYS = {
    "zone", "type", "region", "date",
    "boat_name", "pilot_name", "crew_names",
}


def _load_infostation_schema() -> list[tuple]:
    """Lit template.json et retourne la liste ordonnée des champs infoStation_visibility=oui.

    Retourne : [(section, field_key, name_fr, read_only), ...]
    section order: survey → video_observation → system
    """
    try:
        with open(_TEMPLATE_JSON_PATH, 'r', encoding='utf-8') as f:
            template = json.load(f)
    except Exception as e:
        print(f"[SCHEMA] Impossible de lire template.json : {e}")
        return []

    result = []
    for section_name, section in template.items():
        if not isinstance(section, dict):
            continue
        for field_key, field_def in section.items():
            if not isinstance(field_def, dict):
                continue
            if field_def.get("infoStation_visibility") == "oui":
                label = field_def.get("name_fr") or field_def.get("name") or field_key
                read_only = field_key in _COMPUTED_FIELDS
                result.append((section_name, field_key, label, read_only))
    return result


# Schéma complet (section, field_key, name_fr, read_only) pour tous les champs infoStation
_INFOSTATION_SCHEMA: list[tuple] = _load_infostation_schema()

# Schéma CSV infoStation : ordre et noms de colonnes calqués sur TEMPLATE_infoStation.xlsx.
# Chaque tuple : (section, field_key, csv_column_name)
# section=None → champ calculé ou non mappé (toujours vide)
# Les lignes sont écrites comme LISTE ordonnée (csv.writer) pour gérer le doublon "Zone".
_INFOSTATION_CSV_SCHEMA: list[tuple] = [
    ("video_observation", "codeObs",                   "Codestation"),           # col  1
    ("survey",            "zone",                      "Zone"),                   # col  2
    ("survey",            "type",                      "Type"),                   # col  3
    ("system",            "type_system",               "Systeme"),                # col  4
    ("video_observation", "latitude",                  "Latitude"),               # col  5
    ("video_observation", "longitude",                 "Longitude"),              # col  6
    ("survey",            "date",                      "Date"),                   # col  7
    ("video_observation", "time",                      "Heure"),                  # col  8
    ("video_observation", "point_name",                "Nom du point"),           # col  9
    ("video_observation", "gps_waypoint",              "Pt GPS Garmin"),          # col 10
    ("video_observation", "boatgps_waypoint",          "Pt gps bateau"),          # col 11
    ("survey",            "region",                    "Zone"),                   # col 12 – doublon intentionnel XLSX
    ("video_observation", "site",                      "Site"),                   # col 13
    ("video_observation", "monitoring_program",        "Pt de Suivi"),            # col 14
    ("video_observation", "depth",                     "Profondeur"),             # col 15
    ("video_observation", "deployment_comment",        "Commentaires terrain pose"),         # col 16
    ("video_observation", "location_comment",          "Commentaires terrain localisation"),  # col 17
    ("video_observation", "video_path",                "Dossier Datawork"),       # col 18
    ("video_observation", "video_number",              "sous-dossier video & metadata"),      # col 19
    ("video_observation", "derush_comment",            "Commentaires video"),     # col 20
    (None,                "events_interesting_images", "Images interessantes"),   # col 21 – calculé
    ("video_observation", "habitat",                   "Milieu/Habitat"),         # col 22
    ("video_observation", "estimated_visibility",      "Visibilite"),             # col 23
    ("video_observation", "exploitable",               "Exploitable"),            # col 24
    ("video_observation", "protectionStatus1",         "Codestatut"),             # col 25
    ("video_observation", "protectionStatus2",         "Codestatut2"),            # col 26
    (None,                "statutprotection",          "Statutprotection"),       # col 27 – non mappé
    ("video_observation", "tide",                      "Maree"),                  # col 28
    ("video_observation", "moon",                      "Lune"),                   # col 29
    ("video_observation", "weather",                   "Meteo"),                  # col 30
    ("video_observation", "wind",                      "Vent"),                   # col 31
    ("video_observation", "seaState",                  "Mer"),                    # col 32
    ("video_observation", "swell_height",              "Houle"),                  # col 33
    ("survey",            "boat_name",                 "Bateau"),                 # col 34
    ("survey",            "pilot_name",                "Pilote"),                 # col 35
    ("survey",            "crew_names",                "Equipage"),               # col 36
    ("video_observation", "fish_annotator",            "Analyseur poisson"),      # col 37
    ("video_observation", "habitat_annotator",         "Analyseur habitat"),      # col 38
    ("video_observation", "distance_min",              "Distance analysable min (m)"),  # col 39
    ("video_observation", "distance_max",              "Distance analysable max (m)"),  # col 40
    (None,                "substrat",                  "Substrat"),               # col 41 – non mappé
]

# Colonnes du CSV infostation (ordre XLSX)
_INFOSTATION_COLUMNS: list[str] = [col for _, _, col in _INFOSTATION_CSV_SCHEMA]

# Colonnes du tableau = exactement les mêmes que le CSV (41 colonnes, même ordre XLSX).
# Tuple : (col_name, section, field_key, read_only)
# read_only = champs calculés (section None ou _COMPUTED_FIELDS) + champs identiques pour toutes les vidéos
_FT_TABLE_COLS: list[tuple] = [
    (col_name, section, field_key,
     section is None or field_key in _COMPUTED_FIELDS or field_key in _CAMPAIGN_HEADER_KEYS)
    for section, field_key, col_name in _INFOSTATION_CSV_SCHEMA
]

# Champs custom à initialiser dans les anciens JSONs (backward compat)
_CUSTOM_VOB_FIELDS: list[str] = [
    "habitat", "timecode_ardoise", "timecode_debut",
    "location_comment", "derush_comment", "interesting_images",
    "fish_annotator", "habitat_annotator",
    "distance_min", "distance_max",
    "time", "latitude", "longitude",
    "substrat", "boatgps_waypoint",
    "timecode_landing", "timecode_takeoff", "timecode_end",
    "video_path", "video_number",
    "site", "protectionStatus1", "protectionStatus2",
    "station_number",  # backward compat (anciens JSONs)
]

# En-tête campagne (champs identiques pour toutes les vidéos) : widget_id → (block, json_key)
_INFOSTATION_FIELD_BLOCKS: dict[str, tuple] = {
    "ft_nom_campagne":    ("survey", "survey_name"),
    "ft_zone":            ("survey", "zone"),
    "ft_type":            ("survey", "type"),
    "ft_region":          ("survey", "region"),
    "ft_date":            ("survey", "date"),
    "ft_bateau":          ("survey", "boat_name"),
    "ft_pilote":          ("survey", "pilot_name"),
    "ft_equipage":        ("survey", "crew_names"),
    "ft_partenaires":     ("survey", "partners"),
    "ft_dossier_datawork":("survey", "datawork_folder"),
    "ft_sous_dossier":    ("survey", "video_subfolder"),
}


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
        if self.data_system_container:
            self.data_system_container.setVisible(False)
        self.specific_container_data = self.widget.findChild(QtWidgets.QFrame, "specific_container_data")

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
        """Masque le panneau latéral Météo/Vidéo — les boutons sont dans la barre du tableau."""
        self._scroll_weather = None
        self._scroll_video = None
        # container_weather_data est le parent de container_meteo_data et specific_container_data
        outer = self.widget.findChild(QtWidgets.QFrame, "container_weather_data")
        if outer:
            outer.setVisible(False)
            outer.setMaximumWidth(0)

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

        _btn_style_action = (
            "QPushButton{background:#1a2e3a;color:#a8d8ea;border:1px solid #2778a2;"
            "border-radius:4px;padding:2px 10px;font-size:10px;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2778a2;color:white;}"
        )
        self._btn_ardoise = QtWidgets.QPushButton(
            self.translate("Comparer avec l'ardoise", "Compare with slate"))
        self._btn_ardoise.setStyleSheet(_btn_style_action)
        self._btn_ardoise.setEnabled(False)
        self._btn_ardoise.clicked.connect(self.on_compare_slate_clicked)
        tb_row.addWidget(self._btn_ardoise)

        self._btn_web = QtWidgets.QPushButton(
            self.translate("Comparer données web", "Compare web data"))
        self._btn_web.setStyleSheet(_btn_style_action)
        self._btn_web.setEnabled(False)
        self._btn_web.clicked.connect(self.action_compare_weather_web)
        tb_row.addWidget(self._btn_web)

        self._btn_gpx = QtWidgets.QPushButton(self.translate("IMPORT GPX", "IMPORT GPX"))
        self._btn_gpx.setStyleSheet(
            "QPushButton{background:#1a3a4a;color:#7ec8e3;border:1px solid #2778a2;"
            "border-radius:4px;padding:2px 10px;font-size:10px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2778a2;color:white;}"
        )
        self._btn_gpx.clicked.connect(self._import_gpx)
        tb_row.addWidget(self._btn_gpx)

        self._btn_terrain = QtWidgets.QPushButton(
            self.translate("FEUILLE TERRAIN", "FIELD SHEET"))
        self._btn_terrain.setStyleSheet(
            "QPushButton{background:#2a1a3a;color:#c8a0e3;border:1px solid #7a3ab0;"
            "border-radius:4px;padding:2px 10px;font-size:10px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#7a3ab0;color:white;}"
        )
        self._btn_terrain.clicked.connect(self._open_feuille_terrain)
        tb_row.addWidget(self._btn_terrain)

        self._btn_generer = QtWidgets.QPushButton(
            self.translate("GENERER INFOSTATION", "GENERATE INFOSTATION"))
        self._btn_generer.setStyleSheet(
            "QPushButton{background:#1a3a1a;color:#80e880;border:1px solid #2a8a2a;"
            "border-radius:4px;padding:2px 10px;font-size:10px;font-weight:bold;"
            "font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2a8a2a;color:white;}"
        )
        self._btn_generer.clicked.connect(self._export_infostation_action)
        tb_row.addWidget(self._btn_generer)
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

        # Ligne 2 : Date (Site/Codestatut/Codestatut2 sont désormais par vidéo → tableau)
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(6)
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
        cp.addLayout(row3)

        # Ligne 4 : Partenaires | Dossier Datawork | Sous-dossier | Appliquer
        row4 = QtWidgets.QHBoxLayout()
        row4.setSpacing(6)
        row4.addWidget(_hl("Partenaires"))
        row4.addWidget(_hi("ft_partenaires", "Ifremer; IMT; KAL", 160))
        row4.addSpacing(8)
        row4.addWidget(_hl("Dossier Datawork"))
        row4.addWidget(_hi("ft_dossier_datawork", "260701_ATL_CC_ENEZEG", 160))
        row4.addSpacing(8)
        row4.addWidget(_hl("Sous-dossier"))
        row4.addWidget(_hi("ft_sous_dossier", "0128", 60))
        row4.addStretch()

        self._btn_apply_all = QtWidgets.QPushButton(
            self.translate("Appliquer à toutes les vidéos", "Apply to all videos"))
        self._btn_apply_all.setStyleSheet(
            "QPushButton{background:#20415d;color:#F2BFB4;border:1px solid #2778a2;"
            "border-radius:4px;padding:2px 10px;font-size:10px;font-family:'Segoe UI',sans-serif;}"
            "QPushButton:hover{background:#2778a2;}"
        )
        self._btn_apply_all.clicked.connect(self._apply_survey_to_all)
        row4.addWidget(self._btn_apply_all)
        cp.addLayout(row4)

        outer.addWidget(campaign_panel)

        # ── Tableau infostation (une ligne = une vidéo) ───────────────────
        self._ft_table = QtWidgets.QTableWidget()
        self._ft_table.setColumnCount(len(_FT_TABLE_COLS))
        self._ft_table.setHorizontalHeaderLabels([c[0] for c in _FT_TABLE_COLS])
        self._ft_table.horizontalHeader().setStretchLastSection(False)
        self._ft_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)
        self._ft_table.horizontalHeader().setMinimumSectionSize(40)
        self._ft_table.verticalHeader().setDefaultSectionSize(30)
        self._ft_table.verticalHeader().hide()
        self._ft_table.setAlternatingRowColors(False)
        self._ft_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._ft_table.setSortingEnabled(True)
        self._ft_table.setStyleSheet("""
            QTableWidget {
                background-color: #111820; alternate-background-color: #0d1620;
                color: #F2BFB4; border: none; gridline-color: #1a2e40;
                font-size: 12px; font-family: 'Segoe UI', sans-serif;
            }
            QHeaderView::section {
                background-color: #162433; color: #7ec8e3; font-weight: bold;
                border: 1px solid #1e3448; padding: 5px 6px; font-size: 12px;
            }
            QTableWidget::item { padding: 3px 6px; }
            QTableWidget::item:selected { background-color: #20415d; color: white; }
            QTableWidget::item:alternate { background-color: #0d1620; }
        """)
        # Largeurs par défaut — noms de colonnes = ceux du XLSX (via _INFOSTATION_CSV_SCHEMA)
        _default_widths = {
            "Codestation":                       90,
            "Zone":                              55,
            "Type":                              55,
            "Systeme":                           70,
            "Latitude":                          90,
            "Longitude":                         90,
            "Date":                              75,
            "Heure":                             55,
            "Nom du point":                      80,
            "Pt GPS Garmin":                     100,
            "Pt gps bateau":                     100,
            "Site":                              80,
            "Pt de Suivi":                       90,
            "Profondeur":                        65,
            "Commentaires terrain pose":         150,
            "Commentaires terrain localisation": 150,
            "Dossier Datawork":                  160,
            "sous-dossier video & metadata":     160,
            "Commentaires video":                160,
            "Images interessantes":              160,
            "Milieu/Habitat":                    90,
            "Visibilite":                        80,
            "Exploitable":                       75,
            "Codestatut":                        80,
            "Codestatut2":                       80,
            "Statutprotection":                  90,
            "Maree":                             70,
            "Lune":                              70,
            "Meteo":                             80,
            "Vent":                              60,
            "Mer":                               60,
            "Houle":                             65,
            "Bateau":                            90,
            "Pilote":                            90,
            "Equipage":                          120,
            "Analyseur poisson":                 100,
            "Analyseur habitat":                 100,
            "Distance analysable min (m)":       110,
            "Distance analysable max (m)":       110,
            "Substrat":                          90,
        }
        for col_i, (col_label, *_) in enumerate(_FT_TABLE_COLS):
            self._ft_table.setColumnWidth(col_i, _default_widths.get(col_label, 80))

        self._ft_table.cellChanged.connect(self._on_ft_table_cell_changed)
        self._ft_table.cellClicked.connect(self._on_ft_table_row_clicked)
        outer.addWidget(self._ft_table, stretch=1)

        self.refresh_statistics()

    # ── Tableau feuille terrain ───────────────────────────────────────────

    # Palette de couleurs de fond par système (fond sombre, lisible)
    _SYSTEM_COLORS = [
        "#0d2030",  # bleu-gris foncé (défaut)
        "#1a2010",  # vert foncé
        "#201020",  # violet foncé
        "#201808",  # brun foncé
        "#081820",  # cyan foncé
        "#200810",  # rouge foncé
        "#101820",  # ardoise foncé
        "#181010",  # bordeaux foncé
    ]

    def _rebuild_ft_table(self):
        """Reconstruit le tableau infostation depuis les JSONs de toutes les vidéos."""
        if not hasattr(self, '_ft_table') or self._ft_table is None:
            return
        self._set_video_buttons_enabled(False)
        self._ft_table.setSortingEnabled(False)
        self._ft_table.blockSignals(True)
        self._ft_table.setRowCount(0)

        _ro_flags = (QtCore.Qt.ItemFlag.ItemIsSelectable |
                     QtCore.Qt.ItemFlag.ItemIsEnabled)
        _rw_flags = _ro_flags | QtCore.Qt.ItemFlag.ItemIsEditable

        # Index de la colonne "Systeme" dans le schéma
        _systeme_col = next((i for i, (_, _, k, _) in enumerate(_FT_TABLE_COLS)
                             if k == "type_system"), None)
        _system_color_map: dict[str, str] = {}

        for model_row in range(self.video_model.rowCount()):
            item = self.video_model.item(model_row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            video_path = str(video_path)

            row_data = self._build_infostation_row(video_path)

            # Couleur de fond selon la valeur "Systeme"
            system_val = (str(row_data[_systeme_col]).strip()
                          if _systeme_col is not None and _systeme_col < len(row_data)
                          else "")
            if system_val and system_val not in _system_color_map:
                idx = len(_system_color_map) % len(self._SYSTEM_COLORS)
                _system_color_map[system_val] = self._SYSTEM_COLORS[idx]
            row_bg = QtGui.QColor(_system_color_map.get(system_val, self._SYSTEM_COLORS[0]))

            trow = self._ft_table.rowCount()
            self._ft_table.insertRow(trow)

            for col_i, (col_label, block_name, json_key, read_only) in enumerate(_FT_TABLE_COLS):
                val = str(row_data[col_i] if col_i < len(row_data) else "")
                cell = QtWidgets.QTableWidgetItem(val)
                cell.setTextAlignment(
                    QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft)
                cell.setFlags(_ro_flags if read_only else _rw_flags)
                cell.setBackground(QtGui.QBrush(row_bg))
                if read_only:
                    cell.setForeground(QtGui.QBrush(QtGui.QColor("#7a9aaa")))
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
            print(f"[TEMP_JSON] {os.path.basename(json_path)} ← {block_name}.{json_key} = {new_value!r}")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(jdata, f, indent=4, ensure_ascii=False)
            if self._on_metadata_saved:
                self._on_metadata_saved()
        except Exception as e:
            print(f"[INFOSTATION TABLE] Error saving {block_name}.{json_key}: {e}")

        if json_key == "point_name" and new_value:
            self._check_point_name_duplicate(video_path, new_value)

    def _check_point_name_duplicate(self, video_path: str, point_name: str) -> None:
        """Avertit si point_name est déjà utilisé par une autre vidéo du même système."""
        system_dir = os.path.dirname(os.path.dirname(os.path.normpath(video_path)))
        duplicates = []
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            other_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not other_path or os.path.normpath(str(other_path)) == os.path.normpath(video_path):
                continue
            if os.path.dirname(os.path.dirname(os.path.normpath(str(other_path)))) != system_dir:
                continue
            temp_path = get_temp_json_path(str(other_path))
            if not os.path.isfile(temp_path):
                continue
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                other_pname = (data.get("video_observation", {})
                                   .get("point_name", {})
                                   .get("value") or "").strip()
                if other_pname == point_name:
                    duplicates.append(os.path.basename(str(other_path)))
            except Exception:
                continue

        if duplicates:
            QtWidgets.QMessageBox.warning(
                self.widget,
                "Doublon de point détecté",
                f"⚠️  Le point « {point_name} » est déjà utilisé par :\n"
                + "\n".join(f"  •  {v}" for v in duplicates)
                + "\n\nVérifiez le numéro de point saisi à l'ardoise."
            )

    def _on_ft_table_row_clicked(self, row: int, _col: int):
        """Charge les données de la vidéo cliquée et active les boutons contextuel."""
        first_item = self._ft_table.item(row, 0)
        if first_item is None:
            return
        video_path = first_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return
        self._set_video_buttons_enabled(True)
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
        self._retranslate_ui()
        self.refresh_statistics()
        if self.current_template_json and os.path.exists(self.current_template_json):
            self.load_all_data(self.current_template_json)

    def _retranslate_ui(self):
        """Met à jour les textes des boutons du panneau infostation."""
        if hasattr(self, '_btn_generer'):
            self._btn_generer.setText(self.translate("GENERER INFOSTATION", "GENERATE INFOSTATION"))
        if hasattr(self, '_btn_terrain'):
            self._btn_terrain.setText(self.translate("FEUILLE TERRAIN", "FIELD SHEET"))
        if hasattr(self, '_btn_apply_all'):
            self._btn_apply_all.setText(self.translate("Appliquer à toutes les vidéos", "Apply to all videos"))
        if hasattr(self, '_btn_ardoise'):
            self._btn_ardoise.setText(self.translate("Comparer avec l'ardoise", "Compare with slate"))
        if hasattr(self, '_btn_web'):
            self._btn_web.setText(self.translate("Comparer données web", "Compare web data"))

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

    def _set_video_buttons_enabled(self, enabled: bool):
        for btn in (getattr(self, '_btn_ardoise', None), getattr(self, '_btn_web', None)):
            if btn:
                btn.setEnabled(enabled)

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

    def load_all_data(self, json_path: str):
        """Lit json_path et peuple tous les panneaux (système, campagne, vidéo, météo).

        Si json_path est un _temp.json, fusionne avec le JSON brut d'acquisition pour
        récupérer les données system et survey de l'acquisition (caméra, date, GPS…).
        """
        if not os.path.isfile(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self._json_data = json.load(f)
                self.current_template_json = json_path
        except Exception as e:
            print(f"[ERROR] Unable to read JSON file: {e}")
            return

        # Fusion avec le JSON brut si on lit un _temp.json
        if json_path.endswith('_temp.json'):
            _base = os.path.splitext(os.path.basename(json_path))[0]  # "<stem>_temp"
            _stem = _base[:-5]  # retire "_temp"
            _raw = os.path.join(os.path.dirname(json_path), f"{_stem}.json")
            if os.path.isfile(_raw):
                try:
                    with open(_raw, 'r', encoding='utf-8') as _f:
                        _raw_data = json.load(_f)
                    # system : toujours depuis le JSON brut (données acquisition)
                    if "system" in _raw_data:
                        self._json_data["system"] = _raw_data["system"]
                    # survey : base = acquisition, surchargé par valeurs IHM non-nulles
                    if "survey" in _raw_data:
                        merged_survey = dict(_raw_data["survey"])
                        for k, v in self._json_data.get("survey", {}).items():
                            if isinstance(v, dict) and v.get("value") is not None:
                                merged_survey[k] = v
                        self._json_data["survey"] = merged_survey
                except Exception as e:
                    print(f"[META] Fusion JSON brut impossible : {e}")

        if "video_observation" in self._json_data:
            self._ensure_custom_fields()
            obs = self._json_data["video_observation"]
            weather = {k: v for k, v in obs.items() if k in self.weather_sea_keys}
            # Champs gérés dans la feuille terrain ou dans la page Événements → masqués ici
            _feuille_terrain_keys = {
                "depth", "point_name", "gps_waypoint", "boatgps_waypoint", "deployment_comment",
                "fish_annotator", "habitat_annotator",
                "distance_min", "distance_max",
                "timecode_ardoise", "timecode_debut",
                "timecode_landing", "timecode_takeoff", "timecode_end",
                "timecode_atterrissage", "timecode_decollage",  # backward compat
                "derush_comment", "interesting_images",
                "moteur", "screenshot",
                "latitude", "longitude", "time",
                "video_path", "video_number",
                "site", "protectionStatus1", "protectionStatus2",
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
                print(f"[TEMP_JSON] {os.path.basename(json_path)} ← {block_name}.{json_key} = {value!r}")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[INFOSTATION HEADER] {field_id}: {e}")
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

        # ── Timecode atterrissage ────────────────────────────────────────
        if not self._v(obs, "timecode_landing") and not self._v(obs, "timecode_atterrissage"):
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower()
                       for kw in ["atterrissage", "atterissage", "landing"]):
                    self._json_data["video_observation"].setdefault(
                        "timecode_landing", {"value": None}
                    )["value"] = _tc_str(ev)
                    break

        # ── Timecode décollage ───────────────────────────────────────────
        if not self._v(obs, "timecode_takeoff") and not self._v(obs, "timecode_decollage"):
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower()
                       for kw in ["décollage", "decollage", "takeoff", "take_off"]):
                    self._json_data["video_observation"].setdefault(
                        "timecode_takeoff", {"value": None}
                    )["value"] = _tc_str(ev)
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
        """Régénère le CSV infostation complet (approche simplifiée, gère le doublon 'Zone')."""
        self.generate_infostation_csv()

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
          202207181314_ATL_CC220006    → ('CC220006', '13:14')  [nouveau : HHmm]
          20190819140122_ATL_CC190001  → ('CC190001', '14:01')  [ancien  : HHmmss]
          CC190001                     → ('CC190001', '')
        """
        m = re.match(r'^(\d{8})(\d{4,6})_[^_]+_(.+)$', stem)
        if m:
            time_raw = m.group(2)
            heure = f"{time_raw[0:2]}:{time_raw[2:4]}"
            return m.group(3), heure
        return stem, ""

    def _build_infostation_row(self, video_path: str) -> list:
        """Construit la liste ordonnée des valeurs pour une ligne CSV (ordre _INFOSTATION_CSV_SCHEMA).

        Retourne une liste positionnelle (pour gérer le doublon "Zone" en cols 2 et 12).
        """
        stem = os.path.splitext(os.path.basename(video_path))[0]
        codestat, heure_stem = self._extract_stem_parts(stem)

        # Source primaire : _temp.json (données IHM)
        # Fallback : JSON brut d'acquisition pour les champs encore null
        temp_path = get_temp_json_path(video_path)
        raw_path  = get_video_json_path(video_path)

        temp_data = {}
        if os.path.isfile(temp_path):
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    temp_data = json.load(f)
            except Exception:
                pass

        raw_data = {}
        if os.path.isfile(raw_path):
            try:
                with open(raw_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
            except Exception:
                pass

        def _merge_section(section: str) -> dict:
            """Retourne la section fusionnée : _temp.json prioritaire, brut en fallback."""
            tmp = dict(temp_data.get(section, {}))
            raw = raw_data.get(section, {})
            for k, v in raw.items():
                if k not in tmp:
                    tmp[k] = v
                else:
                    cur_val = tmp[k].get("value") if isinstance(tmp[k], dict) else tmp[k]
                    if cur_val is None or str(cur_val).strip() == "":
                        tmp[k] = v
            return tmp

        jdata = {
            "system":            _merge_section("system"),
            "survey":            _merge_section("survey"),
            "video_observation": _merge_section("video_observation"),
        }
        surv = jdata.get("survey", {})
        obs  = jdata.get("video_observation", {})

        # ── Helpers ──────────────────────────────────────────────────────────
        def _ev_tc(keywords: list[str]) -> str:
            """Cherche le premier event_deployment dont la valeur contient un des mots-clés."""
            for ev in (obs.get("events_deployment", [{}]) or [{}])[0].get("values", []):
                if any(kw in (ev.get("value") or "").lower() for kw in keywords):
                    return ev.get("time_code_start") or ""
            return ""

        gps = get_video_gps_coords(video_path)
        lat_gps = str(gps[0]).replace('.', ',') if gps else ""
        lon_gps = str(gps[1]).replace('.', ',') if gps else ""

        # ── Construction de la ligne dans l'ordre exact du XLSX ───────────
        row: list = []
        for section, field_key, col_name in _INFOSTATION_CSV_SCHEMA:

            # Champ calculé : Images intéressantes
            if section is None and field_key == "events_interesting_images":
                parts = []
                for ev in (obs.get("events_interesting_images", [{}]) or [{}])[0].get("values", []):
                    tc = ev.get("time_code_start") or ""
                    detail = ev.get("comment") or ev.get("value") or ""
                    parts.append(f"{tc} {detail}".strip())
                row.append(" ; ".join(parts))
                continue

            block = jdata.get(section, {}) if section else {}
            val = self._v(block, field_key)

            # ── Surcharges par field_key ──────────────────────────────────
            if field_key == "date":
                val = self._fmt_date(val) if val else ""

            elif field_key == "video_path" and not val:
                _vdir = os.path.dirname(os.path.normpath(video_path))
                _sys = os.path.basename(os.path.dirname(_vdir))
                _camp = os.path.basename(os.path.dirname(os.path.dirname(_vdir)))
                val = f"{_camp}\\{_sys}"

            elif field_key == "video_file_name" and not val:
                val = stem

            elif field_key == "video_number" and not val:
                val = os.path.basename(os.path.dirname(os.path.normpath(video_path)))

            elif field_key == "latitude":
                val = val.replace('.', ',') if val else lat_gps

            elif field_key == "longitude":
                val = val.replace('.', ',') if val else lon_gps

            elif field_key == "time" and not val:
                val = heure_stem

            elif field_key == "codeObs" and not val:
                # Reconstruction dynamique : zone + 2 derniers chiffres de l'année + n° point 0000
                import re as _re2
                zone_v   = self._v(surv, "zone").strip()
                date_v   = self._v(surv, "date").strip()
                year_2d  = _re2.sub(r"[^0-9]", "", date_v)[2:4] if date_v else ""
                pname_v  = (self._v(obs, "point_name") or self._v(obs, "station_number")).strip()
                if pname_v:
                    try:
                        station_idx = f"{int(pname_v):04d}"
                    except ValueError:
                        station_idx = pname_v.zfill(4)[:4]
                else:
                    station_idx = ""
                if zone_v and year_2d and station_idx:
                    val = f"{zone_v}{year_2d}{station_idx}"
                else:
                    val = "A saisir"

            elif field_key == "point_name" and not val:
                val = self._v(obs, "station_number") or "A saisir"

            elif field_key == "boatgps_waypoint" and not val:
                val = self._v(obs, "gps_boat_point")

            elif field_key == "site" and not val:
                val = self._v(surv, "site")

            elif field_key == "protectionStatus1" and not val:
                val = self._v(surv, "protectionStatus1")

            elif field_key == "protectionStatus2" and not val:
                val = self._v(surv, "protectionStatus2")

            elif field_key == "timecode_ardoise" and not val:
                val = _ev_tc(["ardoise", "slate", "tableau blanc", "whiteboard"])

            elif field_key == "timecode_landing" and not val:
                val = (self._v(obs, "timecode_atterrissage")
                       or _ev_tc(["atterrissage", "atterissage", "landing"]))

            elif field_key == "timecode_takeoff" and not val:
                val = (self._v(obs, "timecode_decollage")
                       or _ev_tc(["décollage", "decollage", "takeoff", "take_off"]))

            elif field_key == "timecode_debut" and not val:
                val = _ev_tc(["atterrissage", "landing"])

            row.append(val)

        return row

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
        """Affiche tous les champs manquants par vidéo dans un arbre expandable.
        Retourne True si l'utilisateur choisit de générer quand-même."""
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

        _force = [False]

        btn_row = QtWidgets.QHBoxLayout()

        btn_force = QtWidgets.QPushButton(self.translate("Générer quand-même", "Generate anyway"))
        btn_force.setStyleSheet(
            "QPushButton{background:#3a2800;color:#E8A838;border:1px solid #E8A838;"
            "border-radius:4px;padding:5px 14px;font-size:11px;}"
            "QPushButton:hover{background:#E8A838;color:#1a1a1a;}"
        )
        def _on_force():
            _force[0] = True
            dlg.accept()
        btn_force.clicked.connect(_on_force)

        btn_close = QtWidgets.QPushButton(self.translate("Fermer et corriger", "Close and fix"))
        btn_close.setStyleSheet(
            "QPushButton{background:#20415d;color:#F2BFB4;border:1px solid #2778a2;"
            "border-radius:4px;padding:5px 14px;font-size:11px;}"
            "QPushButton:hover{background:#2778a2;}"
        )
        btn_close.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_force)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.exec()
        return _force[0]

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
        """Extrait le datetime UTC depuis un stem de fichier vidéo.

        Formats reconnus :
          202207181314_ATL_…   → datetime(2022, 7, 18, 13, 14)  [HHmm]
          20190819140122_ATL_… → datetime(2019, 8, 19, 14,  1)  [HHmmss]
        """
        m = re.match(r'^(\d{8})(\d{4,6})', stem)
        if not m:
            return None
        try:
            date_str, time_str = m.group(1), m.group(2)
            if len(time_str) == 6:
                fmt = "%Y%m%d%H%M%S"
            else:
                fmt = "%Y%m%d%H%M"
            return datetime.strptime(date_str + time_str, fmt).replace(tzinfo=timezone.utc)
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
                print(f"[TEMP_JSON] {os.path.basename(json_path)} ← video_observation.latitude={lat_str!r}, longitude={lon_str!r}")
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

    # Champs requis dans le JSON de chaque vidéo pour construire le nom formaté
    # Format : (block, json_key, label_affichage)
    _REQUIRED_VIDEO_JSON_FIELDS = [
        ("survey",           "date",           "Date (survey.date)"),
        ("survey",           "region",         "Région / AREA (survey.region)"),
        ("survey",           "zone",           "Zone (survey.zone)"),
        ("video_observation","point_name",     "N° du point (video_observation.point_name)"),
    ]

    def _on_save_clicked(self):
        """Valide que tous les champs nécessaires au nom formaté sont remplis pour chaque vidéo."""
        if not self._working_dir:
            QtWidgets.QMessageBox.warning(
                self.widget, "Aucune campagne ouverte",
                "Ouvrez d'abord une campagne avant de sauvegarder."
            )
            return

        # ── 1. Vérification des JSONs vidéo (champs critiques pour le nom) ──
        missing_by_video: list[tuple[str, list[str]]] = []

        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            json_path = resolve_video_json_path(self._working_dir, str(video_path))
            if not os.path.isfile(json_path):
                missing_by_video.append((os.path.basename(str(video_path)), ["JSON introuvable"]))
                continue

            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                missing_by_video.append((os.path.basename(str(video_path)), ["JSON illisible"]))
                continue

            missing_fields = []
            for block, key, label in self._REQUIRED_VIDEO_JSON_FIELDS:
                entry = data.get(block, {}).get(key, {})
                val = (entry.get("value", "") if isinstance(entry, dict) else entry) or ""
                if not str(val).strip():
                    missing_fields.append(label)

            if missing_fields:
                missing_by_video.append((os.path.basename(str(video_path)), missing_fields))

        if missing_by_video:
            lines = []
            for vid_name, fields in missing_by_video[:10]:
                lines.append(f"• {vid_name} : {', '.join(fields)}")
            if len(missing_by_video) > 10:
                lines.append(f"  … et {len(missing_by_video) - 10} autre(s) vidéo(s)")

            dlg = QtWidgets.QDialog(self.widget)
            dlg.setWindowTitle("Champs manquants")
            dlg.setMinimumWidth(520)
            _lay = QtWidgets.QVBoxLayout(dlg)
            _lay.setSpacing(10)
            _lay.setContentsMargins(14, 14, 14, 14)

            _icon_row = QtWidgets.QHBoxLayout()
            _ico = QtWidgets.QLabel()
            _ico.setPixmap(self.widget.style().standardPixmap(
                QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning))
            _icon_row.addWidget(_ico, alignment=QtCore.Qt.AlignmentFlag.AlignTop)
            _msg = QtWidgets.QLabel(
                "Les champs suivants sont requis pour générer les noms de dossier :\n\n"
                + "\n".join(lines)
                + "\n\nRenseignez ces champs dans la feuille terrain ou directement dans les JSON vidéo."
            )
            _msg.setWordWrap(True)
            _icon_row.addWidget(_msg, stretch=1)
            _lay.addLayout(_icon_row)

            _force = [False]
            _btn_row = QtWidgets.QHBoxLayout()

            _btn_force = QtWidgets.QPushButton("Générer quand-même")
            _btn_force.setStyleSheet(
                "QPushButton{background:#3a2800;color:#E8A838;border:1px solid #E8A838;"
                "border-radius:4px;padding:5px 14px;font-size:11px;}"
                "QPushButton:hover{background:#E8A838;color:#1a1a1a;}"
            )
            def _on_force():
                _force[0] = True
                dlg.accept()
            _btn_force.clicked.connect(_on_force)

            _btn_ok = QtWidgets.QPushButton("OK")
            _btn_ok.setDefault(True)
            _btn_ok.clicked.connect(dlg.accept)

            _btn_row.addWidget(_btn_force)
            _btn_row.addStretch()
            _btn_row.addWidget(_btn_ok)
            _lay.addLayout(_btn_row)

            dlg.exec()
            if not _force[0]:
                return

        # ── 2. Tout est rempli ou génération forcée ───────────────────────────
        self._generate_benthoss_folder()
        self.generate_infostation_csv()

    def _blink_widgets(self, header_widgets: list, table_cells: list):
        """Fait clignoter en rouge les champs vides (3 allers-retours, 200 ms chacun)."""
        _ERR = ("background-color:#3a0f0f;color:#ff6060;"
                "border:2px solid #ff3333;border-radius:3px;padding:3px 6px;")
        _ERR_CELL = QtGui.QColor("#5a1010")

        count = [0]

        # Sauvegarde des couleurs d'origine des cellules
        orig_bg = {}
        if hasattr(self, '_ft_table'):
            for r, c in table_cells:
                item = self._ft_table.item(r, c)
                if item:
                    orig_bg[(r, c)] = item.background()

        def _toggle():
            count[0] += 1
            on = count[0] % 2 == 1  # impair = rouge

            for w in header_widgets:
                w.setStyleSheet(_ERR if on else (_FIELD_STYLE if w.text().strip() else _EMPTY_STYLE))

            if hasattr(self, '_ft_table'):
                for r, c in table_cells:
                    item = self._ft_table.item(r, c)
                    if item:
                        if on:
                            item.setBackground(_ERR_CELL)
                        else:
                            item.setBackground(orig_bg.get((r, c), QtGui.QColor()))

            if count[0] >= 6:
                self._blink_timer.stop()

        self._blink_timer = QtCore.QTimer()
        self._blink_timer.setInterval(220)
        self._blink_timer.timeout.connect(_toggle)
        self._blink_timer.start()
        _toggle()  # démarre immédiatement en rouge

    @staticmethod
    @staticmethod
    def _parse_nom_complet(survey: dict, vob: dict, video_path: str = "") -> str:
        """Construit le nom formaté YYYYMMDDhhmm_AREA_codeStation depuis les métadonnées.

        codeStation = ZONE + année(2d) + index(4d)  ex: CC260053
        """
        import os as _os, re as _re
        from datetime import datetime as _dt

        def _sv(block, key):
            entry = block.get(key, {})
            return (entry.get("value", "") if isinstance(entry, dict) else entry) or ""

        # ── Date → YYYYMMDD ──────────────────────────────────────────────
        date_raw = _sv(survey, "date").strip()
        date_part = ""
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%m/%d/%Y"):
            try:
                date_part = _dt.strptime(date_raw, fmt).strftime("%Y%m%d")
                break
            except ValueError:
                pass
        if not date_part:
            date_part = _re.sub(r"[^0-9]", "", date_raw)[:8]

        # ── Heure → hhmm ────────────────────────────────────────────────
        time_raw = _sv(vob, "time").strip()
        digits = _re.sub(r"[^0-9]", "", time_raw)
        time_part = digits[:4] if len(digits) >= 4 else ""

        # ── Region (AREA) et Zone ────────────────────────────────────────
        region = _sv(survey, "region").strip()   # ex: ATL
        zone   = _sv(survey, "zone").strip()     # ex: CC

        # ── Année 2 chiffres ─────────────────────────────────────────────
        year_2d = date_part[2:4] if len(date_part) >= 4 else ""

        # ── N° du point : point_name en priorité, fallback station_number (backward compat) ──
        station_num_raw = (_sv(vob, "point_name") or _sv(vob, "station_number")).strip()
        if station_num_raw:
            try:
                station_idx = f"{int(station_num_raw):04d}"
            except ValueError:
                station_idx = station_num_raw.zfill(4)[:4]
        elif video_path:
            # Fallback anciens projets : dossier parent numérique
            parent_name = _os.path.basename(_os.path.dirname(_os.path.normpath(video_path)))
            try:
                station_idx = f"{int(parent_name):04d}"
            except ValueError:
                m = _re.search(r'(\d{4,})$', parent_name)
                station_idx = f"{int(m.group(1)):04d}" if m else "0000"
        else:
            station_idx = "0000"

        # ── codeStation = ZONE + année + N°point  ex: CC260053 ───────────
        if zone and year_2d:
            codestation = f"{zone}{year_2d}{station_idx}"
        else:
            codestation = _sv(vob, "codeObs").strip()  # fallback legacy

        parts = [p for p in [date_part + time_part, region, codestation] if p]
        return "_".join(parts) if parts else ""

    def _generate_benthoss_folder(self):
        """Génère BenthOS_sorties/<YYYYMMDDhhmm_AREA_codeStation>/ avec IMG/, JSON, VIAME.csv et .lnk."""
        if not self._working_dir:
            QtWidgets.QMessageBox.warning(
                self.widget, "Aucune campagne",
                "Ouvrez d'abord une campagne avant de générer les dossiers."
            )
            return

        import shutil as _shutil
        import subprocess

        benthoss_dir = self._working_dir  # BenthOS_sorties IS le dossier de travail
        errors = []
        generated = []

        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if not item:
                continue
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue
            json_path = resolve_video_json_path(self._working_dir, str(video_path))
            if not os.path.isfile(json_path):
                continue

            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue

            survey = data.get("survey", {})
            vob    = data.get("video_observation", {})
            nom    = self._parse_nom_complet(survey, vob, str(video_path))
            if not nom:
                nom = os.path.splitext(os.path.basename(str(video_path)))[0]

            dest_dir = os.path.join(benthoss_dir, nom)
            try:
                os.makedirs(dest_dir, exist_ok=True)
                os.makedirs(os.path.join(dest_dir, "IMG"), exist_ok=True)

                # JSON renommé
                _shutil.copy2(json_path, os.path.join(dest_dir, f"{nom}.json"))

                # Annotation_VIAME.csv (vide — en attente d'export events)
                viame_path = os.path.join(dest_dir, "Annotation_VIAME.csv")
                if not os.path.isfile(viame_path):
                    with open(viame_path, 'w', encoding='utf-8') as vf:
                        vf.write("# 1: Detection or Track-id,"
                                 "2: Video or Image-id,3: Frame-id,"
                                 "4-7: Corners (x1 y1 x2 y2),"
                                 "8: Confidence,9+: class-id\n")

                # Raccourci Windows (.lnk) vers la vidéo brute
                lnk_path = os.path.join(dest_dir, f"{nom}.lnk")
                subprocess.run([
                    "powershell", "-Command",
                    f'$ws = New-Object -ComObject WScript.Shell; '
                    f'$s = $ws.CreateShortcut("{lnk_path}"); '
                    f'$s.TargetPath = "{video_path}"; '
                    f'$s.Save()'
                ], shell=True, capture_output=True)

                generated.append(nom)
            except Exception as e:
                errors.append(f"{nom}: {e}")

        msg = f"{len(generated)} dossier(s) générés dans :\n{benthoss_dir}"
        if errors:
            msg += f"\n\nErreurs ({len(errors)}) :\n" + "\n".join(errors[:5])
        QtWidgets.QMessageBox.information(self.widget, "Génération terminée", msg)

    def _open_feuille_terrain(self):
        """Ouvre un explorateur pour choisir une image (JPG/PNG) et l'affiche dans un QDialog."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.widget,
            self.translate("Ouvrir feuille terrain", "Open field sheet"),
            "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff);;All files (*)"
        )
        if not path:
            return

        pixmap = QtGui.QPixmap(path)
        if pixmap.isNull():
            QtWidgets.QMessageBox.warning(
                self.widget,
                self.translate("Image invalide", "Invalid image"),
                self.translate(
                    f"Impossible de charger l'image :\n{path}",
                    f"Cannot load image:\n{path}"
                )
            )
            return

        dlg = QtWidgets.QDialog(self.widget)
        dlg.setWindowTitle(
            self.translate("Feuille terrain", "Field sheet")
            + f" — {os.path.basename(path)}"
        )
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setStyleSheet("background-color: #0d1b2a;")

        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        max_w = int(screen.width() * 0.90)
        max_h = int(screen.height() * 0.90)

        scaled = pixmap.scaled(
            max_w, max_h,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

        layout = QtWidgets.QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #0d1b2a; border: none;")

        lbl = QtWidgets.QLabel()
        lbl.setPixmap(scaled)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("background-color: #0d1b2a;")
        scroll.setWidget(lbl)
        layout.addWidget(scroll)

        # Barre basse : bouton fermer + indicateur de zoom
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet("background-color: #111f2e; border-top: 1px solid #1e3448;")
        bar_layout = QtWidgets.QHBoxLayout(bar)
        bar_layout.setContentsMargins(10, 0, 10, 0)

        lbl_hint = QtWidgets.QLabel(
            self.translate("Clic droit → Enregistrer l'image sous…", "Right-click → Save image as…")
        )
        lbl_hint.setStyleSheet("color: #506070; font-size: 10px;")

        btn_close = QtWidgets.QPushButton(self.translate("Fermer", "Close"))
        btn_close.setFixedSize(80, 24)
        btn_close.setStyleSheet(
            "QPushButton{background:#1e3448;color:#a0c4d8;border:1px solid #2778a2;"
            "border-radius:4px;font-size:10px;}"
            "QPushButton:hover{background:#2778a2;color:white;}"
        )
        btn_close.clicked.connect(dlg.close)

        bar_layout.addWidget(lbl_hint)
        bar_layout.addStretch()
        bar_layout.addWidget(btn_close)
        layout.addWidget(bar)

        dlg.resize(
            min(scaled.width() + 20, max_w),
            min(scaled.height() + 36, max_h),
        )
        self._terrain_dialog = dlg  # évite le garbage collect
        dlg.show()

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

        # Collecte des valeurs depuis les widgets de l'en-tête
        field_values: dict[str, tuple] = {}  # field_id → (block_name, json_key, value)
        for field_id, (block_name, json_key) in _INFOSTATION_FIELD_BLOCKS.items():
            w = self._infostation_widgets.get(field_id)
            if w is None:
                continue
            if isinstance(w, QtWidgets.QLineEdit):
                val = w.text().strip()
            elif isinstance(w, QtWidgets.QPlainTextEdit):
                val = w.toPlainText().strip()
            elif isinstance(w, QtWidgets.QComboBox):
                val = w.currentText().strip()
            else:
                continue
            field_values[field_id] = (block_name, json_key, val)

        # Écriture en une passe par vidéo, une reconstruction de tableau à la fin
        n = 0
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
                for _fid, (block_name, json_key, val) in field_values.items():
                    block = data.setdefault(block_name, {})
                    if json_key in block and isinstance(block[json_key], dict):
                        block[json_key]["value"] = val or None
                    else:
                        block[json_key] = {"value": val or None}
                    print(f"[TEMP_JSON] {os.path.basename(json_path)} ← {block_name}.{json_key} = {val!r}")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                n += 1
            except Exception as e:
                print(f"[APPLY_ALL] {video_path}: {e}")

        # Reconstruction du tableau une seule fois
        self._rebuild_ft_table()

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
            if not self._show_consistency_dialog(issues):
                return

        # Métadonnées complètes ou export forcé par l'utilisateur
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
                writer = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(_INFOSTATION_COLUMNS)
                for vp in sorted(video_paths):
                    try:
                        row_data = self._build_infostation_row(vp)
                        writer.writerow([str(v).replace('\n', ' | ').replace('\r', '')
                                         for v in row_data])
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
                writer = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(_INFOSTATION_COLUMNS)
                for vp in sorted(video_paths):
                    try:
                        row_data = self._build_infostation_row(vp)
                        writer.writerow([str(v).replace('\n', ' | ').replace('\r', '')
                                         for v in row_data])
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
                        print(f"[TEMP_JSON] {os.path.basename(json_path)} ← {block_key}.{field_id} = {new_value!r}")
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
                print(f"[TEMP_JSON] {os.path.basename(self.current_template_json)} ← video_observation (sauvegarde complète)")
                with open(self.current_template_json, 'w', encoding='utf-8') as f:
                    json.dump(self._json_data, f, indent=4, ensure_ascii=False)
                if self._on_metadata_saved:
                    self._on_metadata_saved()
                pass  # CSV généré uniquement via le bouton Qualifier
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
                self.translate("Aucun JSON trouvé pour cette vidéo.",
                               "No JSON found for this video."))
            return
        try:
            with open(self.current_template_json, 'r', encoding='utf-8') as f:
                self._json_data = json.load(f)
        except Exception as e:
            print(f"[SLATE] Failed reloading JSON: {e}")

        slate_frame = None
        slate_timecode = None
        obs = self._json_data.get("video_observation", {})
        for key in ["events_deployment", "events_interesting_images", "events_animal"]:
            if key in obs and isinstance(obs[key], list) and obs[key]:
                for evt in obs[key][0].get("values", []):
                    if any(kw in str(evt.get("value", "")).lower()
                           for kw in ["whiteboard", "slate", "tableau blanc", "ardoise"]):
                        slate_frame = evt.get("frame_number_start")
                        slate_timecode = evt.get("time_code_start")
                        break
            if slate_frame is not None or slate_timecode:
                break

        # Fallback : calculer le frame depuis le timecode si frame_number_start absent (anciens JSONs)
        if slate_frame is None and slate_timecode:
            try:
                cap_tmp = cv2.VideoCapture(self.current_video_path)
                fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 25.0
                cap_tmp.release()
                parts = slate_timecode.replace(',', ':').split(':')
                parts = [int(p) for p in parts]
                if len(parts) == 2:
                    secs = parts[0] * 60 + parts[1]
                elif len(parts) == 3:
                    secs = parts[0] * 3600 + parts[1] * 60 + parts[2]
                else:
                    secs = 0
                slate_frame = int(secs * fps)
            except Exception:
                pass

        if slate_frame is None:
            QtWidgets.QMessageBox.warning(self.widget,
                self.translate("Ardoise introuvable", "Slate Not Found"),
                self.translate("Aucune ardoise trouvée pour cette vidéo. Saisissez-la dans la page Validation.",
                               "No slate found for this video. Please enter it in the Validation page."))
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
