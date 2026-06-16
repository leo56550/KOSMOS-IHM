from PyQt6 import QtWidgets, QtCore
import json

from services.campaign_service import get_campaign_json_data, get_video_json_path
from services.video_service import check_stereo_status
from services.weather_service import WeatherWorker
from views.dialogs.sftp_dialog import SftpDialog
from controllers.accueil_controller import AccueilController
from controllers.qualif_controller import QualifController
from controllers.validation_controller import ValidationController
from controllers.evenements_controller import EvenementsController
from controllers.metadonnees_controller import MetadonneesController
from controllers.extraction_controller import ExtractionController
import os


class AProposController:
    """Contrôleur minimal de la page À propos (pas de logique métier)."""

    def __init__(self, widget, *args, **kwargs):
        self.widget = widget

    def set_language(self, language: str):
        """Stub de traduction (page statique)."""
        pass


class AppController:
    """Orchestrates navigation, campaign lifecycle, and page controllers."""

    def __init__(self, window):
        """Instancie tous les controllers de page, connecte les signaux de navigation et les boutons workflow."""
        self.window = window
        self.qualification_completed = False
        self.validation_completed = False
        self._current_campaign_name: str = ""
        self._current_derusher_name: str = ""
        self._current_campaign_mode: str = ""  # "MONO" | "STEREO" | ""

        # Instantiate page controllers
        self.accueil_ctrl = AccueilController(
            window.page_accueil,
            self.handle_campaign_opening
        )
        self.qualif_ctrl = QualifController(
            window.page_qualification, parent=window,
            on_before_delete=self._release_file_in_all_players
        )
        self.validation_ctrl = ValidationController(
            window.page_validation, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
            on_qualification_changed=self.refresh_status_bar,
        )
        self.evenements_ctrl = EvenementsController(
            window.page_evenements, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
        )
        self.metadonnees_ctrl = MetadonneesController(
            window.page_metadonnees,
            self.qualif_ctrl.video_model,
            self.qualif_ctrl.trash_model,
            on_metadata_saved=self._on_metadata_saved,
            on_video_selected=self._on_meta_video_selected,
        )
        self.apropos_ctrl = AProposController(window.page_apropos)
        self.extraction_ctrl = ExtractionController(
            window.page_extraction, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
        )

        self.page_controllers = [
            self.accueil_ctrl, self.qualif_ctrl, self.validation_ctrl,
            self.evenements_ctrl, self.metadonnees_ctrl, self.apropos_ctrl, self.extraction_ctrl
        ]

        # Rafraîchir la barre de statut quand le modèle vidéo change (suppression/ajout externe)
        self.qualif_ctrl.video_model.rowsInserted.connect(self.refresh_status_bar)
        self.qualif_ctrl.video_model.rowsRemoved.connect(self.refresh_status_bar)

        # Carte : propager les clics sur les marqueurs vers tous les controllers
        bridge = self.qualif_ctrl.bridge
        bridge.videoSelected.connect(self.validation_ctrl.select_video_by_name)
        bridge.videoSelected.connect(self.evenements_ctrl.select_video_by_name)
        bridge.videoSelected.connect(self.metadonnees_ctrl.select_video_by_name)
        bridge.videoSelected.connect(self.extraction_ctrl.select_video_by_name)

        # Wire navigation actions
        window.actionAcceuil.triggered.connect(lambda: self.switch_page(window.page_accueil))
        window.actionQualification.triggered.connect(lambda: self.switch_page(window.page_qualification))
        window.actionValidation.triggered.connect(lambda: self.switch_page(window.page_validation))
        window.actionEvenements.triggered.connect(lambda: self.switch_page(window.page_evenements))
        window.actionMetadonnees.triggered.connect(lambda: self.switch_page(window.page_metadonnees))
        window.actionA_propos.triggered.connect(lambda: self.switch_page(window.page_apropos))
        window.actionExtraction.triggered.connect(lambda: self.switch_page(window.page_extraction))

        # Language buttons
        window.btn_lang_fr.clicked.connect(lambda: self.set_language("fr"))
        window.btn_lang_en.clicked.connect(lambda: self.set_language("en"))

        if hasattr(window, 'btn_sftp'):
            window.btn_sftp.clicked.connect(self._open_sftp_dialog)

        # Finish buttons
        self.btn_finir_qualif = window.findChild(QtWidgets.QPushButton, "btn_finir_qualif")
        if self.btn_finir_qualif:
            self.btn_finir_qualif.clicked.connect(self.complete_qualification)

        self.btn_finir_validation = window.findChild(QtWidgets.QPushButton, "btn_finir_validation")
        if self.btn_finir_validation:
            self.btn_finir_validation.clicked.connect(self.complete_validation)

        # Button mapping for navigation highlight
        window.button_mapping = {
            window.page_accueil: window.actionAcceuil,
            window.page_qualification: window.actionQualification,
            window.page_validation: window.actionValidation,
            window.page_evenements: window.actionEvenements,
            window.page_metadonnees: window.actionMetadonnees,
            window.page_extraction: window.actionExtraction,
            window.page_apropos: window.actionA_propos,
        }

        self.lock_navigation(True)
        self.switch_page(window.page_accueil)

    def _on_meta_video_selected(self, video_name: str, _video_path: str):
        """Ouvre le player détaché et focus la carte depuis la page Métadonnées."""
        # Focus carte — update_minimap gère le raise_() du dialog et le pan JS
        self.qualif_ctrl.update_minimap(video_name)
        # Ouvre le player (bypass la garde selected_video_name)
        prev = self.qualif_ctrl.selected_video_name
        self.qualif_ctrl.selected_video_name = None
        self.qualif_ctrl.select_video_by_name(video_name)
        if self.qualif_ctrl.selected_video_name is None:
            # select_video_by_name n'a pas trouvé la vidéo, restaurer
            self.qualif_ctrl.selected_video_name = prev

    def _on_metadata_saved(self):
        """Reconstruit la minimap si elle est visible, sinon invalide pour le prochain affichage."""
        if self.qualif_ctrl.map_dialog.isVisible():
            self.qualif_ctrl.map_initialized = False
            self.qualif_ctrl.update_minimap(self.qualif_ctrl.selected_video_name)
        else:
            self.qualif_ctrl.map_initialized = False

    def _open_sftp_dialog(self):
        """Ouvre le dialog de connexion SFTP / téléversement carte SD."""
        dlg = SftpDialog(self.window)
        dlg.exec()

    # --- Language ---

    def set_language(self, language: str):
        """Propage la langue à tous les controllers et met à jour les boutons workflow."""
        w = self.window
        if language not in w.translations:
            return
        w.current_language = language
        w.update_language_buttons(language)
        trans = w.translations[language]
        if self.btn_finir_qualif:
            self.btn_finir_qualif.setText(trans.get('Finir qualification', self.btn_finir_qualif.text()))
        if self.btn_finir_validation:
            self.btn_finir_validation.setText(trans.get('Finir validation', self.btn_finir_validation.text()))
        self._update_info_labels(trans)
        for ctrl in self.page_controllers:
            if hasattr(ctrl, 'set_language'):
                ctrl.set_language(language)

    def _update_info_labels(self, trans: dict):
        """Rafraîchit les labels dérusher et campagne de la toolbar avec les traductions actuelles."""
        w = self.window
        if hasattr(w, 'derusher_label') and self._current_derusher_name:
            w.derusher_label.setText(
                trans.get('derusher_active', '{} est en train de derusher').format(self._current_derusher_name)
            )
        if hasattr(w, 'campaign_label'):
            if self._current_campaign_name:
                w.campaign_label.setText(
                    trans.get('campaign_open', '📁 {}').format(self._current_campaign_name)
                )
            else:
                w.campaign_label.setText("")
        if hasattr(w, '_campaign_mode_action'):
            mode = self._current_campaign_mode
            if mode:
                is_stereo = (mode == "STEREO")
                color = "#f0c040" if is_stereo else "#a0b8c8"
                border = "#c89a10" if is_stereo else "#607080"
                w.campaign_mode_label.setText(mode)
                w.campaign_mode_label.setStyleSheet(
                    f"color: {color}; font-weight: bold; font-family: 'Segoe UI', sans-serif;"
                    f" font-size: 10px; padding: 2px 6px; border: 1px solid {border};"
                    f" border-radius: 3px; letter-spacing: 0.5px;"
                )
                w._campaign_mode_action.setVisible(True)
            else:
                w._campaign_mode_action.setVisible(False)
        if self._current_campaign_name:
            w.setWindowTitle(f"KOSMOS IHM — {self._current_campaign_name}")

    # --- Campaign opening ---

    def handle_campaign_opening(self, nom_derusher: str):
        """Ouvre la campagne sélectionnée, rafraîchit tous les modèles et déverrouille la navigation."""
        w = self.window
        self.qualification_completed = False
        self.validation_completed = False
        self._current_campaign_mode = ""

        trans = w.translations.get(w.current_language, w.translations['fr'])
        if self.btn_finir_qualif:
            self.btn_finir_qualif.setEnabled(True)
            self.btn_finir_qualif.setText(trans.get('Finir qualification', 'Finir qualification'))
        if self.btn_finir_validation:
            self.btn_finir_validation.setEnabled(True)
            self.btn_finir_validation.setText(trans.get('Finir validation', 'Finir validation'))

        self._current_derusher_name = nom_derusher

        self.qualif_ctrl.open_system_explorer(nom_derusher)
        self._refresh_all_page_models()
        self._detect_campaign_mode()
        self.refresh_status_bar()

        dossier = getattr(self.qualif_ctrl, 'current_campaign_folder', None)
        if not dossier:
            return

        session = os.path.basename(os.path.normpath(dossier))
        parent = os.path.basename(os.path.dirname(os.path.normpath(dossier)))
        self._current_campaign_name = f"{parent} / {session}" if parent else session
        self._update_info_labels(w.translations.get(w.current_language, w.translations['fr']))

        data_systeme = get_campaign_json_data(dossier, extract_system=True)
        data_complete = get_campaign_json_data(dossier, extract_system=False)

        if data_systeme:
            # Unlock ALL pages — the workflow buttons (Finir qualif/valid) restent
            # disponibles comme guide mais ne doivent pas bloquer la navigation
            # quand on change de campagne.
            self.qualification_completed = True
            self.validation_completed = True
            self.lock_navigation(False)
            self.metadonnees_ctrl.load_global_campaign_metadata(dossier)

            try:
                lat = lon = None
                if data_complete and "video_observation" in data_complete:
                    block = data_complete["video_observation"]
                    lat = block.get("latitude", {}).get("value")
                    lon = block.get("longitude", {}).get("value")

                if lat is not None and lon is not None:
                    self.weather_thread = WeatherWorker(lat, lon)
                    self.weather_thread.weather_fetched.connect(self.metadonnees_ctrl.inject_weather_data)
                    self.weather_thread.start()
                else:
                    self.metadonnees_ctrl.inject_weather_data({})
            except Exception as e:
                print(f"[METEO] Error: {e}")
                self.metadonnees_ctrl.inject_weather_data({})

            self.switch_page(w.page_qualification)
        else:
            # Pas de JSON système trouvé (campagne fraîche) — déverrouiller quand même
            # Qualification si des vidéos ont été chargées, sinon tout garder verrouillé.
            has_videos = self.qualif_ctrl.video_model.rowCount() > 0
            if has_videos:
                self.lock_navigation(False)   # Val/Events restent locked (flags=False)
                self.switch_page(w.page_qualification)
            else:
                self.lock_navigation(True)

    def _detect_campaign_mode(self):
        """Détermine si la campagne est MONO ou STEREO à partir de la première vidéo du modèle."""
        model = self.qualif_ctrl.video_model
        if model.rowCount() == 0:
            self._current_campaign_mode = ""
            return
        first_item = model.item(0, 0)
        if first_item is None:
            self._current_campaign_mode = ""
            return
        first_path = first_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if first_path:
            is_stereo, _ = check_stereo_status(first_path)
            self._current_campaign_mode = "STEREO" if is_stereo else "MONO"
        else:
            self._current_campaign_mode = ""

    def _refresh_all_page_models(self):
        """Recharge le VideoModel dans tous les controllers de page après ouverture de campagne."""
        updated_model = self.qualif_ctrl.video_model
        for ctrl, method in [
            (self.validation_ctrl, 'load_campaign_videos'),
            (self.evenements_ctrl, 'load_campaign_videos'),
            (self.metadonnees_ctrl, 'load_campaign_videos'),
            (self.extraction_ctrl, 'load_campaign_videos'),
        ]:
            if hasattr(ctrl, method):
                getattr(ctrl, method)(updated_model)

    # --- Qualification / Validation completion ---

    def complete_qualification(self):
        """Marque la qualification terminée, déverrouille Validation/Événements et bascule vers Validation."""
        self.qualification_completed = True
        w = self.window
        w.actionValidation.setEnabled(True)
        w.actionEvenements.setEnabled(True)
        if self.btn_finir_qualif:
            self.btn_finir_qualif.setEnabled(False)
            trans = w.translations[w.current_language]
            self.btn_finir_qualif.setText(trans.get('Qualification Terminée ✓', 'Qualification Terminée ✓'))
        self.switch_page(w.page_validation)

    def complete_validation(self):
        """Marque la validation terminée, déverrouille Événements et bascule vers Métadonnées."""
        self.validation_completed = True
        w = self.window
        w.actionEvenements.setEnabled(True)
        if self.btn_finir_validation:
            self.btn_finir_validation.setEnabled(False)
            trans = w.translations[w.current_language]
            self.btn_finir_validation.setText(trans.get('Validation Terminée ✓', 'Validation Terminée ✓'))
        self.switch_page(w.page_metadonnees)

    # --- Navigation ---

    def lock_navigation(self, locked: bool):
        """Active ou désactive les actions de navigation selon l'état du workflow."""
        w = self.window
        w.actionQualification.setEnabled(not locked)
        w.actionMetadonnees.setEnabled(not locked)
        w.actionExtraction.setEnabled(True)
        if locked:
            w.actionValidation.setEnabled(False)
            w.actionEvenements.setEnabled(False)
        else:
            w.actionValidation.setEnabled(self.qualification_completed)
            w.actionEvenements.setEnabled(self.qualification_completed and self.validation_completed)

    def _release_file_in_all_players(self, path: str):
        """Libère le verrou Windows sur un fichier vidéo dans tous les players embarqués."""
        for player in [
            getattr(self.validation_ctrl, 'player', None),
            getattr(self.evenements_ctrl, 'event_player', None),
            getattr(self.extraction_ctrl, 'video_player', None),
        ]:
            if player is not None and hasattr(player, 'release_video_file'):
                player.release_video_file(path)

    def _stop_background_players(self, target_page):
        """Arrête les lecteurs de la page qu'on quitte pour éviter l'accumulation."""
        w = self.window
        current = w.stackedWidget.currentWidget()
        if current == target_page:
            return
        # Lecteur détaché de qualification : fermé quand on quitte la page qualif
        if current == w.page_qualification:
            self.qualif_ctrl._close_detached_player()

    def switch_page(self, page):
        """Bascule vers page si le workflow le permet, arrête les lecteurs de la page courante."""
        w = self.window
        free_pages = [w.page_accueil, w.page_apropos, w.page_extraction]

        self._stop_background_players(page)

        if page in free_pages:
            w.stackedWidget.setCurrentWidget(page)
            w.update_nav_highlight(page)
            if page == w.page_extraction:
                self.extraction_ctrl.refresh_video_list()
            self._focus_page_player(page)
            return

        if not w.actionQualification.isEnabled():
            return
        if page == w.page_validation and not self.qualification_completed:
            return
        if page == w.page_evenements and not self.validation_completed:
            return
        if page == w.page_extraction:
            self.extraction_ctrl.refresh_video_list()

        w.stackedWidget.setCurrentWidget(page)
        w.update_nav_highlight(page)
        self._focus_page_player(page)

    def _focus_page_player(self, page):
        """Donne le focus clavier au player embarqué de la page, si présent."""
        w = self.window
        player_map = {
            w.page_validation: (self.validation_ctrl, 'player'),
            w.page_evenements: (self.evenements_ctrl, 'event_player'),
            w.page_extraction: (self.extraction_ctrl, 'video_player'),
        }
        entry = player_map.get(page)
        if entry:
            ctrl, attr = entry
            player = getattr(ctrl, attr, None)
            if player is not None:
                QtCore.QTimer.singleShot(0, player.setFocus)

    def _focus_map(self, video_name: str):
        """Focalise la carte Leaflet sur la vidéo dont le nom est fourni."""
        self.qualif_ctrl.update_minimap(video_name)

    def refresh_status_bar(self, *_):
        """Recalcule et affiche les stats de campagne dans la barre de statut."""
        model = self.qualif_ctrl.video_model
        n = model.rowCount()
        total_sec = 0
        qualified = 0
        for row in range(n):
            dur_item = model.item(row, 1)
            if dur_item:
                parts = dur_item.text().split(":")
                if len(parts) == 2:
                    try:
                        total_sec += int(parts[0]) * 60 + int(parts[1])
                    except ValueError:
                        pass
            path_item = model.item(row, 0)
            if path_item:
                video_path = path_item.data(QtCore.Qt.ItemDataRole.UserRole)
                if video_path:
                    json_path = get_video_json_path(video_path)
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            val = data.get("video_observation", {}).get("exploitable", {}).get("value")
                            if val and str(val).strip():
                                qualified += 1
                        except Exception:
                            pass
        self.window.update_status_bar(n, total_sec, qualified)
