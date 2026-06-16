import os
import json

from PyQt6 import QtCore, QtGui, QtWidgets

from services.motor_service import get_motor_stable_timestamps
from services.video_service import check_stereo_status
from services.campaign_service import get_video_json_path
from views.widgets.embedded_player import EmbeddedVideoPlayer
from models.video_model import VideoFilterProxyModel


class ValidationController:
    """Contrôleur de la page Validation : lecture vidéo et saisie de l'exploitabilité."""

    def __init__(self, page_widget: QtWidgets.QWidget, shared_model: QtGui.QStandardItemModel,
                 on_video_focused=None):
        """Initialise le player embarqué, l'arbre vidéo et le combo exploitabilité."""
        self.page = page_widget
        self.video_model = shared_model
        self._on_video_focused = on_video_focused
        self.current_language = 'en'
        self.current_json_path = None
        self.current_video_path = None

        self.video_tree = self.page.findChild(QtWidgets.QTreeView, "tree_video_validation")
        self.player_container = self.page.findChild(QtWidgets.QFrame, "lecteur_timeline_container")
        self.exploitable_container = self.page.findChild(QtWidgets.QFrame, "exploitable_container")

        left_panel = self.page.findChild(QtWidgets.QFrame, "frame_3")
        if left_panel:
            left_panel.setMinimumWidth(150)
            left_panel.setMaximumWidth(16777215)

        self.proxy_model = VideoFilterProxyModel(self.page)
        self.proxy_model.setSourceModel(self.video_model)

        if self.video_tree:
            self.video_tree.setModel(self.proxy_model)
            self.video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.video_tree.clicked.connect(self.on_video_selected)

        if self.player_container:
            layout = self.player_container.layout() or QtWidgets.QVBoxLayout(self.player_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self.player = EmbeddedVideoPlayer(parent=self.player_container)
            layout.addWidget(self.player)
            self.player_container.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
            )
            self.player.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
            )

        main_splitter = self.page.findChild(QtWidgets.QSplitter, "splitter_3")
        if main_splitter:
            main_splitter.setStretchFactor(0, 0)
            main_splitter.setStretchFactor(1, 1)
            main_splitter.setCollapsible(1, False)

        if self.exploitable_container:
            layout = self.exploitable_container.layout() or QtWidgets.QVBoxLayout(self.exploitable_container)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

            self.lbl_exploitable = QtWidgets.QLabel("Video Exploitable? ")
            self.lbl_exploitable.setStyleSheet("color: white; font-weight: bold; border: none;")
            layout.addWidget(self.lbl_exploitable)

            self.combo_exploitable = QtWidgets.QComboBox()
            self.combo_exploitable.setStyleSheet("""
                QComboBox { background-color: #20415d; color: white; border: 1px solid #ababab;
                            border-radius: 4px; padding: 5px; min-width: 150px; }
                QComboBox QAbstractItemView { background-color: #20415d; color: white;
                                             selection-background-color: #2778a2; }
            """)
            layout.addWidget(self.combo_exploitable)
            self.combo_exploitable.currentTextChanged.connect(self.on_exploitable_changed)

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Met à jour la langue et rafraîchit les libellés."""
        self.current_language = language
        if hasattr(self, 'player'):
            self.player.set_language(language)
        if hasattr(self, 'lbl_exploitable'):
            self.lbl_exploitable.setText(self.translate("Vidéo Exploitable ? ", "Video Exploitable?"))
        if self.current_json_path and os.path.exists(self.current_json_path):
            self.refresh_combobox_values()

    def load_campaign_videos(self, model: QtGui.QStandardItemModel):
        """Remplace le modèle source du proxy après un changement de campagne."""
        self.video_model = model
        self.proxy_model.setSourceModel(self.video_model)

    def select_video_by_name(self, video_name: str):
        """Sélectionne une vidéo dans l'arbre depuis son nom (appel depuis la carte)."""
        if not self.video_tree or not self.video_model:
            return
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and item.text() == video_name:
                source_index = self.video_model.indexFromItem(item)
                proxy_index = self.proxy_model.mapFromSource(source_index)
                if not proxy_index.isValid():
                    return
                self.video_tree.selectionModel().setCurrentIndex(
                    proxy_index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect |
                    QtCore.QItemSelectionModel.SelectionFlag.Rows
                )
                self.video_tree.scrollTo(proxy_index)
                self.on_video_selected(proxy_index)
                break

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Charge la vidéo sélectionnée, les événements moteur et la télémétrie CSV."""
        source_index = self.proxy_model.mapToSource(index)
        item = self.video_model.itemFromIndex(source_index.siblingAtColumn(0))
        if not item:
            return

        selected_video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        video_dir = os.path.dirname(selected_video_path)
        is_stereo, video_to_load = check_stereo_status(selected_video_path)

        self.current_video_path = selected_video_path
        self.current_json_path = get_video_json_path(selected_video_path)
        self.refresh_combobox_values()
        if self._on_video_focused:
            self._on_video_focused(item.text())

        detected_events = []
        csv_system = os.path.join(video_dir, "systemEvent.csv")
        if os.path.exists(csv_system):
            try:
                engine_data = get_motor_stable_timestamps(csv_system, delay=6.0)
                for entry in engine_data:
                    start_ms = int(entry["timestamp"] * 1000)
                    detected_events.append({
                        "start": start_ms, "end": start_ms + 3000,
                        "title": f"Rot #{entry['rotation_index']} ({entry['angle']}°)",
                        "type": entry["type"]
                    })
            except Exception:
                pass

        csv_telemetry = selected_video_path.replace(".mp4", ".csv")
        if os.path.exists(csv_telemetry):
            self.player.load_dynamic_metadata(csv_telemetry)
        else:
            self.player.df_telemetry = None
            self.player.btn_telemetry.setEnabled(False)
            self.player.btn_telemetry.setChecked(False)

        self.player.load_video_and_events(video_to_load, detected_events, is_stereo=is_stereo)

    def refresh_combobox_values(self):
        """Recharge les valeurs autorisées du combo exploitabilité depuis le JSON."""
        if not hasattr(self, 'combo_exploitable') or not self.current_json_path:
            return
        if os.path.exists(self.current_json_path):
            try:
                self.combo_exploitable.blockSignals(True)
                self.combo_exploitable.clear()
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if "video_observation" in data and "exploitable" in data["video_observation"]:
                    field = data["video_observation"]["exploitable"]
                    lang_key = "authorized_values_fr" if self.current_language == 'fr' else "authorized_values_en"
                    self.combo_exploitable.addItems(field.get(lang_key, []))
                    self.combo_exploitable.setCurrentText(field.get("value", ""))
            except Exception:
                pass
            finally:
                self.combo_exploitable.blockSignals(False)

    def on_exploitable_changed(self, text: str):
        """Persiste la valeur d'exploitabilité dans le JSON et met à jour l'icône de l'item."""
        if not self.current_json_path or not text:
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if "video_observation" in data and "exploitable" in data["video_observation"]:
                data["video_observation"]["exploitable"]["value"] = text
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                selected = self.video_tree.selectionModel().selectedRows()
                if selected:
                    source_index = self.proxy_model.mapToSource(selected[0])
                    item = self.video_model.itemFromIndex(source_index.siblingAtColumn(0))
                    if item:
                        self.refresh_item_indicator(item, self.current_video_path)
        except Exception:
            pass

    def refresh_item_indicator(self, item, video_path):
        """Met à jour l'icône et la couleur d'un item selon son statut exploitabilité."""
        json_path = get_video_json_path(video_path)
        is_processed = False
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                val = data.get("video_observation", {}).get("exploitable", {}).get("value")
                if val and str(val).strip():
                    is_processed = True
            except Exception:
                pass

        if is_processed:
            item.setIcon(self.page.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton))
            item.setForeground(QtGui.QBrush(QtGui.QColor("#4CAF50")))
        else:
            item.setIcon(self.page.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
            item.setForeground(QtGui.QBrush(QtGui.QColor("white")))

    def initialize_tree_indicators(self):
        """Initialise les icônes de tout l'arbre au chargement d'une campagne."""
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    self.refresh_item_indicator(item, path)
