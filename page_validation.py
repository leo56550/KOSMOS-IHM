import os
import json
from PyQt6 import QtCore, QtGui, QtWidgets
from utils2 import get_motor_stable_timestamps
from embedded_player import EmbeddedVideoPlayer


class VideoFilterProxyModel(QtCore.QSortFilterProxyModel):
    """Proxy model qui masque les vidéos déjà déplacées dans la corbeille."""

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
        return ".trash" not in parties and "trash" not in parties


class ValidationPage:
    """Contrôleur associé à la page de validation."""

    def __init__(self, page_widget: QtWidgets.QWidget, shared_model: QtGui.QStandardItemModel):
        self.page = page_widget
        self.video_model = shared_model 
        self.current_language = 'fr'
        
        # Variable pour mémoriser le JSON et le chemin de la vidéo active
        self.current_json_path = None
        self.current_video_path = None

        # 1. Récupération des widgets
        self.video_tree = self.page.findChild(QtWidgets.QTreeView, "tree_video_validation")
        self.player_container = self.page.findChild(QtWidgets.QFrame, "lecteur_timeline_container")
        self.exploitable_container = self.page.findChild(QtWidgets.QFrame, "exploitable_container")

        # --- CORRECTION : LIBÉRATION DE LA FRAME GAUCHE ---
        self.frame_gauche_validation = self.page.findChild(QtWidgets.QFrame, "frame_3")
        if self.frame_gauche_validation:
            self.frame_gauche_validation.setMinimumWidth(150)        
            self.frame_gauche_validation.setMaximumWidth(16777215)   # Casse le verrou de largeur maximale

        # --- CONFIGURATION DU FILTRE PROXY ---
        self.proxy_model = VideoFilterProxyModel(self.page)
        self.proxy_model.setSourceModel(self.video_model)

        # 2. Assignation du PROXY au TreeView
        if self.video_tree:
            self.video_tree.setModel(self.proxy_model)
            self.video_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.video_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.video_tree.clicked.connect(self.on_video_selected)

        # 3. Injection du lecteur vidéo et gestion des dimensions de manière flexible
        if self.player_container:
            if self.player_container.layout() is None:
                self.player_layout = QtWidgets.QVBoxLayout(self.player_container)
                self.player_layout.setContentsMargins(10, 10, 10, 10)
            else:
                self.player_layout = self.player_container.layout()

            self.lecteur = EmbeddedVideoPlayer(parent=self.player_container)
            self.player_layout.addWidget(self.lecteur)
            
            # Configuration souple du conteneur et du widget de lecture
            self.player_container.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored, 
                QtWidgets.QSizePolicy.Policy.Expanding
            )
            self.lecteur.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored, 
                QtWidgets.QSizePolicy.Policy.Expanding
            )
            
            self.player_container.setMinimumWidth(0)
            self.lecteur.setMinimumWidth(0)
            
            if hasattr(self.lecteur, 'video_widget'):
                self.lecteur.video_widget.setMinimumWidth(0)
                self.lecteur.video_widget.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Ignored, 
                    QtWidgets.QSizePolicy.Policy.Expanding
                )

        # --- CONFIGURATION DU SPLITTER DE LA PAGE ---
        self.splitter_principal = self.page.findChild(QtWidgets.QSplitter, "splitter_3")
        if self.splitter_principal:
            self.splitter_principal.setStretchFactor(0, 0)   # Panneau gauche
            self.splitter_principal.setStretchFactor(1, 1)   # Zone lecteur (prend l'espace disponible)
            self.splitter_principal.setCollapsible(1, False) # Empêche la disparition complète du lecteur

        # 4. Configuration du menu déroulant "Exploitable" et du panneau latéral
        if self.exploitable_container:
            if self.exploitable_container.layout() is None:
                self.exploitable_layout = QtWidgets.QVBoxLayout(self.exploitable_container)
                self.exploitable_layout.setContentsMargins(10, 10, 10, 10)
                self.exploitable_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            else:
                self.exploitable_layout = self.exploitable_container.layout()

            self.lbl_exploitable = QtWidgets.QLabel("Vidéo Exploitable ? ")
            self.lbl_exploitable.setStyleSheet("color: white; font-weight: bold; border: none;")
            self.exploitable_layout.addWidget(self.lbl_exploitable)

            self.combo_exploitable = QtWidgets.QComboBox()
            self.combo_exploitable.setStyleSheet("""
                QComboBox { background-color: #20415d; color: white; border: 1px solid #ababab; border-radius: 4px; padding: 5px; min-width: 150px; }
                QComboBox QAbstractItemView { background-color: #20415d; color: white; selection-background-color: #2778a2; }
            """)
            self.exploitable_layout.addWidget(self.combo_exploitable)
            self.combo_exploitable.currentTextChanged.connect(self.on_exploitable_changed)

        # 5. Configuration des boutons de correction et signaux
        self.btn_hr = self.page.findChild(QtWidgets.QPushButton, "btn_hr")
        self.btn_dehaze = self.page.findChild(QtWidgets.QPushButton, "btn_dehaze")

        if self.btn_hr:
            self.btn_hr.clicked.connect(self.on_hr_clicked)
        if self.btn_dehaze:
            self.btn_dehaze.clicked.connect(self.on_dehaze_clicked)

        # Connexion au changement d'état (Play/Pause) du lecteur
        if hasattr(self, 'lecteur') and hasattr(self.lecteur, 'playback_state_changed'):
            self.lecteur.playback_state_changed.connect(self.on_playback_state_changed)

        # Initialisations graphiques
        self.initialiser_indicateurs_arbre()
        self.set_language(self.current_language)

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, langue: str):
        """Met à jour les textes de la page selon la langue choisie."""
        self.current_language = langue
        if hasattr(self, 'lbl_exploitable'):
            self.lbl_exploitable.setText(self.translate("Vidéo Exploitable ? ", "Video Exploitable?"))
        
        # Rafraîchir le contenu du combobox si un fichier est actuellement ouvert
        if self.current_json_path and os.path.exists(self.current_json_path):
            self.rafraichir_combobox_valeurs()

    def initialiser_indicateurs_arbre(self):
        """Parcourt le modèle pour mettre à jour les icônes de validation au démarrage."""
        for row in range(self.video_model.rowCount()):
            item = self.video_model.item(row, 0)
            if item:
                video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
                if video_path:
                    self.rafraichir_indicateur_item(item, os.path.dirname(video_path))

    def on_video_selected(self, index: QtCore.QModelIndex):
        """Déclenché au clic sur une vidéo dans la liste de validation."""
        index_origine = self.proxy_model.mapToSource(index)
        item = self.video_model.itemFromIndex(index_origine.siblingAtColumn(0))
        if not item:
            return

        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        dossier_video = os.path.dirname(video_path)
        
        self.current_video_path = video_path
        self.current_json_path = os.path.join(dossier_video, "template.json")
        
        # --- CHARGEMENT DU COMBOBOX EXPLOITABLE ---
        self.rafraichir_combobox_valeurs()

        # --- RECONSTITUTION DES ÉVÉNEMENTS DEPUIS LE CSV MOTEUR ---
        evenements_detectes = []
        csv_system = os.path.join(dossier_video, "systemEvent.csv")
        
        if os.path.exists(csv_system):
            try:
                data_moteur = get_motor_stable_timestamps(csv_system, delay=6.0)
                for entry in data_moteur:
                    start_ms = int(entry["timestamp"] * 1000)
                    end_ms = start_ms + 3000  # Durée de surbrillance (3 secondes)
                    titre_evenement = f"Rot #{entry['index_rotation']} ({entry['angle']}°)"
                    
                    evenements_detectes.append({
                        "start": start_ms,
                        "end": end_ms,
                        "title": titre_evenement,
                        "type": entry["type"]  # Reçoit 'rotation_360' ou 'rotation_60'
                    })
            except Exception as e:
                print(f"Erreur d'extraction du fichier CSV : {e}")

        # Injection de la vidéo et de ses événements correspondants dans l'EmbeddedVideoPlayer
        self.lecteur.charger_video_et_evenements(video_path, evenements_detectes)

    def rafraichir_combobox_valeurs(self):
        """Lit le JSON actuel et charge les options du combobox selon la langue courante."""
        if not hasattr(self, 'combo_exploitable') or not self.current_json_path:
            return

        if os.path.exists(self.current_json_path):
            try:
                self.combo_exploitable.blockSignals(True)
                self.combo_exploitable.clear()

                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if "video_observation" in data and "exploitable" in data["video_observation"]:
                    exploitable_field = data["video_observation"]["exploitable"]
                    
                    # Sélection du set de valeurs selon la langue active
                    cle_langue = "authorized_values_fr" if self.current_language == 'fr' else "authorized_values_en"
                    valeurs_options = exploitable_field.get(cle_langue, [])
                    valeur_actuelle = exploitable_field.get("value")
                    
                    self.combo_exploitable.addItems(valeurs_options)
                    
                    if valeur_actuelle in valeurs_options:
                        self.combo_exploitable.setCurrentText(valeur_actuelle)
                    else:
                        self.combo_exploitable.setCurrentIndex(-1)
                        
            except Exception as e:
                print(f"[ERREUR] Impossible de lire le JSON pour charger le combobox : {e}")
            finally:
                self.combo_exploitable.blockSignals(False)

    def on_exploitable_changed(self, text: str):
        """Déclenché UNIQUEMENT quand l'utilisateur change manuellement la valeur du menu déroulant."""
        if not self.current_json_path or not os.path.exists(self.current_json_path) or not text:
            return

        try:
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if "video_observation" in data and "exploitable" in data["video_observation"]:
                data["video_observation"]["exploitable"]["value"] = text
                
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
                print(f"[SUCCÈS] JSON mis à jour ! Champ 'value' de 'exploitable' défini sur : '{text}'")
                
                # --- MISE À JOUR VISUELLE DIRECTE DANS L'ARBRE (TREE VIEW) ---
                indices_selectionnes = self.video_tree.selectionModel().selectedRows()
                if indices_selectionnes:
                    index_proxy = indices_selectionnes[0]
                    index_origine = self.proxy_model.mapToSource(index_proxy)
                    item = self.video_model.itemFromIndex(index_origine.siblingAtColumn(0))
                    
                    if item:
                        self.rafraichir_indicateur_item(item, os.path.dirname(self.current_json_path))
            
        except Exception as e:
            print(f"[ERREUR] Échec de la mise à jour du champ 'value' dans le JSON : {e}")

    def rafraichir_indicateur_item(self, item: QtGui.QStandardItem, dossier_video: str):
        """Vérifie l'état de remplissage du JSON et applique la couleur/icône adéquate à l'item."""
        json_path = os.path.join(dossier_video, "template.json")
        est_traite = False

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                exploitable_field = data.get("video_observation", {}).get("exploitable", {})
                valeur_actuelle = exploitable_field.get("value")
                
                if valeur_actuelle and str(valeur_actuelle).strip():
                    est_traite = True
            except Exception:
                pass # Sécurité en cas de fichier JSON temporairement inaccessible ou verrouillé

        # Application du style visuel (Vert validé VS Blanc en attente)
        if est_traite:
            icone_valide = self.page.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton)
            item.setIcon(icone_valide)
            item.setForeground(QtGui.QBrush(QtGui.QColor("#4CAF50")))
        else:
            icone_attente = self.page.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon)
            item.setIcon(icone_attente)
            item.setForeground(QtGui.QBrush(QtGui.QColor("white")))

    def on_hr_clicked(self):
        """Déclenché lors du clic sur le bouton HR."""
        if not self.current_video_path or not hasattr(self, 'lecteur'):
            return
        
        # Le lecteur gère la mise en pause et le calcul de la correction en interne
        self.lecteur.appliquer_correction_fixe("HR")

    def on_dehaze_clicked(self):
        """Déclenché lors du clic sur le bouton Débrumage."""
        if not self.current_video_path or not hasattr(self, 'lecteur'):
            return
        
        # Le lecteur gère la mise en pause et le calcul de la correction en interne
        self.lecteur.appliquer_correction_fixe("DEHAZE")

    def on_playback_state_changed(self, is_playing: bool):
        """Slot connecté au changement d'état de lecture émis par EmbeddedVideoPlayer.
        
        Si la vidéo passe en mode "Play", on s'assure de nettoyer les filtres fixes du lecteur.
        """
        if is_playing and hasattr(self, 'lecteur'):
            if hasattr(self.lecteur, 'retirer_filtres'):
                self.lecteur.retirer_filtres()