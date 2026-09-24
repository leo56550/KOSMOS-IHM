from PyQt6 import QtWidgets, QtCore
import json

from services.campaign_service import (get_campaign_json_data, get_video_json_path,
                                       get_working_video_json_path)
from services.video_service import check_stereo_status, get_system_name
from services.weather_service import WeatherWorker
from services.sound_service import get_sound_service
from views.dialogs.notes_dialog import NotesDialog
from controllers.accueil_controller import AccueilController
from controllers.qualif_controller import QualifController, _get_point_name
from controllers.validation_controller import ValidationController
from controllers.evenements_controller import EvenementsController
from controllers.metadonnees_controller import MetadonneesController
from controllers.extraction_controller import ExtractionController
from controllers.apropos_controller import AProposController
import os


class AppController(QtCore.QObject):
    """Orchestrates navigation, campaign lifecycle, and page controllers."""

    def __init__(self, window):
        """Instancie tous les controllers de page, connecte les signaux de navigation et les boutons workflow."""
        super().__init__()
        self.window = window
        self._current_campaign_name: str = ""
        self._current_derusher_name: str = ""
        self._current_campaign_mode: str = ""  # "MONO" | "STEREO" | ""
        self.working_dir: str = ""
        self._campaign_ready: bool = False
        self._campaign_qualified: bool = False  # True dès qu'au moins une vidéo a été qualifiée

        # Instantiate page controllers
        self.accueil_ctrl = AccueilController(
            window.page_accueil,
            self.handle_campaign_opening,
        )
        self.qualif_ctrl = QualifController(
            window.page_qualification, parent=window,
            on_before_delete=self._release_file_in_all_players,
            on_qualification_changed=self._on_qualification_changed,
        )
        self.validation_ctrl = ValidationController(
            window.page_validation, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
            on_qualification_changed=self._on_qualification_changed,
        )
        self.evenements_ctrl = EvenementsController(
            window.page_evenements, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
            on_events_changed=self._on_events_changed,
            on_export_started=window.show_export_progress,
            on_export_progress=window.update_export_progress,
            on_export_ended=window.hide_export_progress,
        )
        if hasattr(window, 'btn_stop_export'):
            window.btn_stop_export.clicked.connect(self.evenements_ctrl.stop_export)
        self.metadonnees_ctrl = MetadonneesController(
            window.page_metadonnees,
            self.qualif_ctrl.video_model,
            self.qualif_ctrl.trash_model,
            on_metadata_saved=self._on_metadata_saved,
            on_video_selected=self._on_meta_video_selected,
            on_open_map=self._open_map_from_metadonnees,
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

        if hasattr(window, 'btn_open_video'):
            window.btn_open_video.clicked.connect(self._open_single_video)

        if hasattr(window, 'btn_notes'):
            window.btn_notes.clicked.connect(self._open_notes)

        if hasattr(window, 'btn_sftp'):
            window.btn_sftp.clicked.connect(self._open_sftp_dialog)

        if hasattr(window, 'btn_recent_campaigns'):
            window.btn_recent_campaigns.clicked.connect(self._open_recent_campaigns)

        if hasattr(window, 'btn_load_history'):
            window.btn_load_history.clicked.connect(self._load_historical_data)

        if hasattr(window, 'btn_delete_temp'):
            window.btn_delete_temp.clicked.connect(self._delete_temp_jsons)

        if hasattr(window, 'btn_generate_temp'):
            window.btn_generate_temp.clicked.connect(self._generate_temp_jsons)

        # Boutons QUALIFIER / VALIDER retirés : la navigation entre pages n'est plus
        # conditionnée à un clic explicite, seule une campagne chargée est nécessaire.
        btn_finir_qualif = window.findChild(QtWidgets.QPushButton, "btn_finir_qualif")
        if btn_finir_qualif:
            btn_finir_qualif.setVisible(False)
        btn_finir_validation = window.findChild(QtWidgets.QPushButton, "btn_finir_validation")
        if btn_finir_validation:
            btn_finir_validation.setVisible(False)

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
        # Synchronise la langue initiale (fenêtre démarre en FR, controllers en EN par défaut)
        self.set_language(window.current_language)

        # +/- pour accélérer/ralentir le player visible, sans dépendre du focus (cf. eventFilter)
        QtWidgets.QApplication.instance().installEventFilter(self)

    def _on_meta_video_selected(self, video_name: str, _video_path: str):  # noqa: ARG002
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

    def _sync_all_to_working_dir(self) -> None:
        """Copie les fichiers compagnon de toutes les vidéos dans le répertoire de travail.

        Seules les copies de travail sont modifiées — les JSON bruts ne sont jamais touchés.
        """
        if not self.working_dir or not self._campaign_ready:
            return

        model = self.qualif_ctrl.video_model
        video_paths = []
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if video_path:
                video_paths.append(video_path)

        # Écriture du dérusher uniquement dans les copies de travail (jamais dans les bruts)
        if self._current_derusher_name:
            self._write_derusher_to_working_copies(video_paths, self._current_derusher_name)

    def _write_derusher_to_working_copies(self, video_paths: list, derusher_name: str) -> None:
        """Écrit le nom du dérusher dans les copies de travail des JSONs vidéo."""
        import json as _json
        count = 0
        for video_path in video_paths:
            wjson = get_working_video_json_path(self.working_dir, video_path)
            if not os.path.isfile(wjson):
                continue
            try:
                with open(wjson, 'r', encoding='utf-8') as f:
                    data = _json.load(f)
                vo = data.get("video_observation", {})
                if "derusher" in vo:
                    existing = (vo["derusher"].get("value") or "").strip()
                    new_val = derusher_name.strip()
                    if existing and existing != new_val:
                        if new_val not in [n.strip() for n in existing.split(",")]:
                            new_val = f"{existing}, {new_val}"
                        else:
                            new_val = existing
                    vo["derusher"]["value"] = new_val
                    with open(wjson, 'w', encoding='utf-8') as f:
                        _json.dump(data, f, indent=2, ensure_ascii=False)
                    count += 1
            except Exception as e:
                print(f"[DERUSHER] {wjson}: {e}")
        print(f"[DERUSHER] '{derusher_name}' écrit dans {count} copies de travail.")

    def _open_working_dir(self):
        """Ouvre un sélecteur de dossier pour choisir le répertoire de travail IHM."""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            "Choisir le répertoire de travail (ex : 2026)",
            self.working_dir or "",
        )
        if not path:
            return
        self.working_dir = path
        # Propager aux controllers
        for ctrl in [self.qualif_ctrl, self.validation_ctrl, self.evenements_ctrl,
                     self.metadonnees_ctrl, self.extraction_ctrl]:
            if hasattr(ctrl, 'set_working_dir'):
                ctrl.set_working_dir(path)
        # Arrêter le clignotement, passer le bouton en vert
        self.accueil_ctrl.confirm_working_dir(path)
        # Déverrouiller la navigation maintenant que les deux conditions sont remplies
        if self._campaign_ready:
            self.lock_navigation(False)
        # Synchroniser tous les fichiers compagnon maintenant que le répertoire est connu
        self._sync_all_to_working_dir()

    def _on_metadata_saved(self, video_path: str = None):
        """Reconstruit la minimap et rafraîchit l'indicateur de complétion + le n° de point
        de la vidéo modifiée, sans attendre un clic pour que la page Validation le reflète."""
        if self.qualif_ctrl.map_dialog.isVisible():
            self.qualif_ctrl.map_initialized = False
            self.qualif_ctrl.update_minimap(self.qualif_ctrl.selected_video_name)
        else:
            self.qualif_ctrl.map_initialized = False
        vp = video_path or self.metadonnees_ctrl.current_video_path
        if vp:
            self.qualif_ctrl.refresh_completion_color_for_video(vp)
            self._refresh_point_name_for_video(vp)

    def _refresh_point_name_for_video(self, video_path: str):
        """Recalcule le n° de point (UserRole+3) et le repropage sur le modèle vidéo partagé.

        Le n° de point est affiché via cette donnée sur plusieurs pages (ex: page Validation) ;
        sans ce refresh, une édition faite sur la page Métadonnées n'apparaissait qu'après avoir
        cliqué sur la vidéo (ce qui réécrivait UserRole+3 en passant).
        """
        new_val = _get_point_name(video_path, self.working_dir)
        for model in (self.qualif_ctrl.video_model, self.qualif_ctrl.trash_model):
            for row in range(model.rowCount()):
                item = model.item(row, 0)
                if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == str(video_path):
                    item.setData(new_val, QtCore.Qt.ItemDataRole.UserRole + 3)

    def _open_single_video(self):
        """Ouvre un fichier MP4 standalone dans un player complet, sans campagne."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            self.translate("Ouvrir une vidéo", "Open a video"),
            "",
            self.translate("Vidéos MP4 (*.mp4);;Tous les fichiers (*)", "MP4 videos (*.mp4);;All files (*)"),
        )
        if not path:
            return
        from views.dialogs.quick_video_dialog import QuickVideoDialog
        dlg = QuickVideoDialog(path, parent=self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.show()

    def _open_notes(self):
        """Ouvre le bloc-notes de session pour la campagne courante."""
        dossier = getattr(self.qualif_ctrl, 'current_campaign_folder', None)
        if not dossier:
            return
        dlg = NotesDialog(dossier, parent=self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.show()

    def _on_qualification_changed(self):
        """Appelé quand l'exploitabilité d'une vidéo change — rafraîchit la barre de statut."""
        self.refresh_status_bar()
        self.metadonnees_ctrl.refresh_feuille_terrain()
        self.qualif_ctrl.refresh_map_marker_colors()

    def _on_events_changed(self, *_):
        """Callback déclenché quand des événements sont ajoutés/supprimés/modifiés."""
        self.metadonnees_ctrl.refresh_feuille_terrain()

    def _open_sftp_dialog(self):
        """Ouvre le hub KOSMOS Connexion (SFTP + planification déploiement)."""
        from views.dialogs.kosmos_connexion_dialog import KosmosConnexionDialog
        dlg = KosmosConnexionDialog(self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.exec()

    def _open_recent_campaigns(self):
        """Ouvre le dialog de sélection d'une campagne récente."""
        from views.dialogs.recent_campaigns_dialog import RecentCampaignsDialog
        dlg = RecentCampaignsDialog(parent=self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.campaign_selected.connect(self._open_campaign_from_recent)
        dlg.exec()

    def _open_campaign_from_recent(self, campaign_folder: str, working_dir: str, derusher_name: str):
        """Ouvre une campagne depuis la liste des récents."""
        if not campaign_folder or not os.path.isdir(campaign_folder):
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Dossier introuvable", "Folder not found"),
                self.translate(
                    f"Le dossier de campagne n'existe plus :\n{campaign_folder}",
                    f"The campaign folder no longer exists:\n{campaign_folder}",
                ),
            )
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self.window,
            self.translate("Nom du dérusher", "Derusher name"),
            self.translate("Votre nom :", "Your name:"),
            text=derusher_name or "",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Nom requis", "Name required"),
                self.translate("Veuillez saisir un nom de dérusher.", "Please enter a derusher name."),
            )
            return

        self.handle_campaign_opening(
            name,
            campaign_folder=campaign_folder,
            working_dir=working_dir,
        )

    def _delete_temp_jsons(self):
        """Supprime tous les _temp.json d'un dossier choisi par l'utilisateur après confirmation."""
        start_dir = getattr(self.qualif_ctrl, 'current_campaign_folder', '') or self.working_dir or ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            self.translate("Choisir le dossier", "Choose folder"),
            start_dir,
        )
        if not folder or not os.path.isdir(folder):
            return
        import glob as _glob
        temp_files = _glob.glob(os.path.join(folder, "**", "*_temp.json"), recursive=True)
        if not temp_files:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Aucun fichier", "No files"),
                self.translate("Aucun _temp.json trouvé dans le dossier de travail.",
                               "No _temp.json found in the working directory.")
            )
            return
        reply = QtWidgets.QMessageBox.question(
            self.window,
            self.translate("Confirmer la suppression", "Confirm deletion"),
            self.translate(
                f"⚠️ Attention : vous allez perdre toutes vos métadonnées !\n\n"
                f"{len(temp_files)} fichier(s) _temp.json vont être supprimés.\n"
                f"Cette action est irréversible.\n\nContinuer ?",
                f"⚠️ Warning: you will lose all your metadata!\n\n"
                f"{len(temp_files)} _temp.json file(s) will be deleted.\n"
                f"This action cannot be undone.\n\nContinue?"
            ),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        errors = []
        for f in temp_files:
            try:
                os.remove(f)
            except Exception as e:
                errors.append(f"{os.path.basename(f)}: {e}")
        if errors:
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Erreurs", "Errors"),
                "\n".join(errors)
            )
        else:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Suppression terminée", "Deletion complete"),
                self.translate(f"{len(temp_files)} _temp.json supprimé(s).",
                               f"{len(temp_files)} _temp.json deleted.")
            )

        # Rafraîchir la page métadonnées pour refléter la suppression
        if hasattr(self.metadonnees_ctrl, '_rebuild_ft_table'):
            self.metadonnees_ctrl._rebuild_ft_table()

    def _load_historical_data(self):
        """Ouvre un CSV/XLSX infostation et l'affiche directement dans le tableau métadonnées."""
        start_dir = getattr(self.qualif_ctrl, 'current_campaign_folder', '') or self.working_dir or ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            self.translate("Charger données historiques", "Load historical data"),
            start_dir,
            "Infostation (*.csv *.xlsx);;CSV (*.csv);;Excel (*.xlsx);;Tous les fichiers (*.*)",
        )
        if not path:
            return
        self.switch_page(self.window.page_metadonnees)
        self.metadonnees_ctrl.load_csv_into_table(path)

    def _generate_temp_jsons(self):
        """Choisit un dossier, puis génère les _temp.json pour chaque vidéo matchée dans le tableau."""
        if self.metadonnees_ctrl._ft_table.rowCount() == 0:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Tableau vide", "Empty table"),
                self.translate(
                    "Chargez d'abord un fichier CSV via 'Données historiques'.",
                    "Please load a CSV file via 'Historical data' first.",
                ),
            )
            return

        start_dir = getattr(self.qualif_ctrl, 'current_campaign_folder', '') or self.working_dir or ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            self.translate("Choisir le dossier contenant les vidéos", "Choose the folder containing videos"),
            start_dir,
        )
        if not folder:
            return

        generated, total, failures = self.metadonnees_ctrl.generate_temp_from_table(folder)

        skipped = total - generated
        summary = self.translate(
            f"{generated} temp.json générés sur {total} ligne(s).",
            f"{generated} temp.json generated out of {total} row(s).",
        )

        if failures:
            detail_lines = "\n".join(
                f"  • {name} → {reason}" for name, reason in failures
            )
            detail = self.translate(
                f"\n\n⚠️ {skipped} ligne(s) non traitée(s) :\n{detail_lines}",
                f"\n\n⚠️ {skipped} row(s) not processed:\n{detail_lines}",
            )
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Génération terminée avec avertissements", "Generation complete with warnings"),
                summary + detail,
            )
        else:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Génération terminée", "Generation complete"),
                summary,
            )

    # --- Language ---

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue courante de la fenêtre."""
        lang = getattr(self.window, 'current_language', 'fr')
        return fr if lang == 'fr' else en

    def set_language(self, language: str):
        """Propage la langue à tous les controllers et met à jour les boutons workflow."""
        w = self.window
        if language not in w.translations:
            return
        w.current_language = language
        w.update_language_buttons(language)
        trans = w.translations[language]
        self._update_info_labels(trans)
        for ctrl in self.page_controllers:
            if hasattr(ctrl, 'set_language'):
                ctrl.set_language(language)
        self.refresh_status_bar()

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

    def handle_campaign_opening(self, nom_derusher: str,
                               campaign_folder: str = "", working_dir: str = ""):
        """Charge la campagne, propage le répertoire de travail et déverrouille la navigation."""
        w = self.window
        self._current_campaign_mode = ""
        self._current_derusher_name = nom_derusher
        self.lock_navigation(False)  # remet actionValidation/Metadonnees/Evenements à disabled

        # Charger la campagne — directement si le dossier est fourni par le dialog
        if campaign_folder:
            self.qualif_ctrl.load_campaign_folder(campaign_folder, nom_derusher)
        else:
            self.qualif_ctrl.open_system_explorer(nom_derusher)

        self._refresh_all_page_models()
        self._detect_campaign_mode()
        self.refresh_status_bar()

        dossier = getattr(self.qualif_ctrl, 'current_campaign_folder', None)
        if not dossier:
            return

        if hasattr(self.window, 'btn_notes'):
            self.window.btn_notes.setEnabled(True)
        session = os.path.basename(os.path.normpath(dossier))
        parent = os.path.basename(os.path.dirname(os.path.normpath(dossier)))
        self._current_campaign_name = f"{parent} / {session}" if parent else session
        self._update_info_labels(w.translations.get(w.current_language, w.translations['fr']))
        get_sound_service().play("campaign_open")

        try:
            from services.recent_campaigns_service import add_recent_campaign
            add_recent_campaign(dossier, working_dir or self.working_dir,
                                self._current_campaign_name, nom_derusher)
        except Exception:
            pass

        data_systeme = get_campaign_json_data(dossier, extract_system=True)
        data_complete = get_campaign_json_data(dossier, extract_system=False)

        # Répertoire de travail fourni par le dialog → propager immédiatement
        if working_dir:
            self.working_dir = working_dir
            for ctrl in [self.qualif_ctrl, self.validation_ctrl, self.evenements_ctrl,
                         self.metadonnees_ctrl, self.extraction_ctrl]:
                if hasattr(ctrl, 'set_working_dir'):
                    ctrl.set_working_dir(working_dir)

        self._campaign_ready = True
        # Sync immédiat si le répertoire de travail est déjà connu
        self._sync_all_to_working_dir()

        if data_systeme:
            if self.working_dir:
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
            if has_videos and self.working_dir:
                self.lock_navigation(False)
                self.switch_page(w.page_qualification)
            else:
                self.lock_navigation(True)

    def _detect_campaign_mode(self):
        """Détermine le mode et les systèmes de la campagne en scannant toutes les vidéos."""
        model = self.qualif_ctrl.video_model
        if model.rowCount() == 0:
            self._current_campaign_mode = ""
            self._update_systems_label([])
            return
        stereo_count = 0
        total = 0
        systems_ordered: list[str] = []
        systems_seen: set[str] = set()
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            if not item:
                continue
            path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not path:
                continue
            total += 1
            is_stereo, _ = check_stereo_status(str(path))
            if is_stereo:
                stereo_count += 1
            sys_name = get_system_name(str(path))
            if sys_name not in systems_seen:
                systems_seen.add(sys_name)
                systems_ordered.append(sys_name)
        if total == 0:
            self._current_campaign_mode = ""
        elif stereo_count == 0:
            self._current_campaign_mode = "MONO"
        elif stereo_count == total:
            self._current_campaign_mode = "STEREO"
        else:
            self._current_campaign_mode = "MIXTE"
        self._update_systems_label(systems_ordered)

    def _update_systems_label(self, systems: list[str]):
        """Met à jour le label systèmes dans la toolbar."""
        w = self.window
        if not hasattr(w, 'systems_label'):
            return
        if not systems:
            w._systems_action.setVisible(False)
            return
        n = len(systems)
        label = f"{n} système{'s' if n > 1 else ''} : {' · '.join(systems)}"
        w.systems_label.setText(label)
        w.systems_label.setStyleSheet(
            "color: #a0c8e0; font-family: 'Segoe UI', sans-serif;"
            " font-size: 10px; padding: 2px 8px; border: 1px solid #405870;"
            " border-radius: 3px; letter-spacing: 0.3px;"
        )
        w._systems_action.setVisible(True)

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
        QtCore.QTimer.singleShot(200, self.qualif_ctrl.initialize_tree_indicators)

    # --- Vérifications de contenu ---

    # --- Navigation ---

    def lock_navigation(self, locked: bool):
        """Active ou désactive les actions de navigation (verrouillé tant qu'aucune campagne n'est chargée)."""
        w = self.window
        w.actionQualification.setEnabled(not locked)
        w.actionExtraction.setEnabled(True)
        w.actionValidation.setEnabled(not locked)
        w.actionEvenements.setEnabled(not locked)
        w.actionMetadonnees.setEnabled(not locked)

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

    def switch_page(self, page):
        """Bascule vers page si le workflow le permet, arrête les lecteurs de la page courante."""
        w = self.window
        free_pages = [w.page_accueil, w.page_apropos, w.page_extraction, w.page_metadonnees]

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

        if page == w.page_extraction:
            self.extraction_ctrl.refresh_video_list()

        w.stackedWidget.setCurrentWidget(page)
        w.update_nav_highlight(page)
        self._focus_page_player(page)

    def _get_page_player(self, page):
        """Retourne le player embarqué (EmbeddedVideoPlayer) associé à *page*, ou None."""
        w = self.window
        player_map = {
            w.page_validation: (self.validation_ctrl, 'player'),
            w.page_evenements: (self.evenements_ctrl, 'event_player'),
            w.page_extraction: (self.extraction_ctrl, 'video_player'),
        }
        entry = player_map.get(page)
        if not entry:
            return None
        ctrl, attr = entry
        return getattr(ctrl, attr, None)

    def _focus_page_player(self, page):
        """Donne le focus clavier au player embarqué de la page, si présent."""
        player = self._get_page_player(page)
        if player is not None:
            # Délai non nul : à 0ms, le focus donné au bouton de nav cliqué (ou au
            # widget par défaut de la page) reprend parfois la main juste après.
            QtCore.QTimer.singleShot(80, player.setFocus)

    _SPEED_KEYS = {
        QtCore.Qt.Key.Key_Plus: +1, QtCore.Qt.Key.Key_Equal: +1,
        QtCore.Qt.Key.Key_Minus: -1, QtCore.Qt.Key.Key_Underscore: -1,
    }
    _TEXT_INPUT_TYPES = (
        QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
        QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QComboBox,
    )

    def eventFilter(self, obj, event):
        """Intercepte +/- au niveau application pour changer la vitesse du player de la
        page actuellement affichée, sans dépendre du focus précis d'un widget — ça marche
        dès l'arrivée sur la page, pas seulement après avoir cliqué dedans."""
        if event.type() == QtCore.QEvent.Type.KeyPress:
            direction = self._SPEED_KEYS.get(event.key())
            if direction is not None:
                focus_w = QtWidgets.QApplication.focusWidget()
                if not isinstance(focus_w, self._TEXT_INPUT_TYPES):
                    page = self.window.stackedWidget.currentWidget()
                    player = self._get_page_player(page)
                    if player is not None and hasattr(player, '_speed_step'):
                        player._speed_step(direction)
                        rate = player.player.playbackRate() or 1.0
                        rate_str = f"×{int(rate) if rate == int(rate) else rate}"
                        icon = "⬆" if direction > 0 else "⬇"
                        if hasattr(player, 'show_fs_osd'):
                            player.show_fs_osd(f"{icon}  {rate_str}")
                        return True
        return super().eventFilter(obj, event)

    def _focus_map(self, video_name: str):
        """Focalise la carte Leaflet sur la vidéo dont le nom est fourni."""
        self.qualif_ctrl.update_minimap(video_name)

    def _open_map_from_metadonnees(self, video_name: str = None):
        """Ouvre la carte de campagne (QDialog Leaflet) depuis la page Métadonnées."""
        self.qualif_ctrl.update_minimap(video_name, show_dialog=True)

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
