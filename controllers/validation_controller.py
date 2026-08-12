import os
import json

from PyQt6 import QtCore, QtGui, QtWidgets

from services.motor_service import get_motor_stable_timestamps
from services.video_service import check_stereo_status
from services.campaign_service import get_video_json_path, resolve_video_json_path
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
        self._working_dir = ""

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
            self.player.btn_ardoise.clicked.connect(self._saisir_ardoise)

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
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)

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

    # Couleurs par valeur d'exploitabilité (bg_checked, color_checked, border_checked, hint_bg)
    _EXPLOITABLE_COLORS = {
        "oui":       ("#1a4a2e", "#4CAF50", "#4CAF50", "#0f2a1a"),
        "yes":       ("#1a4a2e", "#4CAF50", "#4CAF50", "#0f2a1a"),
        "non":       ("#4a1a1a", "#ff6060", "#D94F38", "#2a0f0f"),
        "no":        ("#4a1a1a", "#ff6060", "#D94F38", "#2a0f0f"),
        "partielle": ("#4a3a0e", "#E8C838", "#E8A838", "#2a200a"),
        "partial":   ("#4a3a0e", "#E8C838", "#E8A838", "#2a200a"),
        "?":         ("#2a2a2a", "#aaaaaa", "#777777", "#1a1a1a"),
    }

    def _exploitable_btn_style(self, choice: str) -> str:
        """Retourne le stylesheet d'un bouton toggle avec couleur spécifique à sa valeur."""
        key = choice.lower().strip()
        bg_c, col_c, brd_c, hint_bg = self._EXPLOITABLE_COLORS.get(
            key, ("#1a3a4a", "#4a9fcf", "#2778A2", "#101e28")
        )
        return (
            "QPushButton {"
            f"  background-color: {hint_bg};"
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
            f"QPushButton:checked {{"
            f"  background-color: {bg_c};"
            f"  color: {col_c};"
            f"  border: 2px solid {brd_c};"
            "}"
        )

    def _rebuild_choice_buttons(self, choices: list[str], current: str):
        """Reconstruit les boutons toggle en grille 2 colonnes selon les valeurs autorisées."""
        for btn in self._exploitable_btn_group.buttons():
            self._exploitable_btn_group.removeButton(btn)
        while self._choice_layout.count():
            item = self._choice_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._exploitable_choices = choices
        self._rebuilding_buttons = True

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
            btn.setStyleSheet(self._exploitable_btn_style(choice))
            self._exploitable_btn_group.addButton(btn)
            grid.addWidget(btn, i // 2, i % 2)
            btn.toggled.connect(lambda checked, c=choice: self._on_choice_toggled(checked, c))

        # Wrapper pour insérer le QGridLayout dans le QVBoxLayout parent
        grid_widget = QtWidgets.QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid_widget.setLayout(grid)
        self._choice_layout.addWidget(grid_widget)
        self._rebuilding_buttons = False  # autorise à nouveau on_exploitable_changed

        # Ajuste la hauteur minimale du container selon le nb de lignes
        n_rows = (len(choices) + 1) // 2
        btn_h = 28   # hauteur estimée par bouton
        needed = 18 + 2 + n_rows * (btn_h + 5) + 24 + 16   # titre + sep + grille + badge + marges
        self.exploitable_container.setMinimumHeight(needed)
        self.exploitable_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        self.exploitable_container.updateGeometry()

        self._update_status_badge(current)

    def _on_choice_toggled(self, checked: bool, choice: str):
        """Déclenché quand un bouton toggle change d'état."""
        if checked and not getattr(self, '_rebuilding_buttons', False):
            self.on_exploitable_changed(choice)

    def _update_status_badge(self, current: str):
        """Met à jour le badge de statut sous les boutons avec la couleur de la valeur."""
        if not hasattr(self, '_status_badge'):
            return
        if current and str(current).strip():
            key = current.lower().strip()
            _bg_c, col_c, brd_c, _hint = self._EXPLOITABLE_COLORS.get(
                key, ("#1a3a4a", "#4a9fcf", "#2778A2", "#101e28")
            )
            # Badge : bg légèrement teinté de la couleur de la valeur
            bg_badge = _hint if _hint else "#0d1b0f"
            self._status_badge.setText(f"✓  {current}")
            self._status_badge.setStyleSheet(
                f"color: {col_c}; font-size: 11px; font-weight: bold;"
                " font-family: 'Segoe UI', sans-serif;"
                f" background: {bg_badge}; border: 1px solid {brd_c};"
                " border-radius: 5px; padding: 4px 8px;"
            )
        else:
            self._status_badge.setText(self.translate("Non renseigné", "Not set"))
            self._status_badge.setStyleSheet(
                "color: #3a5568; font-size: 10px; font-family: 'Segoe UI', sans-serif;"
                " background: transparent; border: none;"
            )

    def set_working_dir(self, path: str):
        self._working_dir = path

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
        self.current_json_path = resolve_video_json_path(self._working_dir, selected_video_path)
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

        self.player.btn_ardoise.setEnabled(True)
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
            print(f"[ValidationCtrl] on_exploitable_changed ignoré — path={self.current_json_path!r} text={text!r}")
            return
        print(f"[ValidationCtrl] Sauvegarde exploitabilité '{text}' → {self.current_json_path}")
        try:
            if not os.path.isfile(self.current_json_path):
                print(f"[ValidationCtrl] ERREUR — fichier JSON introuvable : {self.current_json_path}")
                return
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if "video_observation" not in data:
                data["video_observation"] = {}
            video_obs = data["video_observation"]
            if "exploitable" not in video_obs:
                video_obs["exploitable"] = {}
            video_obs["exploitable"]["value"] = text
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[ValidationCtrl] ✓ exploitable='{text}' écrit dans {self.current_json_path}")

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
        except Exception as e:
            print(f"[ValidationCtrl] EXCEPTION dans on_exploitable_changed : {e!r}")
            import traceback; traceback.print_exc()

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

    def _saisir_ardoise(self):
        """Capture un événement ardoise et ouvre un champ pour saisir le code station."""
        if not hasattr(self, 'player') or self.player is None:
            return
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return

        import uuid
        pos_ms = self.player.timeline.get_current_position() if hasattr(self.player, 'timeline') else 0
        time_str = self.player.timeline._format_ms(pos_ms) if hasattr(self.player, 'timeline') else "00:00:00"
        value = "ardoise" if self.current_language == 'fr' else "slate"
        event_uid = str(uuid.uuid4())

        # Lecture du JSON pour pré-remplir le code station
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[VALIDATION] Lecture JSON échouée : {e}")
            return

        existing_code = (data.get("video_observation", {})
                             .get("codeObs", {})
                             .get("value") or "")

        # Dialog code station
        code, ok = QtWidgets.QInputDialog.getText(
            self.page,
            self.translate("Code station", "Station code"),
            self.translate("Code station (ex : CC190001) :", "Station code (e.g. CC190001):"),
            text=existing_code,
        )

        # Ajoute visuellement dans la timeline (indépendamment du dialog)
        if hasattr(self.player, 'timeline'):
            new_evt = {
                "start": pos_ms, "end": pos_ms,
                "title": f"Pic: {value}",
                "type": "custom_event",
                "zone": 0,
                "single_frame": True,
                "comment": "",
                "_json_key": "events_deployment",
                "_event_uid": event_uid,
            }
            self.player.timeline.events.append(new_evt)
            self.player.timeline.update()

        # Écriture JSON unique : ardoise + codeObs si saisi
        try:
            obs = data.setdefault("video_observation", {})

            # Événement ardoise
            deploy = obs.setdefault("events_deployment", [{"authorized_values_fr": [], "values": []}])
            if not deploy:
                deploy.append({"authorized_values_fr": [], "values": []})
            deploy[0].setdefault("values", []).append({
                "event_id": event_uid,
                "time_code_start": time_str,
                "time_code_end": time_str,
                "frame_number_start": None,
                "frame_number_end": None,
                "description_fr": None,
                "description_en": None,
                "value": value,
                "comment": "",
            })

            # Code station
            if ok and code.strip():
                code = code.strip()
                obs.setdefault("codeObs", {})["value"] = code
                # point_name = 4 derniers caractères par convention, si vide
                if not obs.get("point_name", {}).get("value"):
                    obs.setdefault("point_name", {})["value"] = code[-4:] if len(code) >= 4 else code

            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            # Feedback visuel bref
            label = f"✓ {code}" if (ok and code.strip()) else "✓ Ardoise"
            self.player.btn_ardoise.setText(label)
            QtCore.QTimer.singleShot(2000, lambda: self.player.btn_ardoise.setText("SAISIR ARDOISE"))

            if self._on_qualification_changed:
                self._on_qualification_changed()
        except Exception as e:
            print(f"[VALIDATION] Erreur sauvegarde ardoise/codeObs : {e}")
