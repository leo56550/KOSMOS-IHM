import os
import json

from PyQt6 import QtCore, QtGui, QtWidgets

from services.motor_service import get_motor_stable_timestamps
from services.video_service import check_stereo_status
from services.campaign_service import get_video_json_path, resolve_video_json_path
from views.widgets.embedded_player import EmbeddedVideoPlayer
from views.widgets.video_bar_delegate import VideoBarDelegate
from models.video_model import VideoFilterProxyModel
from services.thumbnail_service import THUMB_W, THUMB_H


class _ToggleFrame(QtWidgets.QFrame):
    """Bouton toggle QFrame+QLabel — texte toujours rendu correctement sous Windows 11/Qt6."""

    toggled = QtCore.pyqtSignal(bool)

    def __init__(self, choice: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self._choice = choice
        self._checked = checked
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self._lbl = QtWidgets.QLabel(choice)
        self._lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        # Transparent pour que les clics passent au QFrame parent
        self._lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._lbl)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool):
        self._checked = v

    def text(self) -> str:
        return self._choice

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self.toggled.emit(True)
        super().mousePressEvent(ev)

    def apply_style(self, colors: tuple, checked: bool | None = None):
        """Met à jour le style visuel selon l'état checked courant (ou forcé)."""
        if checked is not None:
            self._checked = checked
        bg_c, col_c, brd_c, hint_bg = colors
        if self._checked:
            self.setStyleSheet(
                f"QFrame {{ background-color: {bg_c}; border: 2px solid {brd_c}; border-radius: 5px; }}"
            )
            self._lbl.setStyleSheet(
                f"color: {col_c}; font-size: 13px; font-weight: bold;"
                " font-family: 'Segoe UI', sans-serif; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {hint_bg}; border: 1px solid #2a4a6a; border-radius: 5px; }}"
            )
            self._lbl.setStyleSheet(
                "color: #cce0f0; font-size: 13px; font-weight: bold;"
                " font-family: 'Segoe UI', sans-serif; background: transparent; border: none;"
            )


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
            self._bar_delegate = VideoBarDelegate(self.video_tree)
            self.video_tree.setItemDelegateForColumn(0, self._bar_delegate)

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

        # Restructure le panneau gauche : le tree et la section exploitabilité sont
        # actuellement dans un QVBoxLayout — impossible de traîner entre eux.
        # On intègre splitter_14 (exploitable+VALIDER) comme 2ème enfant de splitter_4
        # pour qu'une poignée draggable apparaisse entre le tree et le bloc exploitable.
        sp4 = self.page.findChild(QtWidgets.QSplitter, "splitter_4")
        sp14 = self.page.findChild(QtWidgets.QSplitter, "splitter_14")
        if sp4 and sp14 and sp14.parent() is not sp4:
            # Le minimumHeight=750 du .ui empêche le tree de rétrécir
            if self.video_tree:
                self.video_tree.setMinimumHeight(80)
            sp4.addWidget(sp14)            # sp14 devient enfant de sp4
            sp4.setStretchFactor(0, 1)    # le tree prend l'espace disponible
            sp4.setStretchFactor(1, 0)    # le bloc exploitable garde sa taille
            sp4.setSizes([450, 220])
            sp4.setHandleWidth(8)
            sp4.setStyleSheet(
                "QSplitter::handle { background-color: #2778A2; border-radius: 3px; }"
            )

        self._exploitable_btns: list[_ToggleFrame] = []
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

        # Stylesheet scopée à QFrame pour ne PAS cascader aux boutons enfants
        self.exploitable_container.setStyleSheet(
            "QFrame#exploitable_container { background-color: #0d1b2a; border: none; }"
        )

        # Widget interne qui porte tout le contenu — évite les conflits de layout
        self._panel_widget = QtWidgets.QWidget()
        self._panel_widget.setObjectName("panel_widget")
        # Scoper au nom de l'objet pour ne PAS cascader aux boutons enfants
        self._panel_widget.setStyleSheet("QWidget#panel_widget { background: transparent; }")
        outer.addWidget(self._panel_widget)

        layout = QtWidgets.QVBoxLayout(self._panel_widget)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)

        # ── Bandeau alerte ardoises manquantes ──────────────────────────
        self._ardoise_warning = QtWidgets.QLabel("")
        self._ardoise_warning.setWordWrap(True)
        self._ardoise_warning.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._ardoise_warning.setStyleSheet(
            "color: #ffcc00; background-color: #3a2800;"
            " border: 1px solid #cc8800; border-radius: 4px;"
            " padding: 6px 8px; font-size: 11px;"
            " font-family: 'Segoe UI', sans-serif;"
        )
        self._ardoise_warning.setVisible(False)
        layout.addWidget(self._ardoise_warning)

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
        self._choice_container.setObjectName("choice_container")
        self._choice_container.setStyleSheet(
            "QWidget#choice_container { background: transparent; }"
        )
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

        # ── Commentaires vidéo ──────────────────────────────────────────
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: #1e3448; border: none; max-height: 1px;")
        layout.addWidget(sep2)

        lbl_comment = QtWidgets.QLabel(self.translate("Commentaires vidéo", "Video comments"))
        lbl_comment.setStyleSheet(
            "color: #F2BFB4; font-size: 11px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
        )
        layout.addWidget(lbl_comment)

        self._comment_edit = QtWidgets.QPlainTextEdit()
        self._comment_edit.setPlaceholderText(
            self.translate("Observations sur la vidéo…", "Video observations…")
        )
        self._comment_edit.setMaximumHeight(80)
        self._comment_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #162433; color: #F2BFB4;"
            " border: 1px solid #2a4057; border-radius: 4px;"
            " padding: 4px 6px; font-family: 'Segoe UI', sans-serif; font-size: 11px; }"
        )
        self._comment_edit.textChanged.connect(self._on_comment_changed)
        layout.addWidget(self._comment_edit)
        layout.addStretch()

    def refresh_ardoise_warning(self):
        """Affiche un bandeau si des vidéos exploitables (oui) n'ont pas d'ardoise saisie."""
        if not hasattr(self, '_ardoise_warning') or self.video_model is None:
            return
        missing = []
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
            obs = data.get("video_observation", {})
            expl = obs.get("exploitable", {})
            val = expl.get("value", "") if isinstance(expl, dict) else str(expl)
            if str(val).strip().lower() not in ("oui", "yes"):
                continue
            events_deploy = obs.get("events_deployment", []) or []
            values = events_deploy[0].get("values", []) if events_deploy else []
            has_ardoise = any(
                str(ev.get("value", "")).lower() in ("ardoise", "slate")
                for ev in values
            )
            if not has_ardoise:
                missing.append(item.text())

        if missing:
            names = "\n".join(f"  • {n}" for n in missing)
            self._ardoise_warning.setText(
                f"⚠ Ardoise manquante pour :\n{names}"
            )
            self._ardoise_warning.setVisible(True)
        else:
            self._ardoise_warning.setVisible(False)

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

    def _rebuild_choice_buttons(self, choices: list[str], current: str):
        """Reconstruit les _ToggleFrame en grille 2 colonnes selon les valeurs autorisées."""
        # Supprime les anciens widgets
        while self._choice_layout.count():
            item = self._choice_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._exploitable_btns.clear()

        self._exploitable_choices = choices
        self._rebuilding_buttons = True

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(5)
        grid.setContentsMargins(0, 0, 0, 0)

        for i, choice in enumerate(choices):
            is_checked = (choice == current)
            colors = self._EXPLOITABLE_COLORS.get(
                choice.lower().strip(), ("#1a3a4a", "#4a9fcf", "#2778A2", "#101e28")
            )
            frame = _ToggleFrame(choice, is_checked)
            frame.apply_style(colors)
            frame.toggled.connect(
                lambda _, c=choice, f=frame: self._on_frame_toggled(c, f)
            )
            self._exploitable_btns.append(frame)
            grid.addWidget(frame, i // 2, i % 2)

        grid_widget = QtWidgets.QWidget()
        grid_widget.setObjectName("exploitable_grid")
        grid_widget.setStyleSheet("QWidget#exploitable_grid { background: transparent; }")
        grid_widget.setLayout(grid)
        self._choice_layout.addWidget(grid_widget)
        self._rebuilding_buttons = False

        # Hauteur minimale = juste assez pour afficher les boutons sans scroll
        n_rows = (len(choices) + 1) // 2
        min_h = 50 + n_rows * (40 + 6)
        self.exploitable_container.setMinimumHeight(min_h)
        # Expanding vertical permet au splitter parent de l'étirer vers le haut
        self.exploitable_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.exploitable_container.updateGeometry()

        self._update_status_badge(current)

    def _on_frame_toggled(self, choice: str, clicked_frame: _ToggleFrame):
        """Exclusion mutuelle + persistance quand un _ToggleFrame est cliqué."""
        if getattr(self, '_rebuilding_buttons', False):
            return
        for frame in self._exploitable_btns:
            new_state = (frame is clicked_frame)
            if frame.isChecked() != new_state:
                frame.setChecked(new_state)
                colors = self._EXPLOITABLE_COLORS.get(
                    frame.text().lower().strip(), ("#1a3a4a", "#4a9fcf", "#2778A2", "#101e28")
                )
                frame.apply_style(colors)
        self._update_status_badge(choice)
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

    def _on_comment_changed(self):
        """Persiste le commentaire vidéo dans le JSON dès que le texte change (avec debounce léger)."""
        if not hasattr(self, '_comment_edit') or not self.current_json_path:
            return
        if not hasattr(self, '_comment_timer'):
            self._comment_timer = QtCore.QTimer()
            self._comment_timer.setSingleShot(True)
            self._comment_timer.setInterval(800)
            self._comment_timer.timeout.connect(self._flush_comment)
        self._comment_timer.start()

    def _flush_comment(self):
        """Écrit derush_comment dans le JSON."""
        if not self.current_json_path or not os.path.isfile(self.current_json_path):
            return
        text = self._comment_edit.toPlainText().strip() if hasattr(self, '_comment_edit') else ""
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            vob = data.setdefault("video_observation", {})
            if "derush_comment" in vob and isinstance(vob["derush_comment"], dict):
                vob["derush_comment"]["value"] = text or None
            else:
                vob["derush_comment"] = {"value": text or None}
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ValidationCtrl] erreur sauvegarde commentaire : {e}")

    def set_working_dir(self, path: str):
        self._working_dir = path
        if hasattr(self, '_bar_delegate'):
            self._bar_delegate.set_working_dir(path)

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
        self.refresh_ardoise_warning()

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
            vob = data.get("video_observation", {})
            field = vob.get("exploitable", {})
            lang_key = "authorized_values_fr" if self.current_language == 'fr' else "authorized_values_en"
            choices = field.get(lang_key, [])
            current = field.get("value", "") or ""
            self._rebuild_choice_buttons(choices, current)

            # Charge le commentaire vidéo
            if hasattr(self, '_comment_edit'):
                comment_entry = vob.get("derush_comment", {})
                comment = (comment_entry.get("value", "") if isinstance(comment_entry, dict)
                           else comment_entry) or ""
                self._comment_edit.blockSignals(True)
                self._comment_edit.setPlainText(str(comment))
                self._comment_edit.blockSignals(False)
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

            self.refresh_ardoise_warning()

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
        """Met à jour la couleur d'un item selon son statut exploitabilité — préserve les badges de type."""
        # Ne pas écraser la couleur de badge (stéréo/segments)
        if item.data(QtCore.Qt.ItemDataRole.UserRole + 1):
            return
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
        color = "#4CAF50" if is_processed else "#b0bec5"
        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))

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

        vob_tmp = data.get("video_observation", {})
        existing_num = (vob_tmp.get("point_name", {}).get("value")
                        or vob_tmp.get("station_number", {}).get("value") or "")

        # Dialog numéro du point
        num_str, ok = QtWidgets.QInputDialog.getText(
            self.page,
            self.translate("N° du point", "Point number"),
            self.translate("Numéro du point :", "Point number:"),
            text=str(existing_num),
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

        # Écriture JSON unique : ardoise + station_number si saisi
        try:
            obs = data.setdefault("video_observation", {})

            # Événement ardoise
            deploy = obs.setdefault("events_deployment", [{"authorized_values_fr": [], "values": []}])
            if not deploy:
                deploy.append({"authorized_values_fr": [], "values": []})
            # Calcul du numéro de frame depuis la position courante
            frame_num = None
            if self.current_video_path and os.path.exists(self.current_video_path):
                try:
                    import cv2 as _cv2
                    _cap = _cv2.VideoCapture(self.current_video_path)
                    _fps = _cap.get(_cv2.CAP_PROP_FPS) or 25.0
                    _cap.release()
                    frame_num = int(pos_ms * _fps / 1000)
                except Exception:
                    pass

            deploy[0].setdefault("values", []).append({
                "event_id": event_uid,
                "time_code_start": time_str,
                "time_code_end": time_str,
                "frame_number_start": frame_num,
                "frame_number_end": frame_num,
                "description_fr": None,
                "description_en": None,
                "value": value,
                "comment": "",
            })

            # N° du point → 4 chiffres zero-padded, écrit dans point_name (+ compat station_number)
            if ok and num_str.strip():
                raw = num_str.strip()
                try:
                    station_num = f"{int(raw):04d}"
                except ValueError:
                    station_num = raw.zfill(4)[:4]
                obs.setdefault("point_name", {})["value"] = station_num
                obs.setdefault("station_number", {})["value"] = station_num

            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            # Feedback visuel bref + flash ardoise
            label = f"✓ N°{station_num}" if (ok and num_str.strip()) else "✓ Ardoise"
            self.player.btn_ardoise.setText(label)
            QtCore.QTimer.singleShot(2000, lambda: self.player.btn_ardoise.setText("SAISIR ARDOISE"))
            self._flash_ardoise()

            if self._on_qualification_changed:
                self._on_qualification_changed()
            self.refresh_ardoise_warning()
        except Exception as e:
            print(f"[VALIDATION] Erreur sauvegarde ardoise/codeObs : {e}")

    def _flash_ardoise(self):
        """Flash blanc sur le player vidéo — effet déclencheur d'appareil photo."""
        target = getattr(self.player, 'video_container', self.player)
        flash = QtWidgets.QWidget(target)
        flash.setGeometry(target.rect())
        flash.setStyleSheet("background: white; border: none;")
        flash.raise_()
        flash.show()

        effect = QtWidgets.QGraphicsOpacityEffect(flash)
        flash.setGraphicsEffect(effect)

        anim = QtCore.QPropertyAnimation(effect, b"opacity", flash)
        anim.setDuration(350)
        anim.setStartValue(0.9)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
        anim.finished.connect(flash.deleteLater)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
