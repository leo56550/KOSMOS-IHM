import os
import json
import uuid
import cv2
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from utils2 import get_motor_stable_timestamps, extract_frame_at_time, ExportWorker
from timeline import VideoTimeline
from embedded_player import EmbeddedVideoPlayer
from export_options import ExportOptionsDialog


class VideoFilterProxyModel(QtCore.QSortFilterProxyModel):
    """Proxy model qui masque les vidéos déjà déplacées dans la corbeille
    ou dont le statut exploitable est explicitement "non".
    """

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        source_model = self.sourceModel()
        if source_model is None:
            return True

        index_nom = source_model.index(source_row, 0, source_parent)
        if not index_nom.isValid():
            return True

        video_path = source_model.data(index_nom, QtCore.Qt.ItemDataRole.UserRole)
        if not video_path:
            return True

        parties = os.path.normpath(video_path).split(os.sep)
        if ".trash" in parties or "trash" in parties:
            return False

        json_path = os.path.join(os.path.dirname(video_path), "template.json")
        if not os.path.exists(json_path):
            return True

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            exploitable_field = data.get("video_observation", {}).get("exploitable", {})
            valeur_exploitable = exploitable_field.get("value")
            if isinstance(valeur_exploitable, str) and valeur_exploitable.strip().lower() == "non":
                return False
        except Exception:
            pass

        return True
    
from embedded_player import EmbeddedVideoPlayer


class EventsPage:
    """Contrôleur associé à la page des événements (page_evenements)."""

    def __init__(self, page_widget: QtWidgets.QWidget, shared_model: QtGui.QStandardItemModel):
        self.page = page_widget
        self.video_model = shared_model
        self.current_language = 'fr'

        self.current_json_path = None
        self.current_video_path = None  # Stocke la vidéo active pour l'extraction de frames
        self.dictionnaire_evenements = {}
        self.temps_debut_capture = None

        self.frame_gauche_events = self.page.findChild(QtWidgets.QFrame, "frame_12")
        self.player_container_events = self.page.findChild(QtWidgets.QFrame, "video_timeline_container")
        self.choose_event_container = self.page.findChild(QtWidgets.QFrame, "choose_event_container")
        
        if self.choose_event_container:
            self.choose_event_container.setMinimumWidth(320)
            self.choose_event_container.setMaximumWidth(420)
            self.choose_event_container.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred,
                QtWidgets.QSizePolicy.Policy.Expanding
            )
            self.choose_event_container.setStyleSheet(
                "QFrame { background-color: #181c24; border: 1px solid #2778a2; border-radius: 14px; }"
            )
        self.set_language(self.current_language)
        
        # Récupération et structuration complète du conteneur bas (Arbre + Galerie)
        self.list_event_container = self.page.findChild(QtWidgets.QFrame, "list_event_container")
        self.initialiser_list_event_layout()

        self.export_container = self.page.findChild(QtWidgets.QWidget, "container_export") or self.page.findChild(QtWidgets.QFrame, "container_export")
        self.initialiser_export_ui()

        if self.frame_gauche_events:
            self.frame_gauche_events.setMinimumWidth(150)
            self.frame_gauche_events.setMaximumWidth(16777215) 

        self.proxy_model = VideoFilterProxyModel(self.page)
        self.proxy_model.setSourceModel(self.video_model)

        if self.player_container_events:
            if self.player_container_events.layout() is None:
                self.player_layout_events = QtWidgets.QVBoxLayout(self.player_container_events)
                self.player_layout_events.setContentsMargins(10, 10, 10, 10)
            else:
                self.player_layout_events = self.player_container_events.layout()

            zones = [
                {"label": "Déploiement", "color": QtGui.QColor(32, 65, 93, 100)},   # Indigo dye (#20415D)
                {"label": "Faune / Animal", "color": QtGui.QColor(39, 120, 162, 100)}, # Cerulean (#2778A2)
                {"label": "Images", "color": QtGui.QColor(217, 79, 56, 100)}       # Jasper (#D94F38)
            ]
            self.lecteur_events = EmbeddedVideoPlayer(parent=self.player_container_events, zone_definitions=zones)
            self.player_layout_events.addWidget(self.lecteur_events)
            
            # =========================================================================
            # --- SYSTÈME DE SÉLECTION & MODIFICATION INTERACTIVE (DEUX SENS) ---
            # =========================================================================
            
            # 1. Modifications interactives depuis la timeline -> Mise à jour des données
            self.lecteur_events.timeline.eventResized.connect(self.rafraichir_liste_evenements)
            
            if hasattr(self.lecteur_events.timeline, 'eventMoved'):
                self.lecteur_events.timeline.eventMoved.connect(self.rafraichir_liste_evenements)
            elif hasattr(self.lecteur_events.timeline, 'eventChanged'):
                self.lecteur_events.timeline.eventChanged.connect(self.rafraichir_liste_evenements)

            # 2. Synchronisation de la sélection dans les DEUX SENS
            # Sens B : Timeline -> Arbre (Quand on clique sur un bloc de la timeline)
            # La connexion du signal de l'arbre se fait dans initialiser_list_event_layout
            self.lecteur_events.timeline.eventSelected.connect(self.sur_evenement_timeline_selectionne)

            # =========================================================================

            # ACTIVATION DU CLIC DROIT SUR LA TIMELINE
            self.lecteur_events.timeline.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            self.lecteur_events.timeline.customContextMenuRequested.connect(
                lambda pos: self.ouvrir_menu_contextuel(pos, self.lecteur_events.timeline)
            )
            self.initialiser_menus_deroulants_evenements()

        self.tree_view_events = self.page.findChild(QtWidgets.QTreeView, "treeView")
        if self.tree_view_events:
            self.tree_view_events.setModel(self.proxy_model)
            self.tree_view_events.clicked.connect(self.on_video_selected)

        self.tree_captures.itemChanged.connect(self.on_arbre_item_changed)
    def sur_evenement_arbre_selectionne(self):
        """Synchronise la sélection de l'arbre vers la timeline (Timeline -> Met en surbrillance l'événement)"""
        # Bloquer temporairement le signal de la timeline pour éviter une boucle infinie
        if not hasattr(self, 'lecteur_events') or not self.lecteur_events or not self.lecteur_events.timeline:
            return
            
        self.lecteur_events.timeline.blockSignals(True)
        
        try:
            # Récupérer l'élément sélectionné dans l'arbre
            items_selectionnes = self.tree_captures.selectedItems()
            if not items_selectionnes:
                # Si rien n'est sélectionné, on retire la surbillance
                if hasattr(self.lecteur_events.timeline, 'set_selected_event'):
                    self.lecteur_events.timeline.set_selected_event(None)
                else:
                    self.lecteur_events.timeline._selected_event = None
                    self.lecteur_events.timeline.update()
                return
                
            item = items_selectionnes[0]
            
            # On récupère le titre propre stocké dans la colonne 3
            valeur_cible = item.text(3) 
            
            # On cherche l'événement correspondant dans la liste des événements de la timeline
            evenement_trouve = None
            if hasattr(self.lecteur_events.timeline, 'events'):
                for evt in self.lecteur_events.timeline.events:
                    if evt.get("title", "").replace("Pic: ", "") == valeur_cible:
                        evenement_trouve = evt
                        break
                    
            # On envoie l'événement trouvé à la timeline pour qu'elle le mette en surbillance
            if hasattr(self.lecteur_events.timeline, 'set_selected_event'):
                self.lecteur_events.timeline.set_selected_event(evenement_trouve)
            else:
                self.lecteur_events.timeline._selected_event = evenement_trouve
                self.lecteur_events.timeline.update()
        finally:
            self.lecteur_events.timeline.blockSignals(False)
        


    def sur_evenement_timeline_selectionne(self, event_dict):
        """Reçoit l'événement cliqué sur la timeline et sélectionne la ligne correspondante dans l'arbre"""
        # Vérifier que l'arbre existe
        if not hasattr(self, 'tree_captures') or not self.tree_captures:
            return
            
        # Désactiver temporairement les signaux de l'arbre pour éviter une boucle infinie
        self.tree_captures.blockSignals(True)
        
        try:
            # 1. Si on a cliqué dans le vide, on désélectionne tout dans l'arbre
            if event_dict is None:
                self.tree_captures.clearSelection()
                return

            valeur_cible = event_dict.get("title", "").replace("Pic: ", "")
            
            # 2. Parcourir l'arbre pour chercher la ligne correspondante
            ligne_trouvee = False
            for i in range(self.tree_captures.topLevelItemCount()):
                item = self.tree_captures.topLevelItem(i)
                
                # On compare avec le titre propre de la colonne 3
                if item and item.text(3) == valeur_cible:
                    self.tree_captures.clearSelection()
                    item.setSelected(True)
                    # Fait défiler l'arbre automatiquement jusqu'à la ligne sélectionnée si besoin
                    self.tree_captures.scrollToItem(item, QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible)
                    ligne_trouvee = True
                    break
                    
            if not ligne_trouvee:
                self.tree_captures.clearSelection()
        finally:
            # Réactiver les signaux
            self.tree_captures.blockSignals(False)

    def filtrer_les_videos_poubelle(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        index_nom = self.video_model.index(source_row, 0, source_parent)
        video_path = self.video_model.data(index_nom, QtCore.Qt.ItemDataRole.UserRole)
        return "trash" not in os.path.normpath(video_path).split(os.sep) if video_path else True

    def initialiser_list_event_layout(self):
        """Initialise le QTreeWidget unique et remis à zéro dans list_event_container."""
        if not self.list_event_container:
            print("[ERREUR] list_event_container introuvable.")
            return
        
        if self.list_event_container.layout() is not None:
            layout_principal = self.list_event_container.layout()
            while layout_principal.count():
                enfant = layout_principal.takeAt(0)
                if enfant.widget():
                    enfant.widget().deleteLater()
        else:
            layout_principal = QtWidgets.QHBoxLayout(self.list_event_container)
            layout_principal.setContentsMargins(5, 5, 5, 5)
            layout_principal.setSpacing(0)

        self.tree_captures = QtWidgets.QTreeWidget()
        # --- PASSER DE 5 A 6 COLONNES ---
        self.tree_captures.setColumnCount(6)
        self.tree_captures.setHeaderLabels(self._get_tree_headers())
        
        self.tree_captures.setColumnWidth(0, 130)
        self.tree_captures.setColumnWidth(1, 90)
        self.tree_captures.setColumnWidth(2, 150)
        self.tree_captures.setColumnWidth(3, 130)
        self.tree_captures.setColumnWidth(4, 180) # Largeur colonne commentaire

        self.tree_captures.setStyleSheet("""
            QTreeWidget { background-color: #1e1e1e; color: white; border: 1px solid #2778a2; border-radius: 4px; }
            QHeaderView::section { background-color: #20415d; color: white; font-weight: bold; border: 1px solid #2778a2; }
            QTreeWidget::item { height: 40px; } 
        """)
        
        self.tree_captures.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_captures.customContextMenuRequested.connect(
            lambda pos: self.ouvrir_menu_contextuel(pos, self.tree_captures)
        )
        
        self.tree_captures.itemSelectionChanged.connect(self.sur_evenement_arbre_selectionne)

        layout_principal.addWidget(self.tree_captures)

    # =========================================================================
    # LOGIQUE DE PERSISTANCE JSON AVEC CALCULS DE FRAMES (BACKEND)
    # =========================================================================
    
    def _obtenir_fps_video(self) -> float:
        """Récupère dynamiquement le FPS du lecteur vidéo ou 25 par défaut."""
        if hasattr(self, 'lecteur_events') and self.lecteur_events is not None:
            if hasattr(self.lecteur_events, 'video_fps') and isinstance(self.lecteur_events.video_fps, (int, float)) and self.lecteur_events.video_fps > 0:
                return float(self.lecteur_events.video_fps)
        return 25.0  # Sécurité standard pour le calcul

    def _ms_vers_frame(self, ms: int, fps: float) -> int:
        """Convertit les millisecondes récoltées en numéro de frame 1-based."""
        if fps <= 0:
            return 0
        return max(1, int(round((ms / 1000.0) * fps)))

    def _get_json_key_from_label(self, label_affiche: str) -> str:
        if not label_affiche:
            return "events_custom"

        if hasattr(self, 'event_key_by_label') and label_affiche in self.event_key_by_label:
            return self.event_key_by_label[label_affiche]

        lower_label = label_affiche.lower()
        if "deployment" in lower_label or "déploiement" in lower_label:
            return "events_deployment"
        if "animal" in lower_label or "faune" in lower_label:
            return "events_animal"
        if "interesting_images" in lower_label or "interesting image" in lower_label or "images intéressantes" in lower_label or "image" in lower_label:
            return "events_interesting_images"
        return "events_custom"

    def _get_label_from_json_key(self, json_key: str) -> str:
        if hasattr(self, 'event_category_labels') and json_key in self.event_category_labels:
            return self.event_category_labels[json_key]

        if self.current_language == 'en':
            mapping = {
                "events_deployment": "Deployment",
                "events_animal": "Fauna / Animal",
                "events_interesting_images": "Interesting Image"
            }
        else:
            mapping = {
                "events_deployment": "Déploiement",
                "events_animal": "Faune / Animal",
                "events_interesting_images": "Image Intéressante"
            }
        return mapping.get(json_key, json_key)

    def _generate_event_uid(self) -> str:
        return str(uuid.uuid4())

    def _ensure_event_uid(self, event_dict: dict) -> str:
        if not event_dict.get("_event_uid"):
            event_dict["_event_uid"] = self._generate_event_uid()
        return event_dict["_event_uid"]

    def _build_event_categories_from_json(self, data: dict):
        self.event_category_labels = {}
        self.event_key_by_label = {}
        self.dictionnaire_evenements.clear()

        if not isinstance(data, dict):
            return

        video_obs = data.get("video_observation", {})
        if not isinstance(video_obs, dict):
            return

        for cle_json, valeur in video_obs.items():
            if not isinstance(cle_json, str) or not cle_json.startswith("events_"):
                continue
            if not isinstance(valeur, list) or not valeur:
                continue

            premier_objet = valeur[0]
            if not isinstance(premier_objet, dict):
                continue

            if self.current_language == 'en':
                valeurs_autorisees = premier_objet.get("authorized_values_en") or premier_objet.get("authorized_values_fr") or []
            else:
                valeurs_autorisees = premier_objet.get("authorized_values_fr") or premier_objet.get("authorized_values_en") or []

            if not isinstance(valeurs_autorisees, list):
                continue

            label = self._get_label_from_json_key(cle_json)
            self.event_category_labels[cle_json] = label
            self.event_key_by_label[label] = cle_json
            self.dictionnaire_evenements[label] = [str(v) for v in valeurs_autorisees if v is not None]

    def _get_tree_headers(self) -> list[str]:
        if self.current_language == 'en':
            return ["Start / Capture time", "End", "Event type", "Value", "Comment", "Preview"]
        return ["Début / Heure Capture", "Fin", "Type d'événement", "Valeur", "Commentaire", "Aperçu"]

    def set_language(self, langue: str):
        self.current_language = langue
        if hasattr(self, 'tree_captures') and self.tree_captures is not None:
            self.tree_captures.setHeaderLabels(self._get_tree_headers())

    def sauvegarder_evenement_dans_json(self, event_dict: dict, type_affiche: str):
        """Sauvegarde ou met à jour l'événement en écrivant les index de frames calculés."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return

        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if "video_observation" not in data:
                data["video_observation"] = {}

            # Si l'événement stocke sa clé JSON réelle, l'utiliser ; sinon extraire du label
            if "_json_key" in event_dict and event_dict["_json_key"]:
                cle_json = event_dict["_json_key"]
            else:
                cle_json = self._get_json_key_from_label(type_affiche)

            # VALIDATION: Les événements de déploiement (atterrissage/décollage) doivent toujours aller dans events_deployment
            valeur_titre = event_dict.get("title", "").replace("Pic: ", "").strip().lower()
            if any(keyword in valeur_titre for keyword in ["atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff"]):
                cle_json = "events_deployment"
                event_dict["_json_key"] = "events_deployment"
                print(f"[BACKEND] Événement de déploiement '{valeur_titre}' forcé dans events_deployment")
            
            if cle_json not in data["video_observation"]:
                data["video_observation"][cle_json] = [{"authorized_values_fr": self.dictionnaire_evenements.get(type_affiche, []), "values": []}]
            elif not data["video_observation"][cle_json]:
                data["video_observation"][cle_json] = [{"authorized_values_fr": self.dictionnaire_evenements.get(type_affiche, []), "values": []}]

            # --- CALCUL DU FRAME NUMBER VIA LES FPS ---
            fps = self._obtenir_fps_video()
            frame_start = self._ms_vers_frame(event_dict["start"], fps)
            frame_end = self._ms_vers_frame(event_dict["end"], fps)

            event_uid = self._ensure_event_uid(event_dict)
            valeur_sauvegarde = {
                "event_id": event_uid,
                "time_code_start": self.lecteur_events.timeline._format_ms(event_dict["start"]),
                "time_code_end": self.lecteur_events.timeline._format_ms(event_dict["end"]),
                "frame_number_start": frame_start,
                "frame_number_end": frame_end,
                "description_fr": None,
                "description_en": None,
                "value": event_dict["title"].replace("Pic: ", ""),
                "comment": event_dict.get("comment", "")
            }

            values_list = data["video_observation"][cle_json][0].get("values", [])
            
            # --- LOGIQUE DE DÉTECTION DES DOUBLONS AMÉLIORÉE ---
            existing_index = -1
            event_uid = event_dict.get("_event_uid")

            if event_uid is not None:
                for idx, val in enumerate(values_list):
                    if val.get("event_id") == event_uid:
                        existing_index = idx
                        break

            old_start_ms = event_dict.get("_old_start")
            old_end_ms = event_dict.get("_old_end")
            old_frame_start = None
            old_frame_end = None

            if existing_index == -1 and old_start_ms is not None:
                old_frame_start = self._ms_vers_frame(old_start_ms, fps)
                old_frame_end = self._ms_vers_frame(old_end_ms if old_end_ms is not None else old_start_ms, fps)
                for idx, val in enumerate(values_list):
                    if val.get("value") == valeur_sauvegarde["value"]:
                        if val.get("frame_number_start") == old_frame_start and val.get("frame_number_end") == old_frame_end:
                            existing_index = idx
                            break

            if existing_index == -1 and old_frame_start is not None:
                # Si l'événement a été déplacé vers une autre catégorie, rechercher l'entrée originelle
                for other_key, other_value in data["video_observation"].items():
                    if other_key == cle_json or not isinstance(other_value, list) or not other_value:
                        continue
                    other_values = other_value[0].get("values", [])
                    for other_idx, other_val in enumerate(other_values):
                        if other_val.get("value") == valeur_sauvegarde["value"] and \
                                other_val.get("frame_number_start") == old_frame_start and \
                                other_val.get("frame_number_end") == old_frame_end:
                            other_values.pop(other_idx)
                            data["video_observation"][other_key][0]["values"] = other_values
                            values_list.append(valeur_sauvegarde)
                            existing_index = len(values_list) - 1
                            break
                    if existing_index != -1:
                        break

            if existing_index == -1:
                tolerance_frames = max(1, int(fps * 0.25))  # Tolérance de 250ms en frames
                for idx, val in enumerate(values_list):
                    if val.get("event_id") == event_uid:
                        existing_index = idx
                        break
                    if val.get("value") == valeur_sauvegarde["value"]:
                        existing_frame_start = val.get("frame_number_start", 0)
                        if abs(existing_frame_start - frame_start) <= tolerance_frames:
                            existing_index = idx
                            break

            if existing_index != -1:
                values_list[existing_index] = valeur_sauvegarde
            else:
                values_list.append(valeur_sauvegarde)

            data["video_observation"][cle_json][0]["values"] = values_list
            event_dict.pop("_old_start", None)
            event_dict.pop("_old_end", None)
            
            # Mémoriser la clé JSON réelle dans l'événement pour les modifications ultérieures
            event_dict["_json_key"] = cle_json

            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

        except Exception as e:
            print(f"[BACKEND] Erreur lors de l'écriture dans le JSON : {e}")

    def supprimer_evenement_du_json(self, event_dict: dict):
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            video_obs = data.get("video_observation", {})
            valeur_cible = event_dict["title"].replace("Pic: ", "")
            fps = self._obtenir_fps_video()
            frame_start_cible = self._ms_vers_frame(event_dict["start"], fps)
            tolerance_frames = max(1, int(fps * 0.25))  # Tolérance de 250ms

            for cle_json in ["events_deployment", "events_animal", "events_interesting_images"]:
                if cle_json in video_obs and video_obs[cle_json]:
                    values_list = video_obs[cle_json][0].get("values", [])
                    # Filtre en se basant sur la valeur ET une position proche (tolérance)
                    nouvelle_liste = []
                    for v in values_list:
                        v_frame_start = v.get("frame_number_start", 0)
                        # Ne supprime que si la valeur correspond ET la position est proche
                        if v.get("value") == valeur_cible and abs(v_frame_start - frame_start_cible) <= tolerance_frames:
                            # Cet événement sera supprimé - on ne l'ajoute pas
                            print(f"[DEBUG] Suppression: '{valeur_cible}' frame {v_frame_start} (tolérance: {tolerance_frames})")
                            continue
                        nouvelle_liste.append(v)
                    video_obs[cle_json][0]["values"] = nouvelle_liste

            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

        except Exception as e:
            print(f"[BACKEND] Erreur lors de la suppression dans le JSON : {e}")

    # =========================================================================
    # GESTION DES MINIATURES SÉCURISÉES AVEC UTILS2
    # =========================================================================
    
    def ajouter_miniature_arbre(self, item_arbre: QtWidgets.QTreeWidgetItem, timestamp_ms: int):
        """Utilise le module métier dédié utils2 pour récupérer l'image exacte."""
        label_miniature = QtWidgets.QLabel()
        label_miniature.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label_miniature.setStyleSheet("background-color: black; margin: 2px; border-radius: 2px;")
        
        pixmap_vignette = None
        if self.current_video_path and os.path.exists(self.current_video_path):
            frame_rgb = extract_frame_at_time(self.current_video_path, timestamp_ms / 1000.0)
            
            if frame_rgb is not None:
                hauteur, largeur, canaux = frame_rgb.shape
                bytes_per_line = canaux * largeur
                q_img = QtGui.QImage(frame_rgb.data, largeur, hauteur, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
                pixmap_vignette = QtGui.QPixmap.fromImage(q_img)

        if pixmap_vignette and not pixmap_vignette.isNull():
            label_miniature.setPixmap(pixmap_vignette.scaled(60, 34, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation))
        else:
            label_miniature.setText("N/A")
            label_miniature.setStyleSheet("color: gray; font-size: 9px; font-weight: bold;")

        # --- ICI : CHANGEMENT DE 4 A 5 ---
        self.tree_captures.setItemWidget(item_arbre, 5, label_miniature)

    # =========================================================================
    # INTERFACES ET SELECTIONS ACTIONS
    # =========================================================================

    def ouvrir_menu_contextuel(self, position, emetteur):
        event_dict = None
        item_arbre_cible = None

        if emetteur == self.tree_captures:
            item = self.tree_captures.itemAt(position)
            if item:
                item_arbre_cible = item
                valeur_titre = item.text(3) 
                for evt in self.lecteur_events.timeline.events:
                    if evt.get("title") == valeur_titre or evt.get("title") == f"Pic: {valeur_titre}":
                        event_dict = evt
                        break

        elif emetteur == self.lecteur_events.timeline:
            event_dict = self.lecteur_events.timeline.get_event_at_position(position)
            if event_dict:
                valeur_titre = event_dict.get("title", "").replace("Pic: ", "")
                for i in range(self.tree_captures.topLevelItemCount()):
                    item = self.tree_captures.topLevelItem(i)
                    if item.text(3) == valeur_titre:
                        item_arbre_cible = item
                        break

        if not event_dict:
            return

        menu = QtWidgets.QMenu(self.page)
        menu.setStyleSheet("""
            QMenu { background-color: #2b2b2b; color: white; border: 1px solid #2778a2; }
            QMenu::item { padding: 6px 20px 6px 20px; }
            QMenu::item:selected { background-color: #20415d; color: #f09624; }
        """)

        action_supprimer = menu.addAction("❌ Supprimer l'événement")
        action_choisie = menu.exec(emetteur.mapToGlobal(position))

        if action_choisie == action_supprimer:
            self.supprimer_evenement_unifie(event_dict, item_arbre_cible)

    def supprimer_evenement_unifie(self, event_dict: dict, item_arbre: QtWidgets.QTreeWidgetItem):
        if event_dict in self.lecteur_events.timeline.events:
            self.lecteur_events.timeline.events.remove(event_dict)
            self.lecteur_events.timeline.update()

        if item_arbre:
            index_top = self.tree_captures.indexOfTopLevelItem(item_arbre)
            if index_top != -1:
                self.tree_captures.takeTopLevelItem(index_top)

        self.supprimer_evenement_du_json(event_dict)

    def rafraichir_liste_evenements(self, event_modifie: dict):
        if not hasattr(self, 'tree_captures') or self.tree_captures is None:
            return
        
        self.tree_captures.blockSignals(True)
        valeur_cible = event_modifie.get("title", "").replace("Pic: ", "")
        
        for i in range(self.tree_captures.topLevelItemCount()):
            item = self.tree_captures.topLevelItem(i)
            # On compare avec la valeur stockée dans la colonne 3
            if item.text(3) == valeur_cible:
                # 1. Extraction et formatage des nouveaux temps de la timeline
                nouveau_start = event_modifie.get("start", 0)
                nouveau_end = event_modifie.get("end", 0)
                
                txt_start = self.lecteur_events.timeline._format_ms(nouveau_start)
                txt_end = self.lecteur_events.timeline._format_ms(nouveau_end)
                
                # 2. Mise à jour des colonnes de texte
                item.setText(0, txt_start)
                item.setText(1, "-" if nouveau_start == nouveau_end or "Pic:" in event_modifie.get("title", "") else txt_end)
                
                # 3. MISE A JOUR DE LA MINIATURE (L'événement ayant bougé, l'image change sur la colonne 5)
                self.ajouter_miniature_arbre(item, nouveau_start)
                break
                
        self.tree_captures.blockSignals(False)
        
        # 4. Forcer le rafraîchissement visuel du widget de l'arbre
        self.tree_captures.viewport().update()
        
        # 5. Sauvegarde des nouvelles coordonnées temporelles dans le fichier JSON
        # IMPORTANT: Utiliser le type réel de l'événement (stocké dans _json_key), pas le type du combo
        type_affiche = self.combo_type_event.currentText()
        if "_json_key" in event_modifie:
            # Reconvertir la clé JSON en label pour la compatibilité avec sauvegarder_evenement_dans_json
            json_key = event_modifie["_json_key"]
            type_affiche_correct = self._get_label_from_json_key(json_key)
            if self.current_language == 'en':
                # Ajouter le suffixe avec la clé JSON pour la correspondance exacte
                if json_key == "events_deployment":
                    type_affiche_correct = "Deployment (events_deployment)"
                elif json_key == "events_animal":
                    type_affiche_correct = "Fauna / Animal (events_animal)"
                elif json_key == "events_interesting_images":
                    type_affiche_correct = "Interesting Images (events_interesting_images)"
            else:
                if json_key == "events_deployment":
                    type_affiche_correct = "Déploiement (events_deployment)"
                elif json_key == "events_animal":
                    type_affiche_correct = "Faune / Animal (events_animal)"
                elif json_key == "events_interesting_images":
                    type_affiche_correct = "Images Intéressantes (events_interesting_images)"
            type_affiche = type_affiche_correct
        self.sauvegarder_evenement_dans_json(event_modifie, type_affiche)

    def initialiser_menus_deroulants_evenements(self):
        if not self.choose_event_container:
            return

        if self.choose_event_container.layout() is None:
            layout_menu = QtWidgets.QVBoxLayout(self.choose_event_container)
        else:
            layout_menu = self.choose_event_container.layout()

        layout_menu.setContentsMargins(16, 16, 16, 16)
        layout_menu.setSpacing(14)

        self.choose_event_container.setStyleSheet(
            "QFrame { background-color: #181c24; border: 1px solid #2778a2; border-radius: 14px; }"
        )

        style_combo = """
            QComboBox { background-color: #212a35; color: white; border: 1px solid #2778a2; border-radius: 8px; padding: 8px; }
            QComboBox QAbstractItemView { background-color: #212a35; color: white; selection-background-color: #2778a2; }
        """
        style_bouton_action = """
            QPushButton { background-color: #e68c14; color: white; font-weight: bold; border: 1px solid #f09624; border-radius: 8px; padding: 10px; }
            QPushButton:hover { background-color: #f09624; }
            QPushButton:disabled { background-color: #454545; color: #888888; border: 1px solid #555555; }
        """
        style_label = "color: white; font-weight: bold;"
        style_title = "font-size: 14px; font-weight: bold; color: #ffffff;"
        style_subtitle = "color: #aaaaaa;"

        if not hasattr(self, 'combo_type_event') or self.combo_type_event is None:
            self.lbl_title_event = QtWidgets.QLabel("Sélection d'événement")
            self.lbl_title_event.setStyleSheet(style_title)
            self.lbl_title_event.setContentsMargins(0, 0, 0, 0)

            self.lbl_subtitle_event = QtWidgets.QLabel("Choisissez le type et la valeur, ajoutez un commentaire si besoin, puis capturez.")
            self.lbl_subtitle_event.setStyleSheet(style_subtitle)
            self.lbl_subtitle_event.setWordWrap(True)

            self.lbl_type_event = QtWidgets.QLabel("Type d'événement")
            self.lbl_type_event.setStyleSheet(style_label)
            self.combo_type_event = QtWidgets.QComboBox()
            self.combo_type_event.setStyleSheet(style_combo)
            self.combo_type_event.setMinimumWidth(220)
            self.combo_type_event.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

            self.lbl_valeur_event = QtWidgets.QLabel("Caractéristiques")
            self.lbl_valeur_event.setStyleSheet(style_label)
            self.combo_valeur_event = QtWidgets.QComboBox()
            self.combo_valeur_event.setStyleSheet(style_combo)
            self.combo_valeur_event.setMinimumWidth(220)
            self.combo_valeur_event.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

            # Zone de saisie pour ajouter un commentaire à la volée avant capture
            self.lbl_commentaire_input = QtWidgets.QLabel("Commentaire rapide")
            self.lbl_commentaire_input.setStyleSheet(style_label)
            self.input_commentaire_event = QtWidgets.QLineEdit()
            self.input_commentaire_event.setPlaceholderText("Écrire un commentaire ici...")
            self.input_commentaire_event.setStyleSheet("""
                QLineEdit { background-color: #212a35; color: white; border: 1px solid #2778a2; border-radius: 8px; padding: 8px; }
            """)

            self.btn_capturer = QtWidgets.QPushButton("CAPTURER ÉVÉNEMENT")
            self.btn_capturer.setStyleSheet(style_bouton_action)
            self.btn_capturer.setMinimumHeight(38)
            self.btn_finir = QtWidgets.QPushButton("FINIR ÉVÉNEMENT")
            self.btn_finir.setStyleSheet(style_bouton_action)
            self.btn_finir.setMinimumHeight(38)
            self.btn_finir.setEnabled(False)

            layout_menu.addWidget(self.lbl_title_event)
            layout_menu.addWidget(self.lbl_subtitle_event)

            form_layout = QtWidgets.QFormLayout()
            form_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            form_layout.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            form_layout.setSpacing(12)
            form_layout.setContentsMargins(0, 0, 0, 0)
            form_layout.addRow(self.lbl_type_event, self.combo_type_event)
            form_layout.addRow(self.lbl_valeur_event, self.combo_valeur_event)
            form_layout.addRow(self.lbl_commentaire_input, self.input_commentaire_event)
            layout_menu.addLayout(form_layout)

            bouton_layout = QtWidgets.QHBoxLayout()
            bouton_layout.setSpacing(10)
            bouton_layout.addWidget(self.btn_capturer)
            bouton_layout.addWidget(self.btn_finir)
            layout_menu.addLayout(bouton_layout)

            self.combo_type_event.currentTextChanged.connect(self.on_type_event_changed)
            self.combo_valeur_event.currentTextChanged.connect(self.on_value_event_changed)
            self.btn_capturer.clicked.connect(self.on_capturer_clicked)
            self.btn_finir.clicked.connect(self.on_finir_clicked)

    def on_type_event_changed(self, type_selectionne: str):
        if not type_selectionne or type_selectionne not in self.dictionnaire_evenements:
            return
        self.combo_valeur_event.blockSignals(True)
        self.combo_valeur_event.clear()
        valeurs_associees = self.dictionnaire_evenements[type_selectionne]
        self.combo_valeur_event.addItems([str(v) for v in valeurs_associees if v is not None])
        self.combo_valeur_event.blockSignals(False)
        self._update_capture_mode()

    def on_value_event_changed(self, valeur_selectionnee: str):
        self._update_capture_mode()

    def _is_single_frame_event(self, type_selectionne: str, valeur: str = "") -> bool:
        if not type_selectionne:
            return False
        type_lower = type_selectionne.lower()
        valeur_lower = (valeur or "").strip().lower()
        if "interesting_images" in type_lower or "image" in type_lower:
            return True
        if any(keyword in valeur_lower for keyword in ["atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff"]):
            return True
        return False

    def _is_landing_event(self, valeur: str) -> bool:
        valeur_lower = (valeur or "").strip().lower()
        return any(keyword in valeur_lower for keyword in ["atterrissage", "atterissage", "landing"])

    def _is_takeoff_event(self, valeur: str) -> bool:
        valeur_lower = (valeur or "").strip().lower()
        return any(keyword in valeur_lower for keyword in ["décollage", "decollage", "takeoff"])

    def _single_frame_event_conflict(self, type_selectionne: str, valeur: str) -> str | None:
        if not self._is_single_frame_event(type_selectionne, valeur):
            return None
        if not hasattr(self, 'lecteur_events') or not getattr(self.lecteur_events, 'timeline', None):
            return None

        for evt in self.lecteur_events.timeline.events:
            if not isinstance(evt, dict):
                continue
            title = str(evt.get('title', '')).replace('Pic: ', '').strip()
            if self._is_landing_event(valeur) and self._is_landing_event(title):
                return 'atterrissage'
            if self._is_takeoff_event(valeur) and self._is_takeoff_event(title):
                return 'décollage'
        return None

    def _update_capture_mode(self):
        current_type = self.combo_type_event.currentText()
        current_value = self.combo_valeur_event.currentText() if hasattr(self, 'combo_valeur_event') else ""
        if self._is_single_frame_event(current_type, current_value):
            self.btn_capturer.setText("CAPTURER")
            self.btn_finir.setVisible(False)
            self.btn_finir.setEnabled(False)
            if self.temps_debut_capture is not None:
                self.temps_debut_capture = None
        else:
            self.btn_capturer.setText("CAPTURER ÉVÉNEMENT")
            self.btn_finir.setVisible(True)
            self.btn_finir.setEnabled(False)

    def initialiser_export_ui(self):
        if not self.export_container:
            return
        if self.export_container.layout() is None:
            export_layout = QtWidgets.QVBoxLayout(self.export_container)
            export_layout.setContentsMargins(14, 14, 14, 14)
            export_layout.setSpacing(12)
        else:
            export_layout = self.export_container.layout()
            export_layout.setContentsMargins(14, 14, 14, 14)
            export_layout.setSpacing(12)

        # --- Bouton Exporter le Segment (Images) ---
        self.export_button = QtWidgets.QPushButton("EXPORTER EVENEMENTS", self.export_container)
        self.export_button.setStyleSheet(
            "QPushButton { background-color: #e68c14; color: white; font-weight: bold; border: 1px solid #f09624; border-radius: 8px; padding: 12px; }"
            "QPushButton:hover { background-color: #f09624; }"
        )
        self.export_button.setEnabled(False)

        # Barre de progression pour l'export (segment)
        self.export_progress = QtWidgets.QProgressBar(self.export_container)
        self.export_progress.setMinimum(0)
        self.export_progress.setMaximum(100)
        self.export_progress.setValue(0)
        self.export_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #e68c14; border-radius: 4px; background-color: #2a2a2a; }"
            "QProgressBar::chunk { background-color: #e68c14; }"
        )
        self.export_progress.setVisible(False)

        self.export_status_label = QtWidgets.QLabel("", self.export_container)
        self.export_status_label.setWordWrap(True)
        self.export_status_label.setStyleSheet("color: white; font-size: 12px;")

        # Ajout des widgets au layout
        export_layout.addWidget(self.export_button)
        export_layout.addWidget(self.export_progress)
        export_layout.addWidget(self.export_status_label)
        export_layout.addStretch(1)

        # Connexions des signaux
        self.export_button.clicked.connect(self.on_export_segment_clicked)
        self.export_worker = None


    def _update_export_button_state(self):
        """Active ou désactive les boutons d'export selon qu'une vidéo est chargée (Version Unique)."""
        has_video = bool(self.current_video_path)
        if hasattr(self, 'export_button') and self.export_button is not None:
            self.export_button.setEnabled(has_video)


    def _find_landing_takeoff_events(self):
        landing_event = None
        takeoff_event = None
        if not hasattr(self, 'lecteur_events') or not getattr(self.lecteur_events, 'timeline', None):
            return None, None

        for evt in self.lecteur_events.timeline.events:
            if not evt or not isinstance(evt, dict):
                continue
            title = str(evt.get('title', '')).replace('Pic: ', '').strip()
            if self._is_landing_event(title):
                landing_event = evt
            elif self._is_takeoff_event(title):
                takeoff_event = evt
        return landing_event, takeoff_event


    def _get_export_segment_bounds(self):
        """Lit les bornes d'export depuis template.json (frame_number_start de atterrissage et décollage)"""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            return None
        
        # Chercher template.json dans le dossier parent
        dossier_parent = os.path.dirname(self.current_video_path)
        template_json_path = os.path.normpath(os.path.join(dossier_parent, "template.json"))
        
        if not os.path.exists(template_json_path):
            print(f"[EXPORT] template.json non trouvé à : {template_json_path}")
            return None
        
        try:
            with open(template_json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # Récupérer les événements de déploiement
            video_obs = json_data.get('video_observation', {})
            events_deployment = video_obs.get('events_deployment', [])
            
            if not isinstance(events_deployment, list) or len(events_deployment) == 0:
                print("[EXPORT] Pas d'événements de déploiement dans template.json")
                return None
            
            values = events_deployment[0].get('values', [])
            landing_frame = None
            takeoff_frame = None
            
            # Chercher atterrissage et décollage
            for event_item in values:
                event_value = str(event_item.get('value', '')).strip().lower()
                if event_value in ('atterrissage', 'landing'):
                    landing_frame = event_item.get('frame_number_start')
                elif event_value in ('décollage', 'take_off', 'takeoff'):
                    takeoff_frame = event_item.get('frame_number_start')
            
            if landing_frame is None or takeoff_frame is None:
                print(f"[EXPORT] Événements manquants - Landing: {landing_frame}, Takeoff: {takeoff_frame}")
                return None
            
            try:
                landing_frame = int(landing_frame)
                takeoff_frame = int(takeoff_frame)
            except Exception:
                return None
            
            # Obtenir le FPS de la vidéo
            cap = cv2.VideoCapture(self.current_video_path)
            video_fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            
            if video_fps <= 0:
                video_fps = 25.0
            
            # Convertir les frame numbers en ms (frame 1 = 0ms)
            start_ms = ((float(landing_frame) - 1.0) / float(video_fps)) * 1000.0
            end_ms = ((float(takeoff_frame) - 1.0) / float(video_fps)) * 1000.0
            
            print(f"[EXPORT] Bornes calculées: frame {landing_frame}-{takeoff_frame} → {start_ms:.0f}ms-{end_ms:.0f}ms (fps={video_fps})")
            
            return start_ms, end_ms
            
        except Exception as e:
            print(f"[EXPORT] Erreur lors de la lecture de template.json : {e}")
            return None


    def on_export_segment_clicked(self):
        """
        Exportation avec options:
        - Affiche la fenêtre de dialogue pour configurer FPS et filtres
        - Crée un dossier img/ avec les images entre l'atterrissage et le décollage
        - Crée un CSV uniquement avec les événements contenus dans ce segment temporel
        """
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            QtWidgets.QMessageBox.warning(self.page, "Exportación imposible", "No se ha seleccionado ningún video.")
            return

        if not hasattr(self, 'lecteur_events') or not getattr(self.lecteur_events, 'timeline', None):
            QtWidgets.QMessageBox.warning(self.page, "Exportación imposible", "No se puede acceder a los eventos.")
            return

        bounds = self._get_export_segment_bounds()
        if bounds is None:
            QtWidgets.QMessageBox.warning(self.page, "Exportación imposible", "Faltan las etiquetas de aterrizaje/despegue.")
            return

        # Mostrar la ventana de diálogo para las opciones de exportación
        dialog = ExportOptionsDialog(self.page)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return  # El usuario canceló

        # Recuperar las opciones seleccionadas
        options = dialog.get_processing_options()
        target_fps = options.get("target_fps", 5)
        apply_he = options.get("apply_he", False)
        apply_dh = options.get("apply_dh", False)
        is_water = options.get("is_water", False)

        start_ms, end_ms = bounds
        dossier_video_parent = os.path.dirname(self.current_video_path)

        # Stocker les bornes d'export pour le CSV generator
        self.export_start_ms = start_ms
        self.export_end_ms = end_ms

        # Actualización de la interfaz de usuario
        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)
        self.export_status_label.setText(f"Exportation en cours à {target_fps} FPS...")
        self.export_button.setEnabled(False)

        # Lanzamiento del worker de exportación sin eventos
        self.export_worker = ExportWorker(
            video_path=self.current_video_path,
            base_output_dir=dossier_video_parent,
            start_ms=start_ms,
            end_ms=end_ms,
            target_fps=target_fps,
            events=[],
            apply_he=apply_he,
            apply_dh=apply_dh,
            is_water=is_water
        )
        
        self.export_worker.progress_updated.connect(self._on_export_progress)
        self.export_worker.export_finished.connect(self._on_export_finished)
        self.export_worker.export_error.connect(self._on_export_error)
        
        self.export_worker.start()


    def _on_export_progress(self, progress: int):
        """Met à jour la barre de progression"""
        if hasattr(self, 'export_progress') and self.export_progress is not None:
            self.export_progress.setValue(progress)


    def _on_export_finished(self, saved_count: int):
        """Appelé quand l'export est terminé avec succès"""
        message = f"✓ Export images terminé : {saved_count} images enregistrées."
        
        # Générer le CSV d'événements avec les bornes d'export stockées
        dossier_parent = os.path.dirname(self.current_video_path)
        events_csv_generated = self._generate_events_csv(dossier_parent, self.export_start_ms, self.export_end_ms)
        
        if events_csv_generated:
            message += "\n✓ CSV événements généré."
        
        if hasattr(self, 'export_status_label') and self.export_status_label is not None:
            self.export_status_label.setText(message)
        if hasattr(self, 'export_button') and self.export_button is not None:
            self.export_button.setEnabled(bool(self.current_video_path))
        if hasattr(self, 'export_progress') and self.export_progress is not None:
            self.export_progress.setVisible(False)

    def _generate_events_csv(self, dossier_parent, start_ms, end_ms):
        """Génère le CSV événements VIAME : une ligne par événement dans chaque frame exportée"""
        template_json_path = os.path.normpath(os.path.join(dossier_parent, "template.json"))
        events_csv_path = os.path.normpath(os.path.join(dossier_parent, "events.csv"))
        img_dir = os.path.normpath(os.path.join(dossier_parent, "img"))
        
        if not os.path.exists(template_json_path):
            print(f"[CSV] template.json non trouvé")
            return False
        
        if not os.path.exists(img_dir):
            print(f"[CSV] Dossier img/ non trouvé")
            return False
        
        try:
            with open(template_json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # Obtenir le FPS de la vidéo
            cap = cv2.VideoCapture(self.current_video_path)
            video_fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            
            if video_fps <= 0:
                video_fps = 25.0
            
            # Calculer start_frame et frame_interval théoriques
            start_frame = int((start_ms / 1000.0) * video_fps) + 1
            target_fps = 5
            frame_interval = max(1, int(video_fps / target_fps))
            
            video_obs = json_data.get('video_observation', {})
            
            # Lister toutes les images exportées et les trier
            exported_images = []  # liste : (seq_num, img_filename)
            for img_name in sorted(os.listdir(img_dir)):
                if img_name.endswith('.jpg'):
                    try:
                        seq_num = int(os.path.splitext(img_name)[0])
                        exported_images.append((seq_num, img_name))
                    except ValueError:
                        pass
            
            if not exported_images:
                print(f"[CSV] Aucune image trouvée dans {img_dir}")
                return False
            
            # Créer un mapping seq_num -> img_filename
            seq_to_image = {}
            for seq_num, img_filename in exported_images:
                seq_to_image[seq_num] = img_filename
            
            # Récupérer les première et dernière images
            first_seq = exported_images[0][0]
            last_seq = exported_images[-1][0]
            total_images = len(exported_images)
            
            # Lire TOUS les événements du JSON
            events_list = []  # Liste : (track_id, frame_start, frame_end, event_name)
            track_id = 0
            
            for category in ['events_deployment', 'events_animal', 'events_interesting_images']:
                events_cat = video_obs.get(category, [])
                if isinstance(events_cat, list) and len(events_cat) > 0:
                    values = events_cat[0].get('values', [])
                    for event_item in values:
                        frame_start = event_item.get('frame_number_start')
                        frame_end = event_item.get('frame_number_end')
                        event_name = str(event_item.get('value', 'unknown')).strip()
                        
                        if frame_start is not None:
                            frame_start = int(frame_start)
                            frame_end = int(frame_end) if (frame_end is not None and int(frame_end) >= frame_start) else frame_start
                            events_list.append((track_id, frame_start, frame_end, event_name))
                            track_id += 1
            
            # Déduire le vrai start_frame (Atterrissage)
            deduced_start_frame = start_frame
            deduced_frame_interval = frame_interval
            
            for track_id_ev, frame_start_ev, frame_end_ev, event_name_ev in events_list:
                if 'atterrissage' in event_name_ev.lower():
                    deduced_start_frame = frame_start_ev
                    break
            
            # Calcul du frame_interval basé sur la durée totale entre l'Atterrissage et le Décollage
            # Cela garantit que le décollage tombe PILE sur la dernière image exportée
            frame_décollage = None
            for track_id_ev, frame_start_ev, frame_end_ev, event_name_ev in events_list:
                if 'décollage' in event_name_ev.lower() or 'decollage' in event_name_ev.lower():
                    frame_décollage = frame_end_ev
                    break
            
            if frame_décollage and frame_décollage > deduced_start_frame and last_seq > first_seq:
                deduced_frame_interval = (frame_décollage - deduced_start_frame) / (last_seq - first_seq)
                print(f"[DEBUG] Intervalle ajusté sur le Décollage : {deduced_frame_interval:.2f}")
            elif last_seq > first_seq and len(events_list) > 0:
                max_frame = max(frame_end for _, _, frame_end, _ in events_list)
                if max_frame > deduced_start_frame:
                    deduced_frame_interval = (max_frame - deduced_start_frame) / (last_seq - first_seq)
            
            if deduced_frame_interval <= 0:
                deduced_frame_interval = frame_interval

            # Charger les événements moteurs
            motor_events = []
            system_event_path = os.path.normpath(os.path.join(dossier_parent, "systemEvent.csv"))
            if os.path.exists(system_event_path):
                try:
                    motor_events = get_motor_stable_timestamps(system_event_path, delay=6.0, start_track_id=track_id)
                    print(f"[CSV] {len(motor_events)} événements moteurs chargés")
                except Exception as e:
                    print(f"[CSV] Erreur lors de la lecture des moteurs : {e}")
            
            # Ouvrir le CSV en écriture
            with open(events_csv_path, 'w', newline='', encoding='utf-8') as f:
                # En-tête VIAME
                f.write("# 1: Detection or Track-id,2: Video or Image Identifier,3: Unique Frame Identifier,4-7: Img-bbox(TL_x,TL_y,BR_x,BR_y),8: Detection or Length Confidence,9: Target Length (0 or -1 if invalid),10-11+: Repeated Species,Confidence Pairs or Attributes\n")
                
                # Métadonnées
                from datetime import datetime
                export_time = datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
                f.write(f"# metadata,fps: 5,\"exported_by: \"\"dive:kosmos\"\"\",\"exported_time: \"\"{export_time}\"\"\"\n")
                
                # 1. ÉCRITURE DES ÉVÉNEMENTS DU JSON
                lines_json_written = 0
                for track_id_ev, frame_start, frame_end, event_name in events_list:
                    
                    # Conversion Frame -> Séquence d'images (1 à X)
                    seq_start = round((frame_start - deduced_start_frame) / deduced_frame_interval) + 1
                    seq_end = round((frame_end - deduced_start_frame) / deduced_frame_interval) + 1
                    
                    # RECADRAGE STRICT DANS LA PLAGE EXPORTÉE (Atterrissage à Décollage)
                    # Tout ce qui est avant l'atterrissage commence à la frame 1
                    seq_start = max(1, min(seq_start, total_images))
                    # Tout ce qui se termine au décollage (ou après) est capé à la dernière image
                    seq_end = max(1, min(seq_end, total_images))
                    
                    if 'décollage' in event_name.lower() or 'decollage' in event_name.lower():
                        # Sécurité : On s'assure que le décollage s'étire bien jusqu'à la toute dernière image
                        seq_end = total_images

                    for seq_num in sorted(seq_to_image.keys()):
                        if seq_start <= seq_num <= seq_end:
                            img_filename = seq_to_image[seq_num]
                            img_path = os.path.normpath(os.path.join(img_dir, img_filename))
                            f.write(f"{track_id_ev},{img_path},{seq_num},0,0,0,0,1,-1,{event_name},1,\n")
                            lines_json_written += 1
                
                # 2. ÉCRITURE DES ÉVÉNEMENTS MOTEURS
                lines_motor_written = 0
                for motor_event in motor_events:
                    motor_track_id = motor_event['track_id']
                    motor_name = motor_event['type']
                    
                    timestamp_start = motor_event['timestamp']
                    timestamp_end = timestamp_start + motor_event['duration']
                    
                    frame_start_motor = int(timestamp_start * video_fps) + 1
                    frame_end_motor = int(timestamp_end * video_fps) + 1
                    
                    seq_start_motor = round((frame_start_motor - deduced_start_frame) / deduced_frame_interval) + 1
                    seq_end_motor = round((frame_end_motor - deduced_start_frame) / deduced_frame_interval) + 1
                    
                    # Recadrage de sécurité pour les moteurs
                    seq_start_motor = max(1, min(seq_start_motor, total_images))
                    seq_end_motor = max(1, min(seq_end_motor, total_images))
                    
                    for seq_num in sorted(seq_to_image.keys()):
                        if seq_start_motor <= seq_num <= seq_end_motor:
                            img_filename = seq_to_image[seq_num]
                            img_path = os.path.normpath(os.path.join(img_dir, img_filename))
                            f.write(f"{motor_track_id},{img_path},{seq_num},0,0,0,0,1,-1,{motor_name},1,\n")
                            lines_motor_written += 1
                
                print(f"[CSV] {total_images} frames traitées. {lines_json_written} lignes d'événements JSON (Atterrissage et Décollage inclus) et {lines_motor_written} lignes de moteurs écrites.")
                return True
                
        except Exception as e:
            print(f"[CSV ERROR] Erreur lors de la génération du CSV : {e}")
            import traceback
            traceback.print_exc()
            return False


    def _on_export_error(self, error_message: str):
        """Appelé en cas d'erreur pendant l'export"""
        if hasattr(self, 'export_status_label') and self.export_status_label is not None:
            self.export_status_label.setText(f"✗ Erreur : {error_message}")
        if hasattr(self, 'export_button') and self.export_button is not None:
            self.export_button.setEnabled(bool(self.current_video_path))
        if hasattr(self, 'export_progress') and self.export_progress is not None:
            self.export_progress.setVisible(False)


    def _zone_index_for_event_type(self, type_label: str) -> int:
        if not type_label:
            return 0
        label = type_label.lower()
        if "deployment" in label or "déploiement" in label:
            return 0
        if "animal" in label or "faune" in label:
            return 1
        if "interesting_images" in label or "image" in label:
            return 2
        return 0


    def on_capturer_clicked(self):
        if not hasattr(self, 'lecteur_events') or self.lecteur_events.player.duration() <= 0:
            return
            
        current_type = self.combo_type_event.currentText()
        current_value = self.combo_valeur_event.currentText()
        commentaire_rapide = self.input_commentaire_event.text().strip() if hasattr(self, 'input_commentaire_event') else ""
        
        pos_ms = self.lecteur_events.player.position()
        temps_str = self.lecteur_events.timeline._format_ms(pos_ms)

        if self._is_single_frame_event(current_type, current_value):
            conflit = self._single_frame_event_conflict(current_type, current_value)
            if conflit:
                QtWidgets.QMessageBox.warning(self.page, "Action impossible", f"Un(e) {conflit} existe déjà.")
                return

            nom_categorie_propre = current_type.split(' ')[0]
            nouvel_evt = {
                "start": pos_ms,
                "end": pos_ms,
                "title": f"Pic: {current_value}",
                "type": "custom_event",
                "zone": self._zone_index_for_event_type(current_type),
                "single_frame": True,
                "comment": commentaire_rapide,
                "_json_key": self._get_json_key_from_label(current_type),
                "_event_uid": self._generate_event_uid()
            }
            self.lecteur_events.timeline.events.append(nouvel_evt)
            self.lecteur_events.timeline.update()

            if hasattr(self, 'tree_captures') and self.tree_captures is not None:
                # 6 colonnes : Début, Fin, Type, Valeur, Commentaire, Aperçu
                item_arbre = QtWidgets.QTreeWidgetItem([temps_str, "-", nom_categorie_propre, f"{current_value}", commentaire_rapide, ""])
                # Autorise l'édition au double-clic sur la ligne
                item_arbre.setFlags(item_arbre.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                item_arbre.setForeground(0, QtGui.QBrush(QtGui.QColor("#e68c14")))
                self.tree_captures.addTopLevelItem(item_arbre)
                self.ajouter_miniature_arbre(item_arbre, pos_ms)

            self.sauvegarder_evenement_dans_json(nouvel_evt, current_type)
            if hasattr(self, 'input_commentaire_event'):
                self.input_commentaire_event.clear()
        else:
            # Événement long : on mémorise le début ET le commentaire écrit
            self.temps_debut_capture = pos_ms
            self.commentaire_en_cours = commentaire_rapide # Stockage temporaire du texte
            
            self.btn_capturer.setEnabled(False)
            self.btn_finir.setEnabled(True)
            self.btn_finir.setText(f"FINIR ÉVÉNEMENT (Début: {temps_str})")


    def on_finir_clicked(self):
        if not hasattr(self, 'lecteur_events') or self.temps_debut_capture is None:
            return

        current_type = self.combo_type_event.currentText()
        current_value = self.combo_valeur_event.currentText()
        
        # On récupère le commentaire stocké au début de la capture (ou une chaîne vide si absent)
        commentaire_sauve = getattr(self, 'commentaire_en_cours', "")

        t_start = self.temps_debut_capture
        t_end = self.lecteur_events.player.position()

        # Sécurité au cas où l'utilisateur a reculé dans la vidéo
        if t_end < t_start:
            t_start, t_end = t_end, t_start

        temps_debut_str = self.lecteur_events.timeline._format_ms(t_start)
        temps_fin_str = self.lecteur_events.timeline._format_ms(t_end)
        nom_categorie_propre = current_type.split(' ')[0]

        nouvel_evt = {
            "start": t_start,
            "end": t_end,
            "title": current_value,
            "type": "custom_event",
            "zone": self._zone_index_for_event_type(current_type),
            "single_frame": False,
            "comment": commentaire_sauve,
            "_json_key": self._get_json_key_from_label(current_type),
            "_event_uid": self._generate_event_uid()
        }
        
        self.lecteur_events.timeline.events.append(nouvel_evt)
        self.lecteur_events.timeline.update()

        if hasattr(self, 'tree_captures') and self.tree_captures is not None:
            # Ajout dans l'arbre à 6 colonnes (Commentaire en colonne index 4, texte vide en colonne 5 pour l'image)
            item_arbre = QtWidgets.QTreeWidgetItem([temps_debut_str, temps_fin_str, nom_categorie_propre, current_value, commentaire_sauve, ""])
            # Rendre la ligne éditable par double-clic
            item_arbre.setFlags(item_arbre.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            self.tree_captures.addTopLevelItem(item_arbre)
            self.ajouter_miniature_arbre(item_arbre, t_start)

        self.sauvegarder_evenement_dans_json(nouvel_evt, current_type)

        # Réinitialisation de l'état des widgets et nettoyage
        self.temps_debut_capture = None
        self.commentaire_en_cours = ""
        if hasattr(self, 'input_commentaire_event'):
            self.input_commentaire_event.clear()

        self.btn_capturer.setEnabled(True)
        self.btn_finir.setEnabled(False)
        self.btn_finir.setText("FINIR ÉVÉNEMENT")


    def on_video_selected(self, index: QtCore.QModelIndex):
        index_origine = self.proxy_model.mapToSource(index)
        item = self.video_model.itemFromIndex(index_origine.siblingAtColumn(0))
        if not item or not item.data(QtCore.Qt.ItemDataRole.UserRole):
            return

        self.current_video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        dossier_video = os.path.dirname(self.current_video_path)
        self.current_json_path = os.path.join(dossier_video, "template.json")

        if hasattr(self, 'tree_captures') and self.tree_captures is not None:
            self.tree_captures.blockSignals(True)
            self.tree_captures.clear()

        self.temps_debut_capture = None
        if hasattr(self, 'btn_capturer'):
            self.btn_capturer.setEnabled(True)

        self.charger_evenements_du_json()
        self._nettoyer_json_misplaced_events()  # Déplacer les événements misplacés
        self._update_export_button_state()

        evenements_timeline = []
        csv_system = os.path.join(dossier_video, "systemEvent.csv")
        
        if os.path.exists(csv_system):
            try:
                data_moteur = get_motor_stable_timestamps(csv_system, delay=6.0)
                for item_moteur in data_moteur:
                    start_ms = int(item_moteur["timestamp"] * 1000)
                    evenements_timeline.append({
                        "start": start_ms,
                        "end": start_ms + 3000,
                        "title": f"Rot #{item_moteur['index_rotation']} ({item_moteur['angle']}°)",
                        "type": item_moteur["type"]
                    })
            except Exception as e:
                print(f"[EVENEMENTS] Erreur CSV Moteur : {e}")

        if self.current_json_path and os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                video_obs = data.get("video_observation", {})
                fps = self._obtenir_fps_video()
                tolerance_frames = max(1, int(fps * 0.25))

                for cle_json in ["events_deployment", "events_animal", "events_interesting_images"]:
                    if cle_json in video_obs and video_obs[cle_json]:
                        values_list = video_obs[cle_json][0].get("values", [])
                        nom_categorie = self._get_label_from_json_key(cle_json)

                        for val in values_list:
                            frame_start = val.get("frame_number_start", 0)
                            frame_end = val.get("frame_number_end", 0)
                            valeur = val.get("value", "")
                            commentaire_json = val.get("comment", "") # Récupération sécurisée du commentaire

                            start_ms = int(((frame_start - 1) / fps) * 1000) if frame_start and fps else 0
                            end_ms = int(((frame_end - 1) / fps) * 1000) if frame_end and fps else 0
                            is_pic = (cle_json == "events_interesting_images" or start_ms == end_ms)
                            titre_timeline = f"Pic: {valeur}" if is_pic else valeur
                            
                            zone_index = self._zone_index_for_event_type(cle_json)

                            evt_doublon = False
                            for evt_existant in evenements_timeline:
                                if evt_existant.get("title") == titre_timeline:
                                    start_existant_ms = evt_existant.get("start", 0)
                                    if abs(start_existant_ms - start_ms) <= (tolerance_frames * 1000 / fps):
                                        evt_doublon = True
                                        break
                            
                            if not evt_doublon:
                                txt_start = self.lecteur_events.timeline._format_ms(start_ms)
                                txt_end = self.lecteur_events.timeline._format_ms(end_ms) if not is_pic else "-"

                                event_dict = {
                                    "start": start_ms,
                                    "end": end_ms,
                                    "title": titre_timeline,
                                    "type": "custom_event",
                                    "zone": zone_index,
                                    "comment": commentaire_json,
                                    "_json_key": cle_json
                                }
                                if "event_id" in val and val["event_id"]:
                                    event_dict["_event_uid"] = val["event_id"]
                                evenements_timeline.append(event_dict)

                                if hasattr(self, 'tree_captures') and self.tree_captures is not None:
                                    item_arbre = QtWidgets.QTreeWidgetItem([
                                        txt_start,
                                        txt_end,
                                        nom_categorie,
                                        valeur,
                                        commentaire_json,
                                        ""
                                    ])

                                    item_arbre.setFlags(item_arbre.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                                    if is_pic:
                                        item_arbre.setForeground(0, QtGui.QBrush(QtGui.QColor("#e68c14")))
                                    else:
                                        item_arbre.setForeground(0, QtGui.QBrush(QtGui.QColor("#2778a2")))

                                    self.tree_captures.addTopLevelItem(item_arbre)
                                    self.ajouter_miniature_arbre(item_arbre, start_ms)

            except Exception as e:
                print(f"[EVENEMENTS] Échec du parsing JSON : {e}")

        if hasattr(self, 'tree_captures') and self.tree_captures is not None:
            self.tree_captures.blockSignals(False)

        if hasattr(self, 'lecteur_events'):
            self.lecteur_events.charger_video_et_evenements(self.current_video_path, evenements_timeline)


    def _nettoyer_json_misplaced_events(self):
        """Déplace les événements de déploiement (atterrissage/décollage) qui seraient misplacés vers events_deployment."""
        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return
        
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            video_obs = data.get("video_observation", {})
            modifie = False
            
            # Déterminer dynamiquement les catégories events_* à nettoyer, sauf events_deployment
            event_categories = [k for k, v in video_obs.items() if isinstance(k, str) and k.startswith("events_") and k != "events_deployment"]

            for cle_json in event_categories:
                if cle_json not in video_obs or not video_obs[cle_json]:
                    continue
                
                values_list = video_obs[cle_json][0].get("values", [])
                deployment_events = []
                other_events = []
                
                # Séparer les événements de déploiement des autres
                for event in values_list:
                    valeur = event.get("value", "").strip().lower()
                    if any(keyword in valeur for keyword in ["atterrissage", "atterissage", "décollage", "decollage", "landing", "takeoff"]):
                        deployment_events.append(event)
                        print(f"[CLEANUP] Trouvé événement de déploiement misplacé: '{event.get('value')}' dans {cle_json}")
                        modifie = True
                    else:
                        other_events.append(event)
                
                # Mettre à jour la liste si des événements ont été séparés
                if deployment_events:
                    video_obs[cle_json][0]["values"] = other_events
                    
                    if "events_deployment" not in video_obs:
                        video_obs["events_deployment"] = [{"authorized_values_fr": [], "values": []}]
                    elif not video_obs["events_deployment"]:
                        video_obs["events_deployment"] = [{"authorized_values_fr": [], "values": []}]
                    
                    for event in deployment_events:
                        existing = False
                        for existing_event in video_obs["events_deployment"][0].get("values", []):
                            if (existing_event.get("value") == event.get("value") and 
                                existing_event.get("frame_number_start") == event.get("frame_number_start")):
                                existing = True
                                break
                        
                        if not existing:
                            video_obs["events_deployment"][0]["values"].append(event)
                            print(f"[CLEANUP] Événement déplacé vers events_deployment: '{event.get('value')}'")
            
            if modifie:
                data["video_observation"] = video_obs
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                print(f"[CLEANUP] JSON nettoyé avec succès")
        
        except Exception as e:
            print(f"[CLEANUP] Erreur lors du nettoyage du JSON: {e}")


    def charger_evenements_du_json(self):
        self.dictionnaire_evenements.clear()
        self.combo_type_event.blockSignals(True)
        self.combo_type_event.clear()

        if self.current_json_path and os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                self._build_event_categories_from_json(data)

                if self.dictionnaire_evenements:
                    self.combo_type_event.addItems(list(self.dictionnaire_evenements.keys()))
                    self.on_type_event_changed(self.combo_type_event.currentText())
            except Exception as e:
                print(f"[ERREUR] Échec de la lecture du schéma JSON : {e}")

        self.combo_type_event.blockSignals(False)


    def on_arbre_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int):
        """Déclenché lorsque l'utilisateur modifie directement une cellule (Commentaire à l'index 4)."""
        if column != 4:
            return

        if not self.current_json_path or not os.path.exists(self.current_json_path):
            return

        # 1. Récupération des informations de la ligne modifiée
        valeur_cible = item.text(3) 
        nouveau_commentaire = item.text(4).strip()

        # 2. Mise à jour dans l'objet mémoire de la timeline pour garder la cohérence
        if hasattr(self, 'lecteur_events') and getattr(self.lecteur_events, 'timeline', None):
            for evt in self.lecteur_events.timeline.events:
                if evt.get("title", "").replace("Pic: ", "") == valeur_cible:
                    evt["comment"] = nouveau_commentaire
                    break

        # 3. Écriture directe et sécurisée dans le fichier JSON
        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            video_obs = data.get("video_observation", {})
            modifie = False

            for cle_json in ["events_deployment", "events_animal", "events_interesting_images"]:
                if cle_json in video_obs and video_obs[cle_json]:
                    values_list = video_obs[cle_json][0].get("values", [])
                    for val in values_list:
                        if val.get("value") == valeur_cible:
                            val["comment"] = nouveau_commentaire
                            modifie = True
                            break
                if modifie:
                    break

            if modifie:
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                print(f"[BACKEND] Commentaire enregistré pour '{valeur_cible}': {nouveau_commentaire}")

        except Exception as e:
            print(f"[BACKEND] Erreur lors de l'édition du commentaire dans le JSON : {e}")