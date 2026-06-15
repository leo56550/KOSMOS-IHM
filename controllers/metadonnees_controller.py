import os
import json
import cv2

from PyQt6 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from services.weather_service import WeatherWorker
from services.campaign_service import get_video_json_path, _find_first_json_in_folder
from views.dialogs.weather_dialog import WeatherWebDialog

_FIELD_STYLE = ("background-color: #162433; color: #F2BFB4; border: 1px solid #2a4057;"
                " border-radius: 3px; padding: 3px 6px; font-family: 'Segoe UI', sans-serif;")
_EMPTY_STYLE = ("background-color: #162433; color: #5a7a8a; border: 1px solid #1e3448;"
                " border-radius: 3px; padding: 3px 6px; font-family: 'Segoe UI', sans-serif;")
_LABEL_STYLE  = ("color: #b0c8d8; font-weight: bold; font-size: 11px; border: none;"
                 " min-width: 130px; font-family: 'Segoe UI', sans-serif;")
_SECTION_TITLE_STYLE = ("font-weight: bold; color: #F2BFB4; font-size: 13px; padding-bottom: 2px;"
                        " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;")
_SECTION_LINE_STYLE  = "border-bottom: 1px solid #2778A2; margin-bottom: 6px;"


class MetadonneesController:
    def __init__(self, widget: QtWidgets.QWidget, video_model: QtGui.QStandardItemModel,
                 trash_model: QtGui.QStandardItemModel):
        self.widget = widget
        self.video_model = video_model
        self.trash_model = trash_model
        self._json_data = {}
        self.current_template_json = None
        self.current_video_path = None
        self.current_language = 'en'

        self.weather_sea_keys = [
            "moon", "tide", "coefficient", "wind", "wind_direction",
            "airTemp", "seaState", "swell_height", "swell_direction",
            "water_temperature", "weather"
        ]

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
        self.data_survey_container = self.widget.findChild(QtWidgets.QFrame, "data_survey_container")
        self.specific_container_data = self.widget.findChild(QtWidgets.QFrame, "specific_container_data")

        # Remove the 1200px minimum that was causing the toolbar to go off-screen
        meteo_outer = self.widget.findChild(QtWidgets.QFrame, "container_weather_data")
        if meteo_outer:
            meteo_outer.setMinimumWidth(0)

        self._setup_ui()
        self._init_scroll_areas()
        self._init_trash_gauge()

        if self.tree_videos:
            self.tree_videos.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self._save_timer = QtCore.QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_metadata_to_json)

    # ── Setup ─────────────────────────────────────────────────────────────

    def _setup_ui(self):
        if self.tree_videos:
            self.tree_videos.setModel(self.video_model)
            self.tree_videos.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.tree_videos.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

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
        self._scroll_survey = self._make_scroll_area(self.data_survey_container)
        self._scroll_system = self._make_scroll_area(self.data_system_container)
        self._scroll_weather = self._make_scroll_area(self.container_weather_data)
        self._scroll_video = self._make_scroll_area(self.specific_container_data)

    def _init_trash_gauge(self):
        if not self.graph_trash_container:
            return

        # Compact height — prevents the canvas from growing over the toolbar
        self.graph_trash_container.setMaximumHeight(155)

        old = self.graph_trash_container.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            dummy = QtWidgets.QWidget()
            dummy.setLayout(old)

        row_layout = QtWidgets.QHBoxLayout(self.graph_trash_container)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.setSpacing(8)

        # Small donut chart (fixed size — no growing)
        self.figure = Figure(figsize=(1.4, 1.4), facecolor='none')
        self.figure.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setFixedSize(130, 130)
        # NoFocus prevents the canvas from stealing focus and hiding the toolbar
        self.canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        row_layout.addWidget(self.canvas)

        # Stats labels beside the chart
        stats = QtWidgets.QWidget()
        stats.setStyleSheet("background: transparent;")
        stats_vbox = QtWidgets.QVBoxLayout(stats)
        stats_vbox.setContentsMargins(0, 10, 0, 10)
        stats_vbox.setSpacing(6)

        self.lbl_stat_title = QtWidgets.QLabel("Campagne")
        self.lbl_stat_title.setStyleSheet(
            "color: #F2BFB4; font-weight: bold; font-size: 11px; border: none;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;")
        self.lbl_video_count = QtWidgets.QLabel("Vidéos : —")
        self.lbl_video_count.setStyleSheet(
            "color: #2778A2; font-size: 11px; border: none; font-family: 'Segoe UI', sans-serif;")
        self.lbl_trash_count = QtWidgets.QLabel("Poubelle : —")
        self.lbl_trash_count.setStyleSheet(
            "color: #D94F38; font-size: 11px; border: none; font-family: 'Segoe UI', sans-serif;")

        for lbl in [self.lbl_stat_title, self.lbl_video_count, self.lbl_trash_count]:
            stats_vbox.addWidget(lbl)
        stats_vbox.addStretch()
        row_layout.addWidget(stats)

        self.ax = self.figure.add_subplot(111)
        self.refresh_statistics()

    # ── Public interface ─────────────────────────────────────────────────

    def set_language(self, language: str):
        self.current_language = language
        if self.current_template_json and os.path.exists(self.current_template_json):
            self.load_all_data(self.current_template_json)

    def load_campaign_videos(self, model: QtGui.QStandardItemModel):
        self.video_model = model
        if self.tree_videos:
            self.tree_videos.setModel(self.video_model)
            # setModel() remplace le selectionModel — on reconnecte le signal au nouveau
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
        indexes = selected.indexes()
        if not indexes:
            return
        # Toujours cibler la colonne 0 — c'est là qu'est stocké UserRole
        col0_index = indexes[0].sibling(indexes[0].row(), 0)
        item = self.video_model.itemFromIndex(col0_index)
        if not item:
            return
        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return
        self.current_video_path = str(video_path)
        json_path = get_video_json_path(self.current_video_path)
        if os.path.exists(json_path):
            self.load_all_data(json_path)

    def load_global_campaign_metadata(self, campaign_folder: str):
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
        if not json_path or not os.path.isfile(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ERROR] Unable to load common data: {e}")
            return

        if "system" in data:
            self._display_block_in_scroll("system", data["system"], self._scroll_system, "Système")
        if "survey" in data:
            self._display_block_in_scroll("survey", data["survey"], self._scroll_survey, "Campagne")

    def load_all_data(self, json_path: str):
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
                                          self._scroll_system, "Système")
        if "survey" in self._json_data:
            self._display_block_in_scroll("survey", self._json_data["survey"],
                                          self._scroll_survey, "Campagne")
        if "video_observation" in self._json_data:
            obs = self._json_data["video_observation"]
            weather = {k: v for k, v in obs.items() if k in self.weather_sea_keys}
            specific = {k: v for k, v in obs.items() if k not in self.weather_sea_keys}
            self._display_block_in_scroll("video_observation", specific,
                                          self._scroll_video, "Vidéo",
                                          extra_btn=("Compare with slate", self.on_compare_slate_clicked))
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
        title_lbl = QtWidgets.QLabel("Météo & Mer")
        title_lbl.setStyleSheet(_SECTION_TITLE_STYLE)
        hdr_row.addWidget(title_lbl)
        btn_web = QtWidgets.QPushButton("Comparer données web")
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
        if not hasattr(self, 'ax'):
            return
        video_count = self.video_model.rowCount()
        trash_count = self.trash_model.rowCount()

        if hasattr(self, 'lbl_video_count'):
            self.lbl_video_count.setText(f"Vidéos : {video_count}")
            self.lbl_trash_count.setText(f"Poubelle : {trash_count}")

        self.ax.clear()
        if video_count + trash_count == 0:
            self.ax.pie([1], colors=['#2a2a2a'], wedgeprops=dict(width=0.3))
        else:
            self.ax.pie(
                [video_count, trash_count],
                colors=['#2778A2', '#D94F38'],
                startangle=90,
                wedgeprops=dict(width=0.35, edgecolor='#111')
            )
        self.ax.axis('equal')
        # draw_idle defers the repaint to the next Qt event — avoids painting over other widgets
        self.canvas.draw_idle()

    # ── Data updates ─────────────────────────────────────────────────────

    def _update_value(self, block_key: str, field_id: str, new_value: str,
                      source_widget: QtWidgets.QLineEdit | None = None):
        if source_widget and isinstance(source_widget, QtWidgets.QLineEdit) and new_value:
            source_widget.setStyleSheet(_FIELD_STYLE)

        if block_key in self._json_data and field_id in self._json_data[block_key]:
            self._json_data[block_key][field_id]["value"] = new_value

        if block_key in ("survey", "system"):
            for row in range(self.video_model.rowCount()):
                item = self.video_model.item(row, 0)
                if not item:
                    continue
                video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if not video_path or not os.path.exists(video_path):
                    continue
                json_path = get_video_json_path(video_path)
                if os.path.exists(json_path):
                    try:
                        with open(json_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if block_key in data and field_id in data[block_key]:
                            data[block_key][field_id]["value"] = new_value
                            with open(json_path, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2, ensure_ascii=False)
                    except Exception as e:
                        print(f"[SYNC ERROR] {e}")
        else:
            if self.current_template_json and os.path.exists(self.current_template_json):
                try:
                    with open(self.current_template_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if block_key in data and field_id in data[block_key]:
                        data[block_key][field_id]["value"] = new_value
                        with open(self.current_template_json, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"[SAVE ERROR] {e}")

    def save_metadata_to_json(self):
        if self.current_template_json:
            try:
                with open(self.current_template_json, 'w', encoding='utf-8') as f:
                    json.dump(self._json_data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[ERROR] Failed writing JSON: {e}")

    def inject_weather_data(self, data=None):
        if "video_observation" in self._json_data:
            weather = {k: v for k, v in self._json_data["video_observation"].items()
                       if k in self.weather_sea_keys}
            self._display_weather_in_scroll(weather)

    # ── Weather web compare ───────────────────────────────────────────────

    def action_compare_weather_web(self):
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
            QtWidgets.QMessageBox.warning(self.widget, "Missing Coordinates",
                                          f"Latitude ({lat}) or Longitude ({lon}) is missing.")
            return
        if not formatted_date:
            QtWidgets.QMessageBox.warning(self.widget, "Missing or Invalid Date",
                                          f"The read date is: '{raw_date}'.")
            return

        self.weather_worker = WeatherWorker(lat, lon, formatted_date)
        self.weather_worker.weather_fetched.connect(self._open_web_weather_popup)
        self.weather_worker.start()

    def _open_web_weather_popup(self, fetched_api_data, relevant_date):
        if not fetched_api_data:
            QtWidgets.QMessageBox.critical(self.widget, "Connection Error", "Unable to retrieve data.")
            return
        dialog = WeatherWebDialog(web_data=fetched_api_data, lang=self.current_language, parent=self.widget)
        dialog.exec()

    # ── Slate compare ─────────────────────────────────────────────────────

    def on_compare_slate_clicked(self):
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            QtWidgets.QMessageBox.warning(self.widget, "Error", "Please select a valid video sequence first.")
            return
        if not self.current_template_json or not os.path.exists(self.current_template_json):
            QtWidgets.QMessageBox.warning(self.widget, "Slate Not Found",
                                          "Please input the slate record entry inside the events timeline view first.")
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
            QtWidgets.QMessageBox.warning(self.widget, "Slate Not Found",
                                          "Please input the slate record entry inside the events timeline view first.")
            return
        self._display_slate_window(slate_frame)

    def _display_slate_window(self, frame_number: int):
        cap = cv2.VideoCapture(self.current_video_path)
        if not cap.isOpened():
            QtWidgets.QMessageBox.warning(self.widget, "Error", "Unable to open video file.")
            return
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number - 1)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            QtWidgets.QMessageBox.warning(self.widget, "Error", f"Unable to read frame {frame_number}.")
            return

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        q_img = QtGui.QImage(frame_rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(q_img)

        dialog = QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle(f"Slate — Frame {frame_number}")
        dialog.setMinimumSize(800, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        lbl = QtWidgets.QLabel()
        lbl.setPixmap(pixmap.scaled(780, 520, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                    QtCore.Qt.TransformationMode.SmoothTransformation))
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        btn = QtWidgets.QPushButton("Fermer")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn)
        dialog.show()
