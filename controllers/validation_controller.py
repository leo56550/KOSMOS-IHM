import os
import json

from PyQt6 import QtCore, QtGui, QtWidgets

from services.motor_service import get_motor_stable_timestamps
from services.video_service import check_stereo_status
from services.campaign_service import get_video_json_path
from views.widgets.embedded_player import EmbeddedVideoPlayer
from models.video_model import VideoFilterProxyModel
from services.thumbnail_service import THUMB_W, THUMB_H


class ValidationController:
    """Contrôleur de la page Validation : lecture vidéo et saisie de l'exploitabilité."""

    def __init__(self, page_widget: QtWidgets.QWidget, shared_model: QtGui.QStandardItemModel,
                 on_video_focused=None, on_qualification_changed=None):
        """Initialise le player embarqué, l'arbre vidéo et le combo exploitabilité."""
        self.page = page_widget
        self.video_model = shared_model
        self._on_video_focused = on_video_focused
        self._on_qualification_changed = on_qualification_changed
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
            self.video_tree.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))
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

        self._exploitable_btn_group = QtWidgets.QButtonGroup()
        self._exploitable_btn_group.setExclusive(True)
        self._exploitable_choices: list[str] = []

        if self.exploitable_container:
            self._build_exploitable_panel()

    # ── Panel exploitabilité ──────────────────────────────────────────────────

    def _build_exploitable_panel(self):
        """Construit le panel d'exploitabilité avec un design carte + boutons toggle."""
        # Vide le layout existant avec setParent(None) (immédiat, pas deleteLater)
        outer = self.exploitable_container.layout()
        if not outer:
            outer = QtWidgets.QVBoxLayout(self.exploitable_container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        while outer.count():
            item = outer.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)   # suppression immédiate du parent → invisible de suite

        # Applique le style au container
        self.exploitable_container.setStyleSheet(
            "background-color: #0d1b2a; border: none;"
        )

        # Widget interne qui porte tout le contenu — évite les conflits de layout
        self._panel_widget = QtWidgets.QWidget()
        self._panel_widget.setStyleSheet("background: transparent;")
        outer.addWidget(self._panel_widget)

        layout = QtWidgets.QVBoxLayout(self._panel_widget)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(10)

        # Titre
        self.lbl_exploitable = QtWidgets.QLabel(
            self.translate("Exploitabilité vidéo", "Video Exploitability")
        )
        self.lbl_exploitable.setStyleSheet(
            "color: #F2BFB4; font-size: 12px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
            " letter-spacing: 0.3px;"
        )
        layout.addWidget(self.lbl_exploitable)

        # Séparateur
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #1e3448; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # Zone des boutons toggle (remplie dynamiquement par _rebuild_choice_buttons)
        self._choice_container = QtWidgets.QWidget()
        self._choice_container.setStyleSheet("background: transparent;")
        self._choice_layout = QtWidgets.QVBoxLayout(self._choice_container)
        self._choice_layout.setContentsMargins(0, 4, 0, 4)
        self._choice_layout.setSpacing(6)
        layout.addWidget(self._choice_container)

        # Indicateur de statut (sélection courante)
        self._status_badge = QtWidgets.QLabel(self.translate("Aucune sélection", "No selection"))
        self._status_badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._status_badge.setStyleSheet(
            "color: #3a5568; font-size: 10px; font-family: 'Segoe UI', sans-serif;"
        )
        layout.addWidget(self._status_badge)
        layout.addStretch()

    def _rebuild_choice_buttons(self, choices: list[str], current: str):
        """Reconstruit les boutons toggle en grille 2 colonnes selon les valeurs autorisées."""
        # Nettoie les anciens boutons
        for btn in self._exploitable_btn_group.buttons():
            self._exploitable_btn_group.removeButton(btn)
        while self._choice_layout.count():
            item = self._choice_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._exploitable_choices = choices

        _BTN_BASE = (
            "QPushButton {"
            "  background-color: #162433;"
            "  color: #7a9ab8;"
            "  font-family: 'Segoe UI', sans-serif;"
            "  font-size: 11px;"
            "  font-weight: bold;"
            "  border: 1px solid #1e3448;"
            "  border-radius: 5px;"
            "  padding: 5px 8px;"
            "  text-align: center;"
            "}"
            "QPushButton:hover {"
            "  background-color: #1e3448;"
            "  color: #d4e8f5;"
            "  border-color: #2778A2;"
            "}"
            "QPushButton:checked {"
            "  background-color: #1a4a2e;"
            "  color: #4CAF50;"
            "  border: 1px solid #4CAF50;"
            "}"
        )

        # Grille 2 colonnes pour tenir dans la hauteur disponible
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(5)
        grid.setContentsMargins(0, 0, 0, 0)

        for i, choice in enumerate(choices):
            btn = QtWidgets.QPushButton(choice)
            btn.setCheckable(True)
            btn.setChecked(choice == current)
            btn.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed
            )
            btn.setStyleSheet(_BTN_BASE)
            self._exploitable_btn_group.addButton(btn)
            grid.addWidget(btn, i // 2, i % 2)
            btn.toggled.connect(lambda checked, c=choice: self._on_choice_toggled(checked, c))

        # Wrapper pour insérer le QGridLayout dans le QVBoxLayout parent
        grid_widget = QtWidgets.QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid_widget.setLayout(grid)
        self._choice_layout.addWidget(grid_widget)

        # Ajuste la hauteur minimale du container selon le nb de lignes
        n_rows = (len(choices) + 1) // 2
        btn_h = 32   # hauteur estimée par bouton
        needed = 20 + 2 + n_rows * (btn_h + 5) + 30 + 24   # titre + sep + grille + badge + marges
        self.exploitable_container.setMinimumHeight(needed)
        self.exploitable_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        self.exploitable_container.updateGeometry()

        self._update_status_badge(current)

    def _on_choice_toggled(self, checked: bool, choice: str):
        """Déclenché quand un bouton toggle change d'état."""
        if checked:
            self.on_exploitable_changed(choice)

    def _update_status_badge(self, current: str):
        """Met à jour le badge de statut sous les boutons."""
        if not hasattr(self, '_status_badge'):
            return
        if current and str(current).strip():
            self._status_badge.setText(f"✓  {current}")
            self._status_badge.setStyleSheet(
                "color: #4CAF50; font-size: 11px; font-weight: bold;"
                " font-family: 'Segoe UI', sans-serif;"
                " background: #0d1b0f; border: 1px solid #2a6a2a;"
                " border-radius: 5px; padding: 4px 8px;"
            )
        else:
            self._status_badge.setText(self.translate("Non renseigné", "Not set"))
            self._status_badge.setStyleSheet(
                "color: #3a5568; font-size: 10px; font-family: 'Segoe UI', sans-serif;"
                " background: transparent; border: none;"
            )

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        """Met à jour la langue et rafraîchit les libellés."""
        self.current_language = language
        if hasattr(self, 'player'):
            self.player.set_language(language)
        if hasattr(self, 'lbl_exploitable'):
            self.lbl_exploitable.setText(
                self.translate("Exploitabilité vidéo", "Video Exploitability")
            )
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
        """Recharge les valeurs autorisées et reconstruit les boutons toggle depuis le JSON."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        if not hasattr(self, '_choice_container'):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            field = data.get("video_observation", {}).get("exploitable", {})
            lang_key = "authorized_values_fr" if self.current_language == 'fr' else "authorized_values_en"
            choices = field.get(lang_key, [])
            current = field.get("value", "") or ""
            self._rebuild_choice_buttons(choices, current)
        except Exception:
            pass

    def on_exploitable_changed(self, text: str):
        """Persiste la valeur d'exploitabilité dans le JSON et met à jour les indicateurs."""
        if not self.current_json_path or not text:
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if "video_observation" in data and "exploitable" in data["video_observation"]:
                data["video_observation"]["exploitable"]["value"] = text
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                self._update_status_badge(text)

                if self._on_qualification_changed:
                    self._on_qualification_changed()

                if self.video_tree:
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
            item.setForeground(QtGui.QBrush(QtGui.QColor("#4CAF50")))
        else:
            item.setForeground(QtGui.QBrush(QtGui.QColor("white")))

    def initialize_tree_indicators(self):
        """Initialise les icônes de tout l'arbre au chargement d'une campagne."""
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if path:
                    self.refresh_item_indicator(item, path)
