import os
import json
import cv2

from PyQt6 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from services.weather_service import WeatherWorker
from services.campaign_service import get_video_json_path, _find_first_json_in_folder
from views.dialogs.weather_dialog import WeatherWebDialog


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

        self._setup_ui()
        self._init_main_layouts()
        self._init_trash_gauge()

        if self.tree_videos:
            self.tree_videos.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self._save_timer = QtCore.QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_metadata_to_json)

    # --- Setup helpers ---

    def _setup_ui(self):
        if self.tree_videos:
            self.tree_videos.setModel(self.video_model)
            self.tree_videos.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

    def _init_main_layouts(self):
        containers = [
            (self.container_weather_data, "weather_grid_layout"),
            (self.data_system_container, "system_grid_layout"),
            (self.data_survey_container, "survey_grid_layout"),
            (self.specific_container_data, "video_grid_layout"),
        ]
        for widget, attr_name in containers:
            if widget:
                if widget.layout() is None:
                    layout = QtWidgets.QVBoxLayout(widget)
                    layout.setContentsMargins(10, 10, 10, 10)
                    layout.setSpacing(8)
                setattr(self, attr_name, widget.layout())
            else:
                setattr(self, attr_name, None)

    def _init_trash_gauge(self):
        if not self.graph_trash_container:
            return
        graph_layout = self.graph_trash_container.layout() or QtWidgets.QVBoxLayout(self.graph_trash_container)
        self.figure = Figure(figsize=(3, 3), facecolor='none')
        self.canvas = FigureCanvas(self.figure)
        graph_layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self.refresh_statistics()

    # --- Public interface ---

    def set_language(self, language: str):
        self.current_language = language
        if self.current_template_json and os.path.exists(self.current_template_json):
            self.load_all_data(self.current_template_json)

    def load_campaign_videos(self, model: QtGui.QStandardItemModel):
        self.video_model = model
        if self.tree_videos:
            self.tree_videos.setModel(self.video_model)

    def on_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes:
            return
        item = self.video_model.itemFromIndex(indexes[0])
        if item:
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if video_path:
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
            self._display_data_block("system", data["system"], self.system_grid_layout, "System Data")
        if "survey" in data:
            self._display_data_block("survey", data["survey"], self.survey_grid_layout, "Campaign Data")

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
            self._display_data_block("system", self._json_data["system"], self.system_grid_layout, "System Data")
        if "survey" in self._json_data:
            self._display_data_block("survey", self._json_data["survey"], self.survey_grid_layout, "Campaign Data")

        if "video_observation" in self._json_data:
            video_obs = self._json_data["video_observation"]
            weather_sea_dict = {k: v for k, v in video_obs.items() if k in self.weather_sea_keys}
            specific_video_dict = {k: v for k, v in video_obs.items() if k not in self.weather_sea_keys}
            self._display_data_block("video_observation", specific_video_dict, self.video_grid_layout, "Video Data")
            self._display_weather_data(weather_sea_dict)

    def _display_data_block(self, block_key, block_data, obsolete_layout, title, target_container=None):
        container_map = {
            "system": self.data_system_container,
            "survey": self.data_survey_container,
            "video_observation": self.specific_container_data,
        }
        container = target_container if target_container else container_map.get(block_key)
        if not container:
            return

        block_name = f"dynamic_form_{block_key}"
        for child in container.findChildren(QtWidgets.QWidget, block_name):
            child.setParent(None)
            child.deleteLater()

        if container.layout() is None:
            QtWidgets.QVBoxLayout(container).setContentsMargins(5, 5, 5, 5)

        form_widget = QtWidgets.QWidget()
        form_widget.setObjectName(block_name)
        form_layout = QtWidgets.QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)

        header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 5)

        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("font-weight: bold; color: white; font-size: 13px;")
        header_layout.addWidget(title_label)

        if block_key == "video_observation" and not target_container:
            btn_slate = QtWidgets.QPushButton("Compare with slate")
            btn_slate.setStyleSheet("""
                QPushButton { background-color: #3a3a3a; color: #00ffaa; border: 1px solid #555;
                              border-radius: 4px; padding: 4px 8px; font-weight: bold; }
                QPushButton:hover { background-color: #4a4a4a; border-color: #00ffaa; }
                QPushButton:pressed { background-color: #2a2a2a; }
            """)
            btn_slate.clicked.connect(self.on_compare_slate_clicked)
            header_layout.addWidget(btn_slate, 0, QtCore.Qt.AlignmentFlag.AlignRight)

        header_widget.setStyleSheet("border-bottom: 2px solid #555; padding-bottom: 4px;")
        form_layout.addWidget(header_widget)

        if not isinstance(block_data, dict):
            return

        lang = self.current_language
        for field_id, structure in block_data.items():
            if not isinstance(structure, dict) or "name" not in structure:
                continue

            tooltip_text = structure.get("description_fr", "")
            val = structure.get("value", "")
            example = structure.get("example", "")
            auth_values = structure.get(f"authorized_values_{lang}")
            label_text = structure.get(f"name_{lang}", structure.get("name", field_id))

            w = QtWidgets.QWidget()
            h_layout = QtWidgets.QHBoxLayout(w)
            h_layout.setContentsMargins(5, 3, 5, 3)
            h_layout.setSpacing(10)

            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet("color: #ccc; font-weight: bold; min-width: 150px; border: none;")
            if tooltip_text:
                lbl.setToolTip(tooltip_text)
            h_layout.addWidget(lbl, 1)

            if auth_values:
                combo = QtWidgets.QComboBox()
                combo.addItems([str(v) for v in auth_values])
                if val:
                    idx = combo.findText(str(val))
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                combo.currentTextChanged.connect(
                    lambda t, b=block_key, f_id=field_id, w_in=combo: self._update_value(b, f_id, t, w_in)
                )
                h_layout.addWidget(combo, 2)
            else:
                line = QtWidgets.QLineEdit()
                line.setText(str(val) if val else "")
                line.setPlaceholderText(str(example))
                line.setStyleSheet(
                    "background-color: #2b2b2b; color: #ffaa00;" if val else
                    "background-color: #2b2b2b; color: #666;"
                )
                line.textChanged.connect(
                    lambda t, b=block_key, f_id=field_id, w_in=line: self._update_value(b, f_id, t, w_in)
                )
                h_layout.addWidget(line, 2)

            form_layout.addWidget(w)

        form_layout.addStretch()
        container.layout().addWidget(form_widget)

    def _display_weather_data(self, weather_sea_dict):
        container = self.container_weather_data
        if not container:
            return

        for child in container.findChildren(QtWidgets.QWidget, "dynamic_form_weather_sea"):
            child.setParent(None)
            child.deleteLater()

        if container.layout() is None:
            QtWidgets.QVBoxLayout(container).setContentsMargins(5, 5, 5, 5)

        form_widget = QtWidgets.QWidget()
        form_widget.setObjectName("dynamic_form_weather_sea")
        form_layout = QtWidgets.QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)

        header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 5)

        title_label = QtWidgets.QLabel("Weather & Sea Data")
        title_label.setStyleSheet("font-weight: bold; color: white; font-size: 13px;")
        header_layout.addWidget(title_label)

        btn_web = QtWidgets.QPushButton("Compare with Web Data")
        btn_web.setStyleSheet("""
            QPushButton { background-color: #3a3a3a; color: #00ffaa; border: 1px solid #555;
                          border-radius: 4px; padding: 4px 8px; font-weight: bold; }
            QPushButton:hover { background-color: #4a4a4a; border-color: #00ffaa; }
            QPushButton:pressed { background-color: #2a2a2a; }
        """)
        btn_web.clicked.connect(self.action_compare_weather_web)
        header_layout.addWidget(btn_web, 0, QtCore.Qt.AlignmentFlag.AlignRight)

        header_widget.setStyleSheet("border-bottom: 2px solid #555; padding-bottom: 4px;")
        form_layout.addWidget(header_widget)

        if isinstance(weather_sea_dict, dict):
            lang = self.current_language
            for field_id, structure in weather_sea_dict.items():
                if not isinstance(structure, dict) or "name" not in structure:
                    continue
                tooltip_text = structure.get("description_fr", "")
                val = structure.get("value", "")
                example = structure.get("example", "")
                auth_values = structure.get(f"authorized_values_{lang}")
                label_text = structure.get(f"name_{lang}", structure.get("name", field_id))

                w = QtWidgets.QWidget()
                h_layout = QtWidgets.QHBoxLayout(w)
                h_layout.setContentsMargins(5, 3, 5, 3)
                h_layout.setSpacing(10)

                lbl = QtWidgets.QLabel(label_text)
                lbl.setStyleSheet("color: #ccc; font-weight: bold; min-width: 150px; border: none;")
                if tooltip_text:
                    lbl.setToolTip(tooltip_text)
                h_layout.addWidget(lbl, 1)

                if auth_values:
                    combo = QtWidgets.QComboBox()
                    combo.addItems([str(v) for v in auth_values])
                    if val:
                        idx = combo.findText(str(val))
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                    combo.currentTextChanged.connect(
                        lambda t, b="video_observation", f_id=field_id, w_in=combo: self._update_value(b, f_id, t, w_in)
                    )
                    h_layout.addWidget(combo, 2)
                else:
                    line = QtWidgets.QLineEdit()
                    line.setText(str(val) if val else "")
                    line.setPlaceholderText(str(example))
                    line.setStyleSheet(
                        "background-color: #2b2b2b; color: #ffaa00;" if val else
                        "background-color: #2b2b2b; color: #666;"
                    )
                    line.textChanged.connect(
                        lambda t, b="video_observation", f_id=field_id, w_in=line: self._update_value(b, f_id, t, w_in)
                    )
                    h_layout.addWidget(line, 2)

                form_layout.addWidget(w)

        form_layout.addStretch()
        container.layout().addWidget(form_widget)

    def action_compare_weather_web(self):
        lat, lon, raw_date = None, None, None

        for block_name, block_content in self._json_data.items():
            if isinstance(block_content, dict):
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
                                          f"The read date is: '{raw_date}'.\n\nPlease check the Date field.")
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

    def inject_weather_data(self, data=None):
        if "video_observation" in self._json_data:
            weather_sea_dict = {
                k: v for k, v in self._json_data["video_observation"].items()
                if k in self.weather_sea_keys
            }
            self._display_weather_data(weather_sea_dict)

    def _update_value(self, block_key: str, field_id: str, new_value: str, source_widget=None):
        if source_widget and isinstance(source_widget, QtWidgets.QLineEdit) and new_value:
            source_widget.setStyleSheet("background-color: #2b2b2b; color: #ffaa00;")

        if block_key in self._json_data and field_id in self._json_data[block_key]:
            self._json_data[block_key][field_id]["value"] = new_value

        if block_key in ["survey", "system"]:
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

    def refresh_statistics(self):
        if not hasattr(self, 'ax'):
            return
        video_count = self.video_model.rowCount()
        trash_count = self.trash_model.rowCount()
        self.ax.clear()
        if video_count + trash_count == 0:
            self.ax.pie([1], colors=['#3d3d3d'], wedgeprops=dict(width=0.25))
        else:
            self.ax.pie(
                [video_count, trash_count],
                labels=["Exploitable", "Trash"],
                autopct='%1.1f%%',
                colors=['#2778a2', '#ff5555'],
                startangle=90,
                textprops={'color': "white"},
                wedgeprops=dict(width=0.25, edgecolor='#1a1a1a')
            )
        self.ax.axis('equal')
        self.figure.tight_layout()
        self.canvas.draw()

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
        video_obs = self._json_data.get("video_observation", {})
        for json_key in ["events_deployment", "events_interesting_images", "events_animal"]:
            if json_key in video_obs and isinstance(video_obs[json_key], list) and video_obs[json_key]:
                for event_item in video_obs[json_key][0].get("values", []):
                    val_string = str(event_item.get("value", "")).lower().strip()
                    if any(kw in val_string for kw in ["whiteboard", "slate", "tableau blanc", "ardoise"]):
                        slate_frame = event_item.get("frame_number_start")
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

        import cv2 as _cv2
        frame_rgb = _cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        from PyQt6.QtGui import QImage, QPixmap
        q_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)

        dialog = QtWidgets.QDialog(self.widget)
        dialog.setWindowTitle(f"Slate - Frame {frame_number}")
        dialog.setMinimumSize(800, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        lbl = QtWidgets.QLabel()
        lbl.setPixmap(pixmap.scaled(780, 520, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                    QtCore.Qt.TransformationMode.SmoothTransformation))
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        btn = QtWidgets.QPushButton("Close")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn)
        dialog.show()
