import os
import io
import json
import folium
import shutil
from video_player import VideoPlayerWindow  
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from utils2 import get_all_mp4_files, get_video_gps_coords, get_motor_stable_timestamps, extract_frame_at_time

class MapBridge(QtCore.QObject):
    """Pont pour recevoir les signaux JavaScript depuis la carte Folium."""
    videoSelected = QtCore.pyqtSignal(str)

    @QtCore.pyqtSlot(str)
    def select_video(self, video_name):
        print(f"-> [PONT] Clic reçu depuis Folium pour la vidéo : {video_name}")
        # On émet un signal Qt avec le nom de la vidéo reçue
        self.videoSelected.emit(video_name)

class QualifPage:
    """Contrôleur pour la page Qualification de l'interface."""

    def __init__(self, widget: QtWidgets.QWidget, parent: QtWidgets.QWidget | None = None):
        self.widget = widget
        self.parent = parent
        self.current_language = 'fr'
        
        # --- DONNÉES GLOBALES ---
        self.video_model = QtGui.QStandardItemModel()
        self.trash_model = QtGui.QStandardItemModel()  # Modèle pour la corbeille
        self.selected_video_name = None
        self.all_coords = {}
        self.champs_campagne = {}  # Stocke les QLineEdit de la campagne globale
        self.lecteur_detache = None  # Permet de définir l'attribut dès le départ

        # --- ÉLÉMENTS DE L'INTERFACE ---
        self.video_tree = self.widget.findChild(QtWidgets.QTreeView, "video_tree")
        self.trash_video_tree = self.widget.findChild(QtWidgets.QTreeView, "trash_video_tree")
        self.frame_campagne = self.widget.findChild(QtWidgets.QFrame, "frame_campagne")
        self.mini_map_container = self.widget.findChild(QtWidgets.QFrame, "mini_map_container")
        
        # Zone dynamique pour accueillir nos lignes de rotations miniatures
        self.frame_miniature = self.widget.findChild(QtWidgets.QFrame, "frame_miniature")


        if self.frame_campagne:
            # 1. Layout principal vertical pour la frame
            layout_permanent = QtWidgets.QVBoxLayout(self.frame_campagne)
            layout_permanent.setContentsMargins(5, 5, 5, 5)
            layout_permanent.setSpacing(10)
            
            # 2. Le titre (qui ne bougera jamais)
            self.label_titre_section = QtWidgets.QLabel("Propriétés de campagne")
            self.label_titre_section.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff; padding-bottom: 5px;")
            self.label_titre_section.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout_permanent.addWidget(self.label_titre_section)
            
            # --- CORRECTION : AJOUT D'UN SCROLL AREA POUR ÉVITER LA DISPARITION ---
            self.scroll_campagne = QtWidgets.QScrollArea(self.frame_campagne)
            self.scroll_campagne.setWidgetResizable(True)
            self.scroll_campagne.setStyleSheet("background: transparent; border: none;")
            
            # 3. Le widget conteneur dynamique (placé à l'intérieur du scroll)
            self.conteneur_formulaire_dynamique = QtWidgets.QWidget()
            self.scroll_campagne.setWidget(self.conteneur_formulaire_dynamique)
            
            layout_permanent.addWidget(self.scroll_campagne)


        self.init_video_list()
        self.init_trash_list()
        self.init_minimap()
        self.init_miniature_area()
        self.set_language(self.current_language)

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, langue: str):
        self.current_language = langue
        if hasattr(self, 'label_titre_section'):
            self.label_titre_section.setText(self.translate("Propriétés de campagne", "Campaign properties"))
        if hasattr(self, 'label_titre_videos'):
            self.label_titre_videos.setText(self.translate("Vidéos de campagne", "Campaign videos"))
        if hasattr(self, 'label_titre_poubelle'):
            self.label_titre_poubelle.setText(self.translate("Vidéos supprimées", "Removed videos"))
        self.video_model.setHorizontalHeaderLabels([
            self.translate("Fichier", "File"),
            self.translate("Durée", "Duration"),
            "FPS",
            self.translate("Résolution", "Resolution"),
            self.translate("Taille", "Size"),
        ])
        self.trash_model.setHorizontalHeaderLabels([
            self.translate("Fichier", "File"),
            self.translate("Durée", "Duration"),
            "FPS",
            self.translate("Résolution", "Resolution"),
            self.translate("Taille", "Size"),
        ])

    def init_video_list(self):
        """Initialise la liste principale des vidéos avec son titre et ses paramètres de Drag & Drop."""
        self.video_model.setHorizontalHeaderLabels(["Fichier", "Durée", "FPS", "Résolution", "Taille"])
        self.video_tree.setModel(self.video_model)

        # --- ENCAPSULATION POUR LE QSPLITTER (MÉTHODE COMPATIBLE) ---
        splitter = self.video_tree.parentWidget()
        
        # 1. On crée un widget tampon qui va recevoir le titre et l'arbre
        self.widget_conteneur_videos = QtWidgets.QWidget()
        layout_bloc = QtWidgets.QVBoxLayout(self.widget_conteneur_videos)
        layout_bloc.setContentsMargins(0, 0, 0, 0)
        layout_bloc.setSpacing(5)
        
        # 2. On crée le titre
        self.label_titre_videos = QtWidgets.QLabel("Vidéos de campagne")
        self.label_titre_videos.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff; padding-bottom: 2px;")
        self.label_titre_videos.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # 3. On trouve la position du treeview dans le splitter pour le remplacer par le tampon
        if hasattr(splitter, "indexOf"):  # Vérifie si c'est bien un QSplitter ou un layout
            index = splitter.indexOf(self.video_tree)
            layout_bloc.addWidget(self.label_titre_videos)
            layout_bloc.addWidget(self.video_tree)
            splitter.insertWidget(index, self.widget_conteneur_videos)
        # -------------------------------------------------------------

        # Ajustement de la taille des colonnes
        for i in range(self.video_model.columnCount()):
            self.video_tree.resizeColumnToContents(i)

        # Gestion de la sélection
        self.video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.video_tree.clicked.connect(self.on_video_selected)

        # ACTIVATION ET CONNEXION DU MENU CONTEXTUEL (Correction)
        self.video_tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_tree.customContextMenuRequested.connect(self.afficher_menu_contextuel)

        # Configuration Drag & Drop
        self.video_tree.setDragEnabled(True)
        self.video_tree.setAcceptDrops(True)
        self.video_tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.video_tree.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        
        self.video_tree.dragEnterEvent = self.video_dragEnterEvent
        self.video_tree.dropEvent = self.video_dropEvent

    def init_trash_list(self):
        """Initialise la liste de la corbeille avec son titre et ses paramètres de Drag & Drop."""
        if not self.trash_video_tree:
            print("Attention : Le widget 'trash_video_tree' n'a pas été trouvé dans l'interface.")
            return

        self.trash_model.setHorizontalHeaderLabels(["Fichier", "Durée", "FPS", "Résolution", "Taille"])
        self.trash_video_tree.setModel(self.trash_model)

        # --- ENCAPSULATION POUR LE QSPLITTER (MÉTHODE COMPATIBLE) ---
        splitter_trash = self.trash_video_tree.parentWidget()
        
        # 1. On crée le second widget tampon pour le côté corbeille
        self.widget_conteneur_trash = QtWidgets.QWidget()
        layout_bloc_trash = QtWidgets.QVBoxLayout(self.widget_conteneur_trash)
        layout_bloc_trash.setContentsMargins(0, 0, 0, 0)
        layout_bloc_trash.setSpacing(5)
        
        # 2. On crée le titre rouge de la corbeille
        self.label_titre_poubelle = QtWidgets.QLabel("Vidéos supprimées")
        self.label_titre_poubelle.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff5555; padding-bottom: 2px;")
        self.label_titre_poubelle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # 3. Remplacement dans le splitter
        if hasattr(splitter_trash, "indexOf"):
            index_trash = splitter_trash.indexOf(self.trash_video_tree)
            layout_bloc_trash.addWidget(self.label_titre_poubelle)
            layout_bloc_trash.addWidget(self.trash_video_tree)
            splitter_trash.insertWidget(index_trash, self.widget_conteneur_trash)
        # -------------------------------------------------------------

        # Ajustement de la taille des colonnes
        for i in range(self.trash_model.columnCount()):
            self.trash_video_tree.resizeColumnToContents(i)

        # Gestion de la sélection
        self.trash_video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.trash_video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        # Configuration Drag & Drop
        self.trash_video_tree.setAcceptDrops(True)
        self.trash_video_tree.setDragEnabled(True)
        self.trash_video_tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        
        self.trash_video_tree.dragEnterEvent = self.trash_dragEnterEvent
        self.trash_video_tree.dropEvent = self.trash_dropEvent

    def restaurer_video_via_index(self, index: QtCore.QModelIndex):
        """Déplace le dossier de la vidéo de la corbeille vers le dossier de la campagne."""
        ligne_index = index.row()
        
        item_nom = self.trash_model.item(ligne_index, 0)
        item_dur = self.trash_model.item(ligne_index, 1)
        item_fps = self.trash_model.item(ligne_index, 2)
        item_res = self.trash_model.item(ligne_index, 3)
        item_taille = self.trash_model.item(ligne_index, 4)
        
        if not item_nom:
            return
            
        nom_video = item_nom.text()
        video_path_trash = item_nom.data(QtCore.Qt.ItemDataRole.UserRole)
        
        if video_path_trash and os.path.exists(video_path_trash):
            try:
                dossier_video_dans_trash = os.path.dirname(video_path_trash)
                dossier_trash_global = os.path.dirname(dossier_video_dans_trash)
                dossier_campagne = os.path.dirname(dossier_trash_global)
                
                cible_destination = os.path.join(dossier_campagne, os.path.basename(dossier_video_dans_trash))
                
                if os.path.exists(cible_destination):
                    shutil.rmtree(cible_destination)
                
                nouveau_emplacement_dossier = shutil.move(dossier_video_dans_trash, dossier_campagne)
                
                nom_fichier_mp4 = os.path.basename(video_path_trash)
                nouveau_video_path = os.path.join(nouveau_emplacement_dossier, nom_fichier_mp4)
                
                print(f"Dossier vidéo restauré : {dossier_video_dans_trash} -> {nouveau_emplacement_dossier}")
                
            except Exception as e:
                print(f"Erreur lors de la restauration du dossier de {nom_video} : {e}")
                return

        col_nom = QtGui.QStandardItem(nom_video)
        col_dur = QtGui.QStandardItem(item_dur.text() if item_dur else "")
        col_fps = QtGui.QStandardItem(item_fps.text() if item_fps else "")
        col_res = QtGui.QStandardItem(item_res.text() if item_res else "")
        col_taille = QtGui.QStandardItem(item_taille.text() if item_taille else "--")
        
        col_nom.setData(nouveau_video_path, QtCore.Qt.ItemDataRole.UserRole)
        self.video_model.appendRow([col_nom, col_dur, col_fps, col_res, col_taille])
        
        self.trash_model.removeRow(ligne_index)

    def trash_dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        """Autorise le dépôt uniquement si la source provient du tableau des vidéos."""
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist") and event.source() == self.video_tree:
            event.acceptProposedAction()
        else:
            event.ignore()

    def trash_dropEvent(self, event: QtGui.QDropEvent):
        """Déclenché au moment où l'utilisateur lâche la vidéo dans la poubelle."""
        if event.source() == self.video_tree:
            indices_selectionnes = self.video_tree.selectionModel().selectedRows()
            
            if indices_selectionnes:
                indices_selectionnes.sort(key=lambda idx: idx.row(), reverse=True)
                for index in indices_selectionnes:
                    self.supprimer_video_via_index(index)
                
                event.setDropAction(QtCore.Qt.DropAction.CopyAction)
                event.accept()
        else:
            event.ignore()

    def video_dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        """Autorise le dépôt uniquement si la source provient de la corbeille."""
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist") and event.source() == self.trash_video_tree:
            event.acceptProposedAction()
        else:
            event.ignore()

    def video_dropEvent(self, event: QtGui.QDropEvent):
        """Déclenché au moment où l'on lâche une vidéo de la poubelle vers la liste principale."""
        if event.source() == self.trash_video_tree:
            indices_selectionnes = self.trash_video_tree.selectionModel().selectedRows()
            
            if indices_selectionnes:
                indices_selectionnes.sort(key=lambda idx: idx.row(), reverse=True)
                for index in indices_selectionnes:
                    self.restaurer_video_via_index(index)
                    
                event.setDropAction(QtCore.Qt.DropAction.CopyAction)
                event.accept()
        else:
            event.ignore()

    def ouvrir_explorateur_systeme(self, nom_derusher: str):
        """Déclenché après validation du nom sur la page d'accueil."""
        
        # 1. Sélection du dossier racine de la campagne
        dossier = QtWidgets.QFileDialog.getExistingDirectory(self.parent or self.widget, "Sélectionner Campagne")
        if not dossier:
            return
        
        self.dossier_campagne_actuel = dossier

        # Nettoyage des modèles de l'IHM
        self.video_model.removeRows(0, self.video_model.rowCount())
        if self.trash_video_tree:
            self.trash_model.removeRows(0, self.trash_model.rowCount())
        self.all_coords.clear()

        # Chargement des vidéos présentes dans les sous-dossiers
        videos = get_all_mp4_files(dossier)
        if not videos:
            print("[ATTENTION] Aucune vidéo MP4 trouvée dans cette campagne.")
            return

        # Remplissage du tableau à l'écran
        for video in videos:
            col_nom = QtGui.QStandardItem(video["name"])
            col_dur = QtGui.QStandardItem(video["duration"])
            col_fps = QtGui.QStandardItem(video["fps"])
            col_res = QtGui.QStandardItem(video["res"])
            
            taille_str = video.get("size")
            if not taille_str and os.path.exists(video["path"]):
                taille_octets = os.path.getsize(video["path"])
                taille_str = f"{taille_octets / (1024 * 1024):.2f} Mo"
            elif not taille_str:
                taille_str = "--"
                
            col_taille = QtGui.QStandardItem(taille_str)
            col_nom.setData(video["path"], QtCore.Qt.ItemDataRole.UserRole)
            self.video_model.appendRow([col_nom, col_dur, col_fps, col_res, col_taille])

            coords = get_video_gps_coords(video["path"])
            if coords:
                self.all_coords[video["name"]] = coords

        self.update_minimap(self.selected_video_name)

        # -----------------------------------------------------------------
        # SYNCHRONISATION DU NOM DU DÉRUSHER DANS CHAQUE SOUS-DOSSIER
        # -----------------------------------------------------------------
        compteur_updates = 0
        premier_json_charge = None
        dossiers_traitees = set()

        for video in videos:
            # os.path.normpath règle le problème des / et \ sous Windows
            chemin_video_normalise = os.path.normpath(video["path"])
            sous_dossier_video = os.path.dirname(chemin_video_normalise)

            if sous_dossier_video in dossiers_traitees:
                continue
            dossiers_traitees.add(sous_dossier_video)
            
            # On cible le fichier template.json de CE sous-dossier
            json_path = os.path.join(sous_dossier_video, "template.json")
            
            if not os.path.exists(json_path):
                print(f"[DEBUG] template.json introuvable pour le dossier : {sous_dossier_video}")
                continue

            if not premier_json_charge:
                premier_json_charge = json_path
                
            try:
                # Étape A : Lecture du JSON
                with open(json_path, 'r', encoding='utf-8') as f:
                    donnees_json = json.load(f)
                
                # Étape B : Injection du nom de l'analyseur
                if "survey" in donnees_json and "derusher" in donnees_json["video_observation"]:
                    donnees_json["video_observation"]["derusher"]["value"] = nom_derusher
                    
                    # Étape C : Réécriture du fichier mis à jour
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(donnees_json, f, indent=2, ensure_ascii=False)
                    
                    compteur_updates += 1
                else:
                    print(f"[DEBUG] Clé 'video_observation.derusher' absente dans {json_path}")
                
            except Exception as e:
                print(f"Erreur d'écriture dans {json_path} : {e}")

        print(f"[SUCCÈS JSON] L'analyseur '{nom_derusher}' a été configuré dans {compteur_updates} sous-dossiers de vidéos.")

        # --- MODIFICATION ICI : Extraction de la partie commune 'system' ---
        self.system_data = None  # On initialise l'attribut
        if premier_json_charge:
            try:
                with open(premier_json_charge, 'r', encoding='utf-8') as f:
                    donnees_completes = json.load(f)
                    # On sauvegarde uniquement le bloc système qui est identique partout
                    if "system" in donnees_completes:
                        self.system_data = donnees_completes["system"]
            except Exception as e:
                print(f"[ERREUR] Impossible de lire le bloc système du premier JSON : {e}")

            # Appel de ta méthode existante pour l'onglet Qualif
            self.charger_et_afficher_json_campagne(premier_json_charge)
        else:
            print("[ATTENTION] Aucun fichier template.json trouvé à côté des vidéos MP4.")

    def charger_et_afficher_json_campagne(self, json_path: str):
        """Lit le fichier JSON global et génère le formulaire sous le titre permanent."""
        if not hasattr(self, 'conteneur_formulaire_dynamique') or not self.conteneur_formulaire_dynamique:
            return

        # 1. Nettoyage PROPRE et STRICT de l'ancien layout
        if self.conteneur_formulaire_dynamique.layout():
            layout_actuel = self.conteneur_formulaire_dynamique.layout()
            # On retire et supprime un par un tous les widgets à l'intérieur
            while layout_actuel.count():
                enfant = layout_actuel.takeAt(0)
                if enfant.widget():
                    enfant.widget().deleteLater()
            
            # Au lieu de détruire le layout, on va le réutiliser s'il s'agit déjà d'un QFormLayout,
            # ou on le remplace proprement en détruisant l'ancien via deleteLater.
            layout_actuel.deleteLater()
        
        self.champs_campagne.clear()

        # 2. Reconstruction du formulaire si le fichier existe
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    donnees_json = json.load(f)
                
                if "survey" in donnees_json:
                    # On recrée un layout tout neuf attaché au conteneur
                    nouveau_layout_formulaire = QtWidgets.QFormLayout(self.conteneur_formulaire_dynamique)
                    nouveau_layout_formulaire.setContentsMargins(5, 5, 5, 5)
                    nouveau_layout_formulaire.setSpacing(15)
                    nouveau_layout_formulaire.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                    
                    elements_survey = donnees_json["survey"]
                    for cle_technique, infos in elements_survey.items():
                        nom_affichage = infos.get("name_fr", cle_technique).capitalize()
                        valeur_initiale = infos.get("value") or ""
                            
                        champ_saisie = QtWidgets.QLineEdit()
                        champ_saisie.setText(str(valeur_initiale))
                        
                        champ_saisie.setStyleSheet("""
                            QLineEdit {
                                font-size: 14px;
                                font-weight: bold;
                                padding: 6px;
                                color: #ffffff;
                                background-color: #1a1a1a;
                                border: 1px solid #555555;
                                border-radius: 4px;
                            }
                        """)
                        
                        if "example" in infos and infos["example"]:
                            champ_saisie.setPlaceholderText(f"{infos['example']}")
                        
                        self.champs_campagne[cle_technique] = champ_saisie
                        
                        champ_saisie.editingFinished.connect(
                            lambda cl=cle_technique: self.sur_champ_campagne_modifie(cl)
                        )
                        
                        label_gauche = QtWidgets.QLabel(f"{nom_affichage} :")
                        label_gauche.setStyleSheet("font-size: 13px; font-weight: bold; color: #e0e0e0;")
                        
                        nouveau_layout_formulaire.addRow(label_gauche, champ_saisie)
                        
                    print(f"[SUCCÈS] {len(elements_survey)} champs de campagne affichés.")
                    return
            except Exception as e:
                print(f"Erreur lecture template.json global : {e}")

        # 3. Message de secours (si le fichier n'existe pas ou est corrompu)
        layout_vide = QtWidgets.QVBoxLayout(self.conteneur_formulaire_dynamique)
        label_erreur = QtWidgets.QLabel("Aucune donnée de campagne chargée.")
        label_erreur.setStyleSheet("color: #aaaaaa; font-style: italic; font-size: 11px;")
        label_erreur.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout_vide.addWidget(label_erreur)

        # 3. Message de secours
        layout_vide = QtWidgets.QVBoxLayout(self.conteneur_formulaire_dynamique)
        label_erreur = QtWidgets.QLabel("Aucune donnée de campagne chargée.")
        label_erreur.setStyleSheet("color: #aaaaaa; font-style: italic; font-size: 11px;")
        label_erreur.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout_vide.addWidget(label_erreur)

    def sur_champ_campagne_modifie(self, cle_technique: str):
        """Récupère la valeur du QLineEdit qui vient d'être modifié et lance la synchronisation."""
        champ = self.champs_campagne.get(cle_technique)
        if champ:
            nouvelle_valeur = champ.text()
            self.synchroniser_champ_campagne(cle_technique, nouvelle_valeur)

    def synchroniser_champ_campagne(self, cle_technique: str, nouvelle_valeur: str):
        """Parcourt toutes les vidéos de la campagne pour mettre à jour la valeur du champ modifié."""
        print(f"[SYNCHRO] Application de la valeur '{nouvelle_valeur}' pour le champ '{cle_technique}'...")
        
        # On parcourt toutes les lignes de notre modèle de vidéos
        for row in range(self.video_model.rowCount()):
            item_video = self.video_model.item(row, 0)
            if not item_video:
                continue
                
            # Récupération du chemin absolu du fichier MP4
            video_path = item_video.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path or not os.path.exists(video_path):
                continue
                
            # Déduction du chemin du template.json pour cette vidéo précise
            dossier_video = os.path.dirname(video_path)
            json_video_path = os.path.join(dossier_video, "template.json")
            
            if os.path.exists(json_video_path):
                try:
                    # 1. Lecture du JSON de la vidéo
                    with open(json_video_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 2. Mise à jour de la structure 'survey'
                    if "survey" in data and cle_technique in data["survey"]:
                        data["survey"][cle_technique]["value"] = nouvelle_valeur
                        
                        # 3. Réécriture du fichier JSON mis à jour
                        with open(json_video_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                            
                except Exception as e:
                    print(f"[ERREUR SYNCHRO] Impossible de mettre à jour {json_video_path} : {e}")
                    
        print("[SUCCÈS] Campagne synchronisée sur l'ensemble des vidéos.")

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Au clic sur une vidéo : met à jour la carte, l'affichage et ouvre le lecteur."""
        item = self.video_model.itemFromIndex(index.siblingAtColumn(0))
        if not item:
            return
            
        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        video_name = item.text()
        self.selected_video_name = video_name

        dossier_video = os.path.dirname(video_path)
        csv_system = os.path.join(dossier_video, "systemEvent.csv")
        
        # --- RÉCUPÉRATION DES ÉVÉNEMENTS POUR LE LECTEUR ---
        events_moteur = []
        if os.path.exists(csv_system):
            self.update_camera_views(video_path, csv_system)
            # On extrait les données pour les envoyer au lecteur
            events_moteur = get_motor_stable_timestamps(csv_path=csv_system, delay=6.0)
           
        self.update_minimap(selected_name=video_name)

        # Nettoyage de l'ancien lecteur
        if self.lecteur_detache is not None:
            try:
                self.lecteur_detache.close()
                self.lecteur_detache.deleteLater()
            except Exception:
                pass
            
        # --- CORRECTION DU CRASH : Ajout de l'argument 'events_data' ---
        # Note : tout comme pour l'autre méthode, si VideoPlayerWindow attend 
        # le chemin du CSV au lieu de la liste, remplacez 'events_moteur' par 'csv_system'
        self.lecteur_detache = VideoPlayerWindow(video_path, events_data=events_moteur, parent=self.widget)
        self.lecteur_detache.show()

    def init_miniature_area(self):
        """Prépare la zone de droite pour pouvoir faire défiler les lignes de rotation."""
        if not self.frame_miniature:
            return
            
        if self.frame_miniature.layout():
            layout_ancien = self.frame_miniature.layout()
            while layout_ancien.count():
                item = layout_ancien.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(layout_ancien)

        self.scroll_area = QtWidgets.QScrollArea(self.frame_miniature)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background-color: #2778a2; border: none;")
        
        self.scroll_content = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(15)
        self.scroll_layout.addStretch()  # Repousse initialement tout vers le haut
        
        self.scroll_area.setWidget(self.scroll_content)
        
        principal_layout = QtWidgets.QVBoxLayout(self.frame_miniature)
        principal_layout.setContentsMargins(0, 0, 0, 0)
        principal_layout.addWidget(self.scroll_area)

    def init_minimap(self):
        self.map_view = QWebEngineView()
        
        # Initialisation du pont
        self.bridge = MapBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.bridge)
        self.map_view.page().setWebChannel(self.channel)
        
        # Connexion au TreeView
        self.bridge.videoSelected.connect(self.selectionner_video_par_nom)

        layout = QtWidgets.QVBoxLayout(self.mini_map_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_view)

    def charger_contenu_carte(self):
        m = folium.Map(location=[48.3600, -4.5578], zoom_start=14, tiles="CartoDB positron")
        data = io.BytesIO()
        m.save(data, close_file=False)
        self.map_view.setHtml(data.getvalue().decode())

    def update_minimap(self, selected_name: str | None = None):
        import math

        # 1. NETTOYAGE ET SÉCURISATION DES COORDONNÉES
        # On ne garde que les coordonnées qui possèdent des valeurs numériques réelles (pas de NaN ni de None)
        coords_valides = {}
        if hasattr(self, 'all_coords') and self.all_coords:
            for name, coords in self.all_coords.items():
                if coords and len(coords) >= 2:
                    lat, lon = coords[0], coords[1]
                    if lat is not None and lon is not None:
                        try:
                            if not (math.isnan(float(lat)) or math.isnan(float(lon))):
                                coords_valides[name] = [float(lat), float(lon)]
                        except (ValueError, TypeError):
                            pass

        # 2. CHOIX DU CENTRE DE LA CARTE (FALLBACK)
        # Si aucune coordonnée valide n'est disponible, on utilise un point par défaut (ex: Brest/Plouzané)
        # Cela permet d'ouvrir la campagne et d'afficher la carte même sans données GPS.
        if coords_valides:
            center = list(coords_valides.values())[0]
        else:
            center = [48.356, -4.571]  # Point de repli par défaut

        # 3. PREMIER CHARGEMENT DE LA CARTE
        if not hasattr(self, 'carte_initialisee') or not self.carte_initialisee:
            
            # Utilisation du centre sécurisé sans NaNs
            m = folium.Map(location=center, zoom_start=17, tiles=None) 
            
            # Couche Google Earth Satellite Hybride
            folium.TileLayer(
                tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
                attr="Google Earth",
                name="Google Satellite",
                max_zoom=22
            ).add_to(m)
            
            # Transport Qt
            m.get_root().header.add_child(
                folium.Element('<script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>')
            )

            # SCRIPT LOGIQUE INTERNE (Avec gestion forcée de l'ouverture du Popup)
            script_principal = """
            <script>
                var qtBackend = null;
                var tousLesMarqueurs = {}; 
                var dernierMarqueurRouge = null;

                document.addEventListener("DOMContentLoaded", function() {
                    if (typeof qt !== 'undefined' && qt.webChannelTransport) {
                        new QWebChannel(qt.webChannelTransport, function (channel) {
                            qtBackend = channel.objects.backend;
                        });
                    }
                });

                function notifierPython(videoName) {
                    if (qtBackend) { qtBackend.select_video(videoName); }
                }

                function changerCouleurMarqueurJS(nomVideo) {
                    // 1. Remettre l'ancien marqueur rouge en bleu si existant
                    if (dernierMarqueurRouge && tousLesMarqueurs[dernierMarqueurRouge]) {
                        var mAncien = tousLesMarqueurs[dernierMarqueurRouge];
                        mAncien.setIcon(L.AwesomeMarkers.icon({icon: 'camera', prefix: 'fa', markerColor: 'blue'}));
                        mAncien.setZIndexOffset(1);
                        mAncien.closePopup();
                    }
                    
                    // 2. Passer le nouveau marqueur en rouge et FORCER l'affichage du nom
                    if (tousLesMarqueurs[nomVideo]) {
                        var mNouveau = tousLesMarqueurs[nomVideo];
                        mNouveau.setIcon(L.AwesomeMarkers.icon({icon: 'camera', prefix: 'fa', markerColor: 'red'}));
                        mNouveau.setZIndexOffset(1000);
                        dernierMarqueurRouge = nomVideo;
                        
                        setTimeout(function() {
                            mNouveau.openPopup();
                        }, 50);
                        
                        if (window.carteLeaflet) {
                            window.carteLeaflet.panTo(mNouveau.getLatLng());
                        }
                    }
                }
            </script>
            """
            m.get_root().html.add_child(folium.Element(script_principal))

            # Liaison de la carte
            js_liaison_carte = f"""
            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    if (typeof {m.get_name()} !== 'undefined') {{
                        window.carteLeaflet = {m.get_name()};
                    }}
                }});
            </script>
            """
            m.get_root().html.add_child(folium.Element(js_liaison_carte))

            # Création des marqueurs uniquement pour les coordonnées valides
            for name, coords in coords_valides.items():
                popup_persistant = folium.Popup(name, auto_close=False, close_on_click=False)

                marker = folium.Marker(
                    location=coords, 
                    popup=popup_persistant, 
                    icon=folium.Icon(color='blue', icon='camera', prefix='fa')
                )
                marker.add_to(m)
                
                js_enregistrement = f"""
                <script>
                    document.addEventListener("DOMContentLoaded", function() {{
                        setTimeout(function() {{
                            var mInstance = {marker.get_name()};
                            if (mInstance) {{
                                tousLesMarqueurs["{name}"] = mInstance;
                                mInstance.on('click', function(e) {{
                                    notifierPython("{name}");
                                }});
                            }}
                        }}, 150);
                    }});
                </script>
                """
                m.get_root().html.add_child(folium.Element(js_enregistrement))

            # Rendu initial HTML
            data = io.BytesIO()
            m.save(data, close_file=False)
            
            self.map_view.page().setWebChannel(self.channel)
            self.map_view.setHtml(data.getvalue().decode())
            
            self.carte_initialisee = True
            
            # On applique le marqueur rouge uniquement s'il est associé à une coordonnée valide
            if selected_name and selected_name in coords_valides:
                QtCore.QTimer.singleShot(500, lambda: self.appliquer_marqueur_rouge_js(selected_name))
                
        else:
            # 2. APPLICATION DYNAMIQUE
            if selected_name and selected_name in coords_valides:
                self.appliquer_marqueur_rouge_js(selected_name)

    def appliquer_marqueur_rouge_js(self, selected_name: str):
        """Exécute le script JS de changement de couleur avec une sécurité de présence."""
        if not selected_name:
            return
            
        # Le script vérifie d'abord si la fonction 'changerCouleurMarqueurJS' ET le dictionnaire existent.
        # Si la carte subit un re-rendu asynchrone, cela évite les plantages de tokens dans la console.
        script_execution = f"""
        if (typeof changerCouleurMarqueurJS === 'function' && typeof tousLesMarqueurs !== 'undefined' && tousLesMarqueurs['{selected_name}']) {{
            changerCouleurMarqueurJS('{selected_name}');
        }} else {{
            // Si la carte n'était pas tout à fait prête, on ré-essaye discrètement dans 100ms
            setTimeout(function() {{
                if (typeof changerCouleurMarqueurJS === 'function') {{ changerCouleurMarqueurJS('{selected_name}'); }}
            }}, 100);
        }}
        """
        self.map_view.page().runJavaScript(script_execution)

    def selectionner_video_par_nom(self, nom_video: str):
        """Parcourt le modèle pour trouver la vidéo par son nom et la sélectionne graphiquement."""
        if self.selected_video_name == nom_video:
            return

        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item and item.text() == nom_video:
                index = self.video_model.indexFromItem(item)
                
                # Bloquer temporairement les signaux pour éviter les boucles infinies
                self.video_tree.blockSignals(True)
                self.video_tree.selectionModel().setCurrentIndex(
                    index, 
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect | QtCore.QItemSelectionModel.SelectionFlag.Rows
                )
                self.video_tree.scrollTo(index)
                self.video_tree.blockSignals(False)
                
                # Mise à jour des variables de suivi
                self.selected_video_name = nom_video
                video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                dossier_video = os.path.dirname(video_path)
                csv_system = os.path.join(dossier_video, "systemEvent.csv")
                
                # Récupération ou initialisation des événements pour le lecteur
                events_moteur = []
                if os.path.exists(csv_system):
                    self.update_camera_views(video_path, csv_system)
                    events_moteur = get_motor_stable_timestamps(csv_path=csv_system, delay=6.0)
                
                # Fermeture de l'ancien lecteur si existant
                if self.lecteur_detache is not None:
                    try:
                        self.lecteur_detache.close()
                        self.lecteur_detache.deleteLater()
                    except Exception:
                        pass
                    
                # Instanciation du lecteur vidéo
                self.lecteur_detache = VideoPlayerWindow(video_path, events_data=events_moteur, parent=self.widget)
                self.lecteur_detache.show()
                
                # --- L'AJOUT CRITIQUE ICI ---
                # On demande à la carte de passer ce marqueur en rouge (via le code dynamique JS)
                self.update_minimap(nom_video)
                
                break

    def update_camera_views(self, video_path: str, csv_path: str):
        """Extrait absolument toutes les rotations stables et génère des blocs horizontaux."""
        # NETTOYAGE SÉCURISÉ
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            # Récupère la liste de dictionnaires depuis utils2.py
            events_moteur = get_motor_stable_timestamps(csv_path, delay=6.0)
            
            if not events_moteur:
                label_info = QtWidgets.QLabel("Aucune rotation moteur trouvée dans le fichier CSV.")
                label_info.setStyleSheet("color: white; font-size: 14px;")
                self.scroll_layout.addWidget(label_info)
                self.scroll_layout.addStretch()
                return

            # On découpe toujours par groupes de 6 événements max (une rotation complète)
            groupes_rotations = [events_moteur[i:i + 6] for i in range(0, len(events_moteur), 6)]

            for index_rot, rotation_events in enumerate(groupes_rotations):
                # 1. Création du grand bandeau horizontal pour la rotation en cours
                frame_rotation = QtWidgets.QFrame()
                frame_rotation.setFixedHeight(230) # Augmenté légèrement pour l'esthétique
                frame_rotation.setStyleSheet("background-color: #20415d; border-radius: 8px; border: 1px solid #3d3d3d;")
                
                layout_horizontal = QtWidgets.QHBoxLayout(frame_rotation)
                layout_horizontal.setContentsMargins(15, 10, 15, 10)
                layout_horizontal.setSpacing(15)

                # Titre à gauche du bandeau
                label_titre = QtWidgets.QLabel(f"Rotation\n#{index_rot + 1}\n(360°)")
                label_titre.setStyleSheet("color: white; font-weight: bold; font-size: 13px;")
                label_titre.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                label_titre.setFixedWidth(90)
                layout_horizontal.addWidget(label_titre)

                # 2. Boucle sur les vignettes de ce bandeau (les angles)
                for evt in rotation_events:
                    ts = evt["timestamp"]
                    angle = evt["angle"]
                    type_evt = evt["type"]

                    # Conteneur individuel pour la photo
                    widget_photo = QtWidgets.QFrame()
                    widget_photo.setStyleSheet("background-color: #1a1a1a; border-radius: 6px;")
                    
                    # --- APPLICATION DU STYLE EN FONCTION DE L'ANGLE ---
                    if type_evt == "rotation_360":
                        # Rotation 360° marquée en rouge
                        widget_photo.setFixedSize(248, 188)
                        widget_photo.setStyleSheet(
                            "background-color: #1a1a1a; "
                            "border-radius: 6px; "
                            "border: 3px solid #ff3333;"
                        )
                    else:
                        # Frame standard pour les rotations moteur intermédiaires (60°, 120°, etc.)
                        widget_photo.setFixedSize(240, 180)
                        widget_photo.setStyleSheet(
                            "background-color: #1a1a1a; "
                            "border-radius: 6px; "
                            "border: 1px solid #555555;"
                        )
                    
                    # Extraction et affichage de l'image
                    frame_data = extract_frame_at_time(video_path, ts)
                    if frame_data is not None:
                        self.display_in_frame(widget_photo, frame_data, angle_degres=angle, ts_secondes=ts)
                        
                    layout_horizontal.addWidget(widget_photo)
                
                # Remplissage si le groupe est incomplet (dernière rotation en cours)
                if len(rotation_events) < 6:
                    for _ in range(6 - len(rotation_events)):
                        layout_horizontal.addSpacing(240)

                layout_horizontal.addStretch()
                self.scroll_layout.addWidget(frame_rotation)

        except Exception as e:
            print(f"Erreur lors de la mise à jour des miniatures : {e}")

    def display_in_frame(self, widget: QtWidgets.QFrame, cv_img, angle_degres: int, ts_secondes: float):
        """Convertit et affiche l'image OpenCV avec badges intégrés."""
        h, w, ch = cv_img.shape
        q_img = QtGui.QImage(cv_img.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(q_img)
        
        layout_interne = QtWidgets.QVBoxLayout(widget)
        layout_interne.setContentsMargins(0, 0, 0, 0)
        
        label_image = QtWidgets.QLabel(widget)
        label_image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label_image.setPixmap(pixmap.scaled(
            widget.size(), 
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
            QtCore.Qt.TransformationMode.SmoothTransformation
        ))
        layout_interne.addWidget(label_image)
        
        # BADGE 1 : ANGLE
        label_angle = QtWidgets.QLabel(f" {angle_degres}° ", label_image)
        label_angle.setStyleSheet("background-color: rgba(0, 0, 0, 160); color: #55ff55; font-weight: bold; border-radius: 3px; font-size: 10px;")
        label_angle.move(5, 5)
        
        # BADGE 2 : TEMPS VIDEO
        minutes = int(ts_secondes // 60)
        secondes = int(ts_secondes % 60)
        millisecondes = int((ts_secondes - int(ts_secondes)) * 1000)
        
        temps_formate = f" {minutes:02d}:{secondes:02d}.{millisecondes:03d} "
        
        label_temps = QtWidgets.QLabel(temps_formate, label_image)
        label_temps.setStyleSheet("background-color: rgba(0, 0, 0, 160); color: #ffffff; font-weight: bold; border-radius: 3px; font-size: 10px;")
        
        label_temps.adjustSize()
        largeur_badge_temps = label_temps.width()
        largeur_cadre_photo = widget.width()
        
        position_x = largeur_cadre_photo - largeur_badge_temps - 5
        label_temps.move(position_x, 5)

    def afficher_menu_contextuel(self, position: QtCore.QPoint):
        """Affiche le menu contextuel clic-droit pour supprimer un fichier."""
        index = self.video_tree.indexAt(position)
        if not index.isValid():
            return  

        menu = QtWidgets.QMenu(self.video_tree)
        action_poubelle = menu.addAction("🗑️ Supprimer")
        
        # Exécuter le menu à la position globale de la souris
        action_cliquee = menu.exec(self.video_tree.viewport().mapToGlobal(position))
        
        if action_cliquee == action_poubelle:
            # On récupère l'index correspondant à la ligne entière (colonne 0)
            index_ligne = index.siblingAtColumn(0)
            self.supprimer_video_via_index(index_ligne)

    def supprimer_video_via_index(self, index: QtCore.QModelIndex):
        """Déplace le dossier de la vidéo de la campagne vers la corbeille."""
        ligne_index = index.row()
        
        item_nom = self.video_model.item(ligne_index, 0)
        item_dur = self.video_model.item(ligne_index, 1)
        item_fps = self.video_model.item(ligne_index, 2)
        item_res = self.video_model.item(ligne_index, 3)
        item_taille = self.video_model.item(ligne_index, 4)
        
        if not item_nom:
            return
            
        nom_video = item_nom.text()
        video_path_origine = item_nom.data(QtCore.Qt.ItemDataRole.UserRole)
        
        if video_path_origine and os.path.exists(video_path_origine):
            try:
                # Structure : .../Nom_Campagne/Nom_Video/Nom_Video.mp4
                dossier_video_origine = os.path.dirname(video_path_origine)
                dossier_campagne = os.path.dirname(dossier_video_origine)
                
                # Création du dossier global .trash s'il n'existe pas
                dossier_trash_global = os.path.join(dossier_campagne, ".trash")
                os.makedirs(dossier_trash_global, exist_ok=True)
                
                cible_destination = os.path.join(dossier_trash_global, os.path.basename(dossier_video_origine))
                
                # Sécurité : si le dossier existe déjà dans la corbeille, on le nettoie avant le déplacement
                if os.path.exists(cible_destination):
                    shutil.rmtree(cible_destination)
                
                nouveau_emplacement_dossier = shutil.move(dossier_video_origine, dossier_trash_global)
                
                nom_fichier_mp4 = os.path.basename(video_path_origine)
                nouveau_video_path = os.path.join(nouveau_emplacement_dossier, nom_fichier_mp4)
                
                print(f"Dossier vidéo déplacé à la corbeille : {dossier_video_origine} -> {nouveau_emplacement_dossier}")
                
            except Exception as e:
                print(f"Erreur lors de la mise à la corbeille du dossier de {nom_video} : {e}")
                return

        # Création des nouveaux items pour le modèle de la corbeille
        col_nom = QtGui.QStandardItem(nom_video)
        col_dur = QtGui.QStandardItem(item_dur.text() if item_dur else "")
        col_fps = QtGui.QStandardItem(item_fps.text() if item_fps else "")
        col_res = QtGui.QStandardItem(item_res.text() if item_res else "")
        col_taille = QtGui.QStandardItem(item_taille.text() if item_taille else "--")
        
        # Sauvegarde du nouveau chemin dans le UserRole
        col_nom.setData(nouveau_video_path, QtCore.Qt.ItemDataRole.UserRole)
        self.trash_model.appendRow([col_nom, col_dur, col_fps, col_res, col_taille])
        
        # Suppression de la ligne du modèle principal
        self.video_model.removeRow(ligne_index)
        
        # Reset de la sélection si la vidéo supprimée était celle sélectionnée
        if self.selected_video_name == nom_video:
            self.selected_video_name = None
            # Optionnel : masquer ou réinitialiser le lecteur vidéo ici si nécessaire