import os
import json
from PyQt6 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class MetadonneesPage:
    """Contrôleur pour la page Métadonnées de l'interface."""

    def __init__(self, widget: QtWidgets.QWidget, video_model: QtGui.QStandardItemModel, trash_model: QtGui.QStandardItemModel):
        self.widget = widget
        self.current_language = 'fr'
        self.system_data_cache = None
        self.weather_data_cache = None
        
        # Sauvegarde des références des modèles de données de la campagne
        self.video_model = video_model
        self.trash_model = trash_model
        
        # Récupération des conteneurs existants depuis le fichier .ui
        self.graph_trash_container = self.widget.findChild(QtWidgets.QFrame, "graph_trash_container")
        self.container_system_data = self.widget.findChild(QtWidgets.QFrame, "container_system_data")
        self.container_weather_data = self.widget.findChild(QtWidgets.QFrame, "container_weather_data")
        
        self.setup_ui()
        self.init_gauge_poubelle()
        self.init_layout_systeme() # Préparation de l'espace pour les données système
        self.init_layout_meteo()
        
        # --- ÉCOUTE DES CHANGEMENTS EN TEMPS RÉEL ---
        self.video_model.rowsInserted.connect(self.rafraichir_statistiques)
        self.video_model.rowsRemoved.connect(self.rafraichir_statistiques)
        self.trash_model.rowsInserted.connect(self.rafraichir_statistiques)
        self.trash_model.rowsRemoved.connect(self.rafraichir_statistiques)

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, langue: str):
        self.current_language = langue
        if hasattr(self, 'title_common') and self.title_common is not None:
            self.title_common.setText(self.translate("Métadonnées communes", "Common metadata"))
        if hasattr(self, 'title_specific') and self.title_specific is not None:
            self.title_specific.setText(self.translate("Métadonnées spécifiques", "Video-specific metadata"))
        if hasattr(self, 'event_title') and self.event_title is not None:
            self.event_title.setText(self.translate("Événements spécifiques à la vidéo", "Video-specific events"))
        self._apply_metadata_placeholders()
        if self.system_data_cache is not None:
            self.injecter_donnes_systeme(self.system_data_cache)
        if self.weather_data_cache is not None:
            self.injecter_donnees_meteo(self.weather_data_cache)

    def setup_ui(self):
        # Ensure page has a layout
        if not self.widget.layout():
            layout = QtWidgets.QVBoxLayout(self.widget)
            layout.setContentsMargins(16, 16, 16, 16)
        else:
            layout = self.widget.layout()

        # Prefer containers defined in the .ui (try common and specific variants)
        common = None
        for name in ("common_metadata", "common_meta"):
            common = self.widget.findChild(QtWidgets.QFrame, name)
            if common is not None:
                break

        specific = None
        for name in ("specific_metada", "specific_metadata", "specific_meta"):
            specific = self.widget.findChild(QtWidgets.QFrame, name)
            if specific is not None:
                break

        # If still not found, create frames and add them to layout
        if common is None:
            common = QtWidgets.QFrame()
            common.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            common.setStyleSheet("QFrame { background: transparent; }")
            self.title_common = QtWidgets.QLabel("Métadonnées communes")
            self.title_common.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
            layout.addWidget(self.title_common)
            layout.addWidget(common)
        else:
            self.title_common = None

        if specific is None:
            specific = QtWidgets.QFrame()
            specific.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            specific.setStyleSheet("QFrame { background: transparent; }")
            self.title_specific = QtWidgets.QLabel("Métadonnées spécifiques à la vidéo")
            self.title_specific.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
            layout.addWidget(self.title_specific)
            layout.addWidget(specific)
        else:
            self.title_specific = None

        self.common_meta_container = common
        self.video_meta_container = specific

        label = self.widget.findChild(QtWidgets.QLabel)
        if label:
            label.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")

        # Internal mapping json_path_list (tuple of keys) -> widget
        self._meta_widgets = {}

        # Prepare metadata display widgets even before a video is selected
        self._init_metadata_widgets()

        # Init tree view for campaign videos: try common names then fallback to first QTreeView
        self.tree_videos = None
        candidate_names = ["video_tree", "treeView", "treeView_2", "tree_videos", "tree_campaign", "tree_video_validation"]
        for name in candidate_names:
            tv = self.widget.findChild(QtWidgets.QTreeView, name)
            if tv is not None:
                self.tree_videos = tv
                break
        if self.tree_videos is None:
            trees = self.widget.findChildren(QtWidgets.QTreeView)
            if trees:
                self.tree_videos = trees[0]

        if self.tree_videos is not None:
            # Show entire campaign (use the shared video_model passed in constructor)
            try:
                self.tree_videos.setModel(self.video_model)
                self.tree_videos.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
                self.tree_videos.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
                self.tree_videos.setStyleSheet("QTreeView { background-color: #1e1e1e; color: white; }")
            except Exception:
                pass

    def init_gauge_poubelle(self):
        """Initialise la figure Matplotlib dans la frame conteneur."""
        if not self.graph_trash_container:
            print("[ERREUR] 'graph_trash_container' introuvable.")
            return

        if not self.graph_trash_container.layout():
            layout_graph = QtWidgets.QVBoxLayout(self.graph_trash_container)
            layout_graph.setContentsMargins(5, 5, 5, 5)
        else:
            layout_graph = self.graph_trash_container.layout()

        self.figure = Figure(figsize=(3, 3), facecolor='none')
        self.canvas = FigureCanvas(self.figure)
        
        layout_graph.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self.rafraichir_statistiques()

    def rafraichir_statistiques(self):
        """Calcule les volumes actuels à partir des modèles et redessine le graphique avec deux cercles imbriqués."""
        if not hasattr(self, 'ax'):
            return
            
        nb_valides = self.video_model.rowCount()
        nb_poubelle = self.trash_model.rowCount()
        total = nb_valides + nb_poubelle
        
        # --- CALCUL DES VIDÉOS EXPLOITABLES ("oui") EN LECTURE DU TEMPLATE JSON ---
        nb_exploitables = 0
        for row in range(nb_valides):
            index_video = self.video_model.index(row, 0)
            if not index_video.isValid():
                continue

            video_path = self.video_model.data(index_video, QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                continue

            json_path = os.path.join(os.path.dirname(video_path), "template.json")
            if not os.path.exists(json_path):
                continue

            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                exploitable_field = data.get("video_observation", {}).get("exploitable", {})
                valeur_exploitable = exploitable_field.get("value")
                if isinstance(valeur_exploitable, str) and valeur_exploitable.strip().lower() == "oui":
                    nb_exploitables += 1
            except Exception:
                # On ignore les JSON corrompus ou les champs manquants
                continue
        
        self.ax.clear()
        
        # 1. DESIGN DE L'ANNEAU EXTÉRIEUR (Poubelle vs Valides)
        if total == 0:
            donnees_ext = [1]
            couleurs_ext = ['#3d3d3d']
            pct_poubelle = 0.0
        else:
            donnees_ext = [nb_valides, nb_poubelle]
            couleurs_ext = ['#2778a2', '#ff5555']
            pct_poubelle = (nb_poubelle / total) * 100

        # Tracé du grand anneau externe
        self.ax.pie(
            donnees_ext, 
            radius=1.0,  # Taille maximale
            colors=couleurs_ext, 
            startangle=90, 
            counterclock=False,
            wedgeprops=dict(width=0.25, edgecolor='#1a1a1a', linewidth=1.5)
        )

        # 2. DESIGN DE L'ANNEAU INTÉRIEUR (Vidéos Exploitables au sein des valides)
        if nb_valides == 0:
            donnees_int = [1]
            couleurs_int = ['#222222']
            pct_exploitable = 0.0
        else:
            nb_non_exploitables = nb_valides - nb_exploitables
            donnees_int = [nb_exploitables, nb_non_exploitables]
            # Vert émeraude pour l'exploitable, gris bleuté pour le non-exploitable
            couleurs_int = ['#00ffaa', '#1c384f'] 
            pct_exploitable = (nb_exploitables / nb_valides) * 100

        # Tracé du petit anneau interne
        self.ax.pie(
            donnees_int,
            radius=0.7,  # Plus petit pour glisser à l'intérieur
            colors=couleurs_int,
            startangle=90,
            counterclock=False,
            wedgeprops=dict(width=0.20, edgecolor='#1a1a1a', linewidth=1.2)
        )

        # 3. TEXTES ET LÉGENDES CENTRALES
        texte_centre = (
            f"Vidéos jetées : {pct_poubelle:.1f}%\n"
            f"Vidéos exploitables : {pct_exploitable:.1f}%"
        ) if total > 0 else "0.0%\nJetées"
        
        self.ax.text(0, 0, texte_centre, ha='center', va='center', fontsize=9, fontweight='bold', color='white')

        # Titre informatif global en bas
        titre_global = f"Total : {total} obs. | Exploitables : {nb_exploitables} / {nb_valides}"
        self.ax.set_title(titre_global, color='#aaaaaa', fontsize=9, y=-0.1)
        
        self.ax.axis('equal')  
        self.figure.tight_layout()
        self.canvas.draw()

    def init_layout_systeme(self):
        """Prépare un layout en grille (Formulaire) dans la frame conteneur."""
        if not self.container_system_data:
            print("[ERREUR] 'container_system_data' introuvable dans le fichier .ui.")
            return

        if not self.container_system_data.layout():
            self.layout_grille = QtWidgets.QFormLayout(self.container_system_data)
            self.layout_grille.setContentsMargins(15, 15, 15, 15)
            self.layout_grille.setSpacing(12)
            self.layout_grille.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        else:
            self.layout_grille = self.container_system_data.layout()
            
    def init_layout_meteo(self):
        """Prépare un QFormLayout dans la frame météo."""
        if not self.container_weather_data:
            print("[ERREUR] 'container_weather_data' introuvable dans le fichier .ui.")
            return

        if not self.container_weather_data.layout():
            self.layout_grille_meteo = QtWidgets.QFormLayout(self.container_weather_data)
            self.layout_grille_meteo.setContentsMargins(15, 15, 15, 15)
            self.layout_grille_meteo.setSpacing(12)
            self.layout_grille_meteo.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        else:
            self.layout_grille_meteo = self.container_weather_data.layout()

    def _configure_meta_tree(self, tree: QtWidgets.QTreeWidget, headers: list[str], editable: bool = True):
        tree.setColumnCount(len(headers))
        tree.setHeaderLabels(headers)
        tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed if editable else QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.header().setStretchLastSection(True)
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(False)
        tree.setStyleSheet(
            "QTreeWidget { background-color: #1f2730; color: #eaeaea; border: 1px solid #2e2e2e; border-radius: 6px; font-size: 14px; }"
            "QTreeWidget::item:selected { background-color: #2778a2; color: white; font-size: 14px; }"
            "QHeaderView::section { background-color: #2b2b2b; color: #ffffff; padding: 6px; font-weight: bold; font-size: 13px; }"
        )
        if editable:
            tree.itemChanged.connect(self._on_meta_item_changed)

    def _init_metadata_widgets(self):
        if self.common_meta_container is None or self.video_meta_container is None:
            return

        if self.common_meta_container.layout() is None:
            self.common_meta_layout = QtWidgets.QVBoxLayout(self.common_meta_container)
            self.common_meta_layout.setContentsMargins(10, 10, 10, 10)
            self.common_meta_layout.setSpacing(6)
        else:
            self.common_meta_layout = self.common_meta_container.layout()

        if self.video_meta_container.layout() is None:
            self.video_meta_layout = QtWidgets.QVBoxLayout(self.video_meta_container)
            self.video_meta_layout.setContentsMargins(10, 10, 10, 10)
            self.video_meta_layout.setSpacing(6)
        else:
            self.video_meta_layout = self.video_meta_container.layout()

        self.title_common = QtWidgets.QLabel("Métadonnées communes")
        self.title_common.setStyleSheet("font-size:14px; font-weight:bold; color: white; padding:4px 0px;")
        self.common_meta_layout.addWidget(self.title_common)

        self.common_tree = QtWidgets.QTreeWidget()
        self._configure_meta_tree(self.common_tree, ["Clé", "Valeur"], editable=True)
        self.common_meta_layout.addWidget(self.common_tree)

        self.title_specific = QtWidgets.QLabel("Métadonnées spécifiques")
        self.title_specific.setStyleSheet("font-size:14px; font-weight:bold; color: white; padding:4px 0px;")
        self.video_meta_layout.addWidget(self.title_specific)

        self.specific_tree = QtWidgets.QTreeWidget()
        self._configure_meta_tree(self.specific_tree, ["Champ", "Valeur"], editable=True)
        self.video_meta_layout.addWidget(self.specific_tree)

        # Événements section masquée
        self.event_title = QtWidgets.QLabel("Événements spécifiques à la vidéo")
        self.event_title.setStyleSheet("font-size:13px; font-weight:bold; color: #c8eaff; padding:8px 0 4px 0;")
        self.event_title.hide()
        self.video_meta_layout.addWidget(self.event_title)

        self.event_tree = QtWidgets.QTreeWidget()
        self._configure_meta_tree(self.event_tree, ["Type", "Détail"], editable=False)
        self.event_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.event_tree.setMinimumHeight(220)
        self.event_tree.hide()
        self.video_meta_layout.addWidget(self.event_tree)

        self._apply_metadata_placeholders()

    def _apply_metadata_placeholders(self):
        self.common_tree.clear()
        self.specific_tree.clear()
        self.event_tree.clear()
        placeholder = QtWidgets.QTreeWidgetItem([
            self.translate("Aucune vidéo sélectionnée", "No video selected"),
            self.translate("Cliquez sur une vidéo pour charger ses métadonnées.", "Click a video to load its metadata.")
        ])
        placeholder.setFlags(placeholder.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
        self.common_tree.addTopLevelItem(placeholder)
        self.specific_tree.addTopLevelItem(QtWidgets.QTreeWidgetItem(["", ""]))
        self.event_tree.addTopLevelItem(QtWidgets.QTreeWidgetItem(["", ""]))

    # ------------------------------------------------------------------
    # Métadonnées: chargement / affichage / sauvegarde
    # ------------------------------------------------------------------
    def bind_json_path(self, json_path: str):
        """Charge le template.json ciblé et affiche les champs.
        Classification: clés top-level 'video_observation' et 'events_*' -> spécifique,
        le reste -> communes.
        """
        if not json_path or not os.path.exists(json_path):
            print(f"[METADONNEES] JSON introuvable: {json_path}")
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[METADONNEES] Erreur lecture JSON: {e}")
            return

        self.current_template_json = json_path
        self._meta_widgets.clear()
        self._json_data = data
        
        # Mettre à jour le titre avec le nom de la vidéo
        video_dir = os.path.dirname(json_path)
        video_name = os.path.basename(video_dir)
        if hasattr(self, 'title_specific') and self.title_specific is not None:
            self.title_specific.setText(self.translate(f"Métadonnées spécifiques à la vidéo {video_name}", f"Video-specific metadata {video_name}"))

        specific_top_keys = {'video_observation'}
        event_entries = self._collect_event_entries(data)

        # Désactivation des signaux pour éviter de déclencher _on_meta_item_changed pendant le clear/remplissage
        self.common_tree.blockSignals(True)
        self.specific_tree.blockSignals(True)

        self.common_tree.clear()
        self.specific_tree.clear()
        self.event_tree.clear()

        for key, val in data.items():
            if key in specific_top_keys or key.startswith('events'):
                continue
            self._add_tree_entry(self.common_tree, [key], key, val)

        for key in specific_top_keys:
            if key in data:
                self._add_tree_entry(self.specific_tree, [key], key, data.get(key))

        if event_entries:
            for section_name, detail, tooltip in event_entries:
                self._add_event_tree_entry(self.event_tree, section_name, detail, tooltip)
        else:
            empty_item = QtWidgets.QTreeWidgetItem(["Aucun événement spécifique détecté.", ""])
            empty_item.setFlags(empty_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            self.event_tree.addTopLevelItem(empty_item)

        # Réactivation des signaux une fois l'arbre prêt
        self.common_tree.blockSignals(False)
        self.specific_tree.blockSignals(False)

        # Force le déploiement complet de toute l'arborescence (Noeuds et sous-noeuds)
        self.common_tree.expandAll()
        self.specific_tree.expandAll()
        self.event_tree.expandAll()

        # save timer
        if not hasattr(self, '_save_timer'):
            self._save_timer = QtCore.QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save_metadata_to_json)

    def _extract_display_value(self, v):
        if isinstance(v, dict):
            # try common pattern {'value': ...}
            if 'value' in v:
                return v.get('value')
            # otherwise stringify
            return json.dumps(v, ensure_ascii=False)
        return v

    def _get_description(self, v):
        if isinstance(v, dict):
            if 'description_fr' in v and v.get('description_fr'):
                return str(v.get('description_fr'))
            if 'description' in v and v.get('description'):
                return str(v.get('description'))
        return ""

    def _is_event_path(self, path: list):
        return any(str(p).startswith('events') for p in path)

    def _collect_event_entries(self, data, prefix=''):
        entries = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key.startswith('events'):
                    section_name = f"{prefix}{key}" if prefix else key
                    if isinstance(value, list):
                        for idx, item in enumerate(value, start=1):
                            if isinstance(item, dict) and isinstance(item.get('values'), list):
                                values = item.get('values')
                                if values:
                                    for item_idx, event_obj in enumerate(values, start=1):
                                        detail = self._format_event_detail(event_obj)
                                        tooltip = self._get_description(event_obj) or self._get_description(item)
                                        entries.append((section_name, detail, tooltip))
                                else:
                                    detail = "Aucun événement dans cette section"
                                    tooltip = self._get_description(item)
                                    entries.append((section_name, detail, tooltip))
                            else:
                                detail = self._format_event_detail(item)
                                tooltip = self._get_description(item)
                                entries.append((section_name, detail, tooltip))
                    else:
                        detail = self._format_event_detail(value)
                        tooltip = self._get_description(value)
                        entries.append((section_name, detail, tooltip))
                elif isinstance(value, (dict, list)):
                    nested_prefix = f"{prefix}{key}." if prefix else f"{key}."
                    entries.extend(self._collect_event_entries(value, nested_prefix))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    entries.extend(self._collect_event_entries(item, prefix))
        return entries

    def _format_event_item(self, section_name: str, item, item_idx=None):
        if isinstance(item, dict):
            parts = []
            if 'value' in item and item['value'] is not None:
                parts.append(str(item['value']))
            for field in ('time_code_start', 'time_code_end', 'frame_number_start', 'frame_number_end', 'description_fr'):
                if item.get(field) not in (None, ''):
                    parts.append(f"{field.replace('_', ' ')}={item[field]}")
            prefix = f"{section_name}#{item_idx}" if item_idx is not None else section_name
            return f"{prefix} : {' | '.join(parts)}" if parts else prefix
        return f"{section_name} : {self._extract_display_value(item)}"

    def _add_tree_entry(self, tree: QtWidgets.QTreeWidget, path: list, key: str, value):
        """Ajoute récursivement une entrée dans le QTreeWidget.
        `path` est la liste des clés menant à cette valeur (top-level key included).
        """
        if self._is_event_path(path):
            return

        description = self._get_description(value)
        # Éléments parents / Dossiers (ne doivent PAS être éditables)
        if isinstance(value, dict) and 'value' not in value:
            root = QtWidgets.QTreeWidgetItem([key, ""])
            root.setFlags((root.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable) | QtCore.Qt.ItemFlag.ItemIsEnabled)
            if description:
                root.setToolTip(0, description)
            tree.addTopLevelItem(root)
            # récursion pour les sous-clés
            for subk, subv in value.items():
                self._add_tree_child(root, path + [subk], subk, subv)
        else:
            # Valeurs simples ou structures {'value':...} -> MODIFIABLE
            display = self._extract_display_value(value)
            item = QtWidgets.QTreeWidgetItem([key, str(display)])
            
            # CORRECTION ICI : On active l'édition proprement
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsEditable)
            
            if description:
                item.setToolTip(0, description)
            # stockage du chemin
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, path)
            tree.addTopLevelItem(item)

    def _add_tree_child(self, parent_item: QtWidgets.QTreeWidgetItem, path: list, key: str, value):
        if self._is_event_path(path):
            return
        description = self._get_description(value)
        if isinstance(value, dict) and 'value' not in value:
            item = QtWidgets.QTreeWidgetItem([key, ""])
            item.setFlags((item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable) | QtCore.Qt.ItemFlag.ItemIsEnabled)
            if description:
                item.setToolTip(0, description)
            parent_item.addChild(item)
            for subk, subv in value.items():
                self._add_tree_child(item, path + [subk], subk, subv)
        else:
            display = self._extract_display_value(value)
            item = QtWidgets.QTreeWidgetItem([key, str(display)])
            
            # CORRECTION ICI : On active l'édition proprement
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsEditable)
            
            if description:
                item.setToolTip(0, description)
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, path)
            parent_item.addChild(item)

    def _add_event_tree_entry(self, tree: QtWidgets.QTreeWidget, category: str, detail: str, tooltip: str | None = None):
        item = QtWidgets.QTreeWidgetItem([category, detail])
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(0, tooltip)
            item.setToolTip(1, tooltip)
        tree.addTopLevelItem(item)

    def _format_event_detail(self, item):
        if not isinstance(item, dict):
            return str(item)
        parts = []
        if item.get('value') not in (None, ''):
            parts.append(str(item.get('value')))
        if item.get('time_code_start'):
            parts.append(f"de {item.get('time_code_start')}")
        if item.get('time_code_end'):
            parts.append(f"à {item.get('time_code_end')}")
        frame_start = item.get('frame_number_start')
        frame_end = item.get('frame_number_end')
        if frame_start is not None and frame_end is not None:
            parts.append(f"frame {frame_start}-{frame_end}")
        elif frame_start is not None:
            parts.append(f"frame {frame_start}")
        elif frame_end is not None:
            parts.append(f"frame fin {frame_end}")
        if item.get('description_fr'):
            parts.append(str(item.get('description_fr')))
        if parts:
            return ' | '.join(parts)
        return json.dumps(item, ensure_ascii=False)

    def _on_meta_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int):
        # SÉCURITÉ : On rejette immédiatement toute modification sur la colonne 0 (les clés)
        if column != 1:
            return
            
        # Récupération du chemin
        path = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not path:
            keys = []
            cur = item
            while cur is not None:
                keys.insert(0, cur.text(0))
                cur = cur.parent()
            path = keys
            
        # Met à jour la valeur dans le JSON en mémoire
        new_text = item.text(1)
        self._set_value_at_path(self._json_data, path, new_text)
        
        # Sauvegarde automatique avec le timer (debounce)
        if hasattr(self, '_save_timer'):
            self._save_timer.start(400)

    def _set_value_at_path(self, data: dict, path: list, new_text: str):
        # Navigate to parent of final key
        cur = data
        for p in path[:-1]:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                # create nested dict if missing
                cur[p] = {}
                cur = cur[p]
        last = path[-1]
        if not isinstance(cur, dict):
            return
        existing = cur.get(last)
        if isinstance(existing, dict) and 'value' in existing:
            coerced = self._coerce_type(new_text, existing.get('value'))
            existing['value'] = coerced
            cur[last] = existing
        else:
            # try to parse JSON literal
            try:
                parsed = json.loads(new_text)
                cur[last] = parsed
            except Exception:
                cur[last] = new_text

    def _format_event_label(self, key: str, value):
        if isinstance(value, dict) and 'value' not in value:
            subitems = []
            for sk, sv in value.items():
                subvalue = self._extract_display_value(sv)
                subitems.append(f"{sk}: {subvalue}")
            return f"{key} → {' | '.join(subitems)}"
        display = self._extract_display_value(value)
        return f"{key} : {display}"

    def _clear_layout(self, frame: QtWidgets.QFrame):
        if frame.layout() is None:
            # set an empty layout so subsequent calls work
            frame.setLayout(QtWidgets.QVBoxLayout())
        layout = frame.layout()
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def save_metadata_to_json(self):
        """Sauvegarde directement l'état de self._json_data mis à jour en temps réel par l'arbre."""
        if not hasattr(self, 'current_template_json') or not self.current_template_json:
            print("[METADONNEES] Aucun JSON chargé.")
            return
        try:
            with open(self.current_template_json, 'w', encoding='utf-8') as f:
                # On écrit directement l'objet mis à jour par l'arbre éditables
                json.dump(self._json_data, f, indent=4, ensure_ascii=False)
            print(f"[METADONNEES] JSON sauvegardé: {self.current_template_json}")
        except Exception as e:
            print(f"[METADONNEES] Erreur écriture JSON: {e}")

    def _on_tree_selection_changed(self, selected, deselected):
        # selection contains QModelIndex; retrieve first selected item's UserRole path
        try:
            indexes = selected.indexes()
            if not indexes:
                return
            idx = indexes[0]
            # Model expected to store full path in UserRole
            video_path = idx.data(QtCore.Qt.ItemDataRole.UserRole)
            if not video_path:
                return
            json_path = os.path.join(os.path.dirname(video_path), "template.json")
            self.bind_json_path(json_path)
        except Exception:
            return

    def _coerce_type(self, text: str, sample):
        # try to coerce to type of sample
        if sample is None:
            return text
        t = type(sample)
        if t is bool:
            lt = text.strip().lower()
            if lt in ('1','true','yes','oui'):
                return True
            return False
        try:
            if t is int:
                return int(text)
            if t is float:
                return float(text)
        except Exception:
            pass
        return text

    def injecter_donnes_systeme(self, data_systeme: dict):
        """Vide la frame et génère dynamiquement les lignes d'affichage avec un titre de section."""
        self.system_data_cache = data_systeme
        if not self.container_system_data or not hasattr(self, 'layout_grille'):
            return

        # 1. NETTOYAGE : On supprime les anciens widgets du layout
        while self.layout_grille.count() > 0:
            item = self.layout_grille.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # AJOUT DU TITRE DE LA SECTION SYSTEME (Prend toute la largeur)
        titre_section = QtWidgets.QLabel(self.translate("Données système", "System data"))
        titre_section.setStyleSheet("""
            font-size: 14px; 
            font-weight: bold; 
            color: #ffffff; 
            padding-bottom: 5px;
            border-bottom: 1px solid #444444;
        """)
        self.layout_grille.addRow(titre_section)
        # On ajoute un petit espace sous la ligne de séparation
        self.layout_grille.addItem(QtWidgets.QSpacerItem(0, 5))

        if not data_systeme:
            label_vide = QtWidgets.QLabel(self.translate("Aucune donnée système disponible", "No system data available"))
            label_vide.setStyleSheet("color: #bbbbbb; font-style: italic;")
            self.layout_grille.addRow(label_vide)
            return

        print(f"[METADONNEES] Extraction et génération dynamique de {len(data_systeme)} champs...")

        # Dictionnaire pour mapper les clés JSON vers de jolis intitulés en français
        if self.current_language == 'en':
            dictionnaire_noms = {
                "camera": "Onboard camera:",
                "model_mcu": "MCU board model:",
                "type_system": "System type:",
                "system_version": "Firmware version:",
            }
        else:
            dictionnaire_noms = {
                "camera": "Caméra embarquée :",
                "model_mcu": "Modèle carte (MCU) :",
                "type_system": "Type de système :",
                "system_version": "Version du Firmware :",
            }

        # 2. CRÉATION DYNAMIQUE DES LIGNES
        for cle, sous_dict in data_systeme.items():
            if isinstance(sous_dict, dict):
                valeur = sous_dict.get("value")
                if valeur is None or valeur == "":
                    valeur = sous_dict.get("example", "Inconnu")
            else:
                valeur = sous_dict
                
            valeur_str = str(valeur) if valeur is not None else "Inconnu"
            nom_affichage = dictionnaire_noms.get(cle, f"{cle.replace('_', ' ').capitalize()} :")
            
            label_titre = QtWidgets.QLabel(nom_affichage)
            label_titre.setStyleSheet("font-weight: bold; color: #aaaaaa; font-size: 12px;")
            
            champ_valeur = QtWidgets.QLineEdit(valeur_str)
            champ_valeur.setReadOnly(True) 
            champ_valeur.setStyleSheet("""
                QLineEdit {
                    background-color: #2b2b2b;
                    color: #00a2ff;
                    border: 1px solid #444444;
                    border-radius: 4px;
                    padding: 5px;
                    font-family: 'Consolas', 'Monospace';
                    font-size: 12px;
                }
            """)
            
            self.layout_grille.addRow(label_titre, champ_valeur)
            print(f"  -> Ligne ajoutée : {nom_affichage} -> Extraite : [{valeur_str}]")

        print("[METADONNEES] Fin de l'affichage des données système.")

    def injecter_donnees_meteo(self, data_meteo: dict):
        """Vide la frame météo et génère dynamiquement les lignes d'affichage avec un titre de section."""
        self.weather_data_cache = data_meteo
        if not self.container_weather_data or not hasattr(self, 'layout_grille_meteo'):
            return

        # 1. Nettoyage des anciens widgets
        while self.layout_grille_meteo.count() > 0:
            item = self.layout_grille_meteo.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # AJOUT DU TITRE DE LA SECTION METEO (Prend toute la largeur)
        titre_section = QtWidgets.QLabel(self.translate("Données météo", "Weather data"))
        titre_section.setStyleSheet("""
            font-size: 14px; 
            font-weight: bold; 
            color: #ffffff; 
            padding-bottom: 5px;
            border-bottom: 1px solid #444444;
        """)
        self.layout_grille_meteo.addRow(titre_section)
        # On ajoute un petit espace sous la ligne de séparation
        self.layout_grille_meteo.addItem(QtWidgets.QSpacerItem(0, 5))

        if not data_meteo:
            label_erreur = QtWidgets.QLabel(self.translate("Météo indisponible (Erreur de connexion)", "Weather unavailable (Connection error)"))
            label_erreur.setStyleSheet("color: #ff5555; font-style: italic;")
            self.layout_grille_meteo.addRow(label_erreur)
            return

        # Dictionnaire de traduction des clés de ton API Open-Meteo
        if self.current_language == 'en':
            dictionnaire_meteo = {
                "airTemp": "Air temperature:",
                "wind": "Wind strength (Beaufort):",
                "wind_direction": "Wind direction:",
                "weather": "Sky:",
                "seaState": "Sea state (Douglas):",
                "water_temperature": "Water temperature:",
                "swell_height": "Swell height:",
                "swell_direction": "Swell direction:",
            }
        else:
            dictionnaire_meteo = {
                "airTemp": "Température de l'air :",
                "wind": "Force du vent (Beaufort) :",
                "wind_direction": "Direction du vent :",
                "weather": "Ciel :",
                "seaState": "État de la mer (Douglas) :",
                "water_temperature": "Température de l'eau :",
                "swell_height": "Hauteur de la houle :",
                "swell_direction": "Direction de la houle :",
            }

        # 2. Génération dynamique
        for cle, valeur in data_meteo.items():
            nom_affichage = dictionnaire_meteo.get(cle, f"{cle} :")
            
            # Formatage des unités pour l'affichage visuel
            valeur_str = str(valeur)
            if cle == "airTemp" or cle == "water_temperature":
                valeur_str = f"{valeur} °C"
            elif cle == "wind":
                valeur_str = f"Force {valeur}"
            elif cle == "seaState":
                valeur_str = f"Mer {valeur}"

            label_titre = QtWidgets.QLabel(nom_affichage)
            label_titre.setStyleSheet("font-weight: bold; color: #aaaaaa; font-size: 12px;")
            
            champ_valeur = QtWidgets.QLineEdit(valeur_str)
            champ_valeur.setReadOnly(True)
            champ_valeur.setStyleSheet("""
                QLineEdit {
                    background-color: #2b2b2b;
                    color: #00ffaa; /* Vert émeraude distinctif */
                    border: 1px solid #444444;
                    border-radius: 4px;
                    padding: 5px;
                    font-family: 'Consolas', 'Monospace';
                    font-size: 12px;
        
                }
            """)
            
            self.layout_grille_meteo.addRow(label_titre, champ_valeur)