from PyQt6 import QtWidgets, uic, QtCore, QtGui
import sys
import os

# Importation de vos classes personnalisées
from page_accueil import AccueilPage
from page_qualif import QualifPage
from page_metadonnees import MetadonneesPage
from page_validation import ValidationPage
from page_evenements import EventsPage
from page_apropos import AProposPage

from utils2 import get_campaign_json_data
from api_wheather import WeatherWorker


class MyApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.qualification_terminee = False
        self.validation_terminee = False

        # 1. Chargement de l'interface
        self.base_path = os.path.dirname(__file__)
        ui_path = os.path.join(self.base_path, "ihm2.ui")
        uic.loadUi(ui_path, self)

        # Dictionnaire pour lier une page (widget) à son bouton de navigation dédié
        self.mapping_boutons = {}

        # 2. Configuration initiale de l'affichage
        self.stackedWidget.setCurrentIndex(0)

        # 3. Instanciation des contrôleurs de pages
        self.accueil_ctrl = AccueilPage(
            self.page_accueil,
            self.gerer_ouverture_campagne
        )
        self.qualif_ctrl = QualifPage(self.page_qualification)
        self.validation_ctrl = ValidationPage(self.page_validation, self.qualif_ctrl.video_model)
        self.evenements_ctrl = EventsPage(self.page_evenements, self.qualif_ctrl.video_model)
        self.metadonnees_ctrl = MetadonneesPage(
            self.page_metadonnees,
            self.qualif_ctrl.video_model,
            self.qualif_ctrl.trash_model
        )
        self.apropos_ctrl = AProposPage(self.page_apropos)
        self.page_controllers = [
            self.accueil_ctrl,
            self.qualif_ctrl,
            self.validation_ctrl,
            self.evenements_ctrl,
            self.metadonnees_ctrl,
            self.apropos_ctrl,
        ]
        
        # --- CONFIGURATION ET CENTRAGE DE LA TOOLBAR DE NAVIGATION ---
        self.nav_toolbar = self.findChild(QtWidgets.QToolBar, "page_tool_bar")
        
        if self.nav_toolbar:
            self.nav_toolbar.setMovable(False)
            self.nav_toolbar.setFloatable(False)
            
            # Récupération des actions définies graphiquement
            actions_existantes = self.nav_toolbar.actions()
            self.nav_toolbar.clear() # On vide la toolbar pour la réorganiser proprement
            
            # Création des deux ressorts invisibles (Spacers) pour le centrage
            spacer_gauche = QtWidgets.QWidget()
            spacer_gauche.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
            
            spacer_droite = QtWidgets.QWidget()
            spacer_droite.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
            
            # Création du sélecteur de langue à gauche
            langue_widget = QtWidgets.QWidget()
            langue_layout = QtWidgets.QHBoxLayout(langue_widget)
            langue_layout.setContentsMargins(0, 0, 0, 0)
            langue_layout.setSpacing(4)

            self.btn_lang_fr = QtWidgets.QToolButton()
            self.btn_lang_fr.setIcon(self._load_flag_icon("drapeau_fr.png"))
            self.btn_lang_fr.setToolTip("Français")
            self.btn_lang_fr.clicked.connect(lambda: self.set_language("fr"))
            self.btn_lang_fr.setCheckable(True)
            self.btn_lang_fr.setAutoExclusive(True)

            self.btn_lang_en = QtWidgets.QToolButton()
            self.btn_lang_en.setIcon(self._load_flag_icon("drpeau_en.png"))
            self.btn_lang_en.setToolTip("English")
            self.btn_lang_en.clicked.connect(lambda: self.set_language("en"))
            self.btn_lang_en.setCheckable(True)
            self.btn_lang_en.setAutoExclusive(True)
            self.btn_lang_fr.setIconSize(QtCore.QSize(24, 16))
            self.btn_lang_en.setIconSize(QtCore.QSize(24, 16))

            langue_layout.addWidget(self.btn_lang_fr)
            langue_layout.addWidget(self.btn_lang_en)
            
            # Création du conteneur central pour regrouper les boutons
            conteneur_boutons = QtWidgets.QWidget()
            layout_boutons = QtWidgets.QHBoxLayout(conteneur_boutons)
            layout_boutons.setContentsMargins(0, 0, 0, 0)
            layout_boutons.setSpacing(12) 
            
            # Conversion et injection des actions dans le conteneur
            # Réorganiser les actions pour mettre Métadonnées avant Événements
            # et ignorer le bouton Export
            actions_ordonnees = []
            for action in actions_existantes:
                # Ignorer le bouton Export
                if action.text().strip().lower() == "export":
                    continue
                elif action == self.actionEvenements:
                    # On saute Événements pour l'ajouter après Métadonnées
                    continue
                elif action == self.actionMetadonnees:
                    # On ajoute Métadonnées
                    actions_ordonnees.append(action)
                    # Puis immédiatement Événements après
                    actions_ordonnees.append(self.actionEvenements)
                else:
                    actions_ordonnees.append(action)
            
            for action in actions_ordonnees:
                bouton = QtWidgets.QToolButton()
                bouton.setDefaultAction(action)
                
                # Ajout d'une propriété dynamique par défaut
                bouton.setProperty("actif", False)
                layout_boutons.addWidget(bouton)
                
                # Association de l'action au bouton généré pour le retrouver plus tard
                action.setData(bouton)
            
            # Agencement final avec effet "vérin hydraulique"
            self.nav_toolbar.addWidget(langue_widget)
            self.nav_toolbar.addWidget(spacer_gauche)
            self.nav_toolbar.addWidget(conteneur_boutons)
            # Label to show current derusher name
            self.derusher_label = QtWidgets.QLabel("")
            self.derusher_label.setStyleSheet("color: #ffffff; font-weight: bold; padding-left:12px; padding-right:12px;")
            self.derusher_label.setMinimumWidth(200)
            self.derusher_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.nav_toolbar.addWidget(self.derusher_label)
            self.nav_toolbar.addWidget(spacer_droite)
            
            # Feuille de style CSS moderne incluant l'état de surdimensionnement [actif="true"]
            self.nav_toolbar.setStyleSheet("""
                QToolBar {
                    background-color: #20415d;
                    border-top: 1px solid #2778a2;
                    padding: 8px;
                }
                QToolButton {
                    background-color: #2778a2;
                    color: white;
                    font-weight: bold;
                    border-radius: 4px;
                    padding: 6px 15px;
                    font-size: 12px;
                }
                QToolButton:hover {
                    background-color: #00a2ff;
                }
                /* Style du bouton actif : texte plus grand, arrière-plan distinct et padding élargi */
                QToolButton[actif="true"] {
                    background-color: #00a2ff;
                    font-size: 14px;
                    padding: 10px 22px;
                    border: 1px solid #ffffff;
                }
                QToolButton#lang_fr, QToolButton#lang_en {
                    background-color: transparent;
                    border: none;
                    font-size: 20px;
                    padding: 0 6px;
                }
                QToolButton#lang_fr:checked, QToolButton#lang_en:checked {
                    background-color: #ffffff;
                    color: #20415d;
                    border-radius: 6px;
                }
            """)
            self.translations = {
                'fr': {
                    'Accueil': 'Accueil',
                    'Qualification': 'Qualification',
                    'Validation': 'Validation',
                    'Événements': 'Événements',
                    'Métadonnées': 'Métadonnées',
                    'À propos': 'À propos',
                    'Finir qualification': 'Finir qualification',
                    'Finir validation': 'Finir validation',
                    'Qualification Terminée ✓': 'Qualification Terminée ✓',
                    'Validation Terminée ✓': 'Validation Terminée ✓',
                    'derusher_active': '{} est en train de derusher',
                    'Required field': 'Champ requis',
                    'You must enter a name to continue.': 'Vous devez obligatoirement saisir un nom pour continuer.',
                },
                'en': {
                    'Accueil': 'Home',
                    'Qualification': 'Qualification',
                    'Validation': 'Validation',
                    'Événements': 'Events',
                    'Métadonnées': 'Metadata',
                    'À propos': 'About',
                    'Finir qualification': 'Finish qualification',
                    'Finir validation': 'Finish validation',
                    'Qualification Terminée ✓': 'Qualification completed ✓',
                    'Validation Terminée ✓': 'Validation completed ✓',
                    'derusher_active': '{} is currently derushing',
                    'Required field': 'Required field',
                    'You must enter a name to continue.': 'You must enter a name to continue.',
                }
            }
            self.current_language = 'fr'
            self.btn_lang_fr.setObjectName('lang_fr')
            self.btn_lang_en.setObjectName('lang_en')
            self.btn_lang_fr.setChecked(True)
            self._update_language()
        
        # 5. Connexions des signaux
        self.actionAcceuil.triggered.connect(lambda: self.changer_page(self.page_accueil))
        self.actionQualification.triggered.connect(lambda: self.changer_page(self.page_qualification))
        self.actionValidation.triggered.connect(lambda: self.changer_page(self.page_validation))
        self.actionEvenements.triggered.connect(lambda: self.changer_page(self.page_evenements))
        self.actionMetadonnees.triggered.connect(lambda: self.changer_page(self.page_metadonnees))
        

        self.actionA_propos.triggered.connect(lambda: self.changer_page(self.page_apropos))


        self.btn_finir_qualif = self.findChild(QtWidgets.QPushButton, "btn_finir_qualif")
        if self.btn_finir_qualif:
            self.btn_finir_qualif.clicked.connect(self.terminer_qualification)

        self.btn_finir_validation = self.findChild(QtWidgets.QPushButton, "btn_finir_validation")
        if self.btn_finir_validation:
            self.btn_finir_validation.clicked.connect(self.terminer_validation)

        # Remplissage du dictionnaire de correspondance (Page <-> Action)
        self.mapping_boutons = {
            self.page_accueil: self.actionAcceuil,
            self.page_qualification: self.actionQualification,
            self.page_validation: self.actionValidation,
            self.page_evenements: self.actionEvenements,
            self.page_metadonnees: self.actionMetadonnees,
            self.page_apropos: self.actionA_propos
        }

        self.verrouiller_navigation(True)
        # Définition de la page active au démarrage
        self.changer_page(self.page_accueil)

    def _load_flag_icon(self, filename: str) -> QtGui.QIcon:
        path = os.path.join(self.base_path, "img", filename)
        if os.path.exists(path):
            return QtGui.QIcon(path)
        return QtGui.QIcon()

    def set_language(self, langue: str):
        if langue not in self.translations:
            return
        self.current_language = langue
        self.btn_lang_fr.setChecked(langue == 'fr')
        self.btn_lang_en.setChecked(langue == 'en')
        self._update_language()

    def _update_language(self):
        translations = self.translations.get(self.current_language, {})
        if hasattr(self, 'actionAcceuil'):
            self.actionAcceuil.setText(translations.get('Accueil', self.actionAcceuil.text()))
        if hasattr(self, 'actionQualification'):
            self.actionQualification.setText(translations.get('Qualification', self.actionQualification.text()))
        if hasattr(self, 'actionValidation'):
            self.actionValidation.setText(translations.get('Validation', self.actionValidation.text()))
        if hasattr(self, 'actionEvenements'):
            self.actionEvenements.setText(translations.get('Événements', self.actionEvenements.text()))
        if hasattr(self, 'actionMetadonnees'):
            self.actionMetadonnees.setText(translations.get('Métadonnées', self.actionMetadonnees.text()))
        if hasattr(self, 'actionA_propos'):
            self.actionA_propos.setText(translations.get('À propos', self.actionA_propos.text()))
        if hasattr(self, 'btn_finir_qualif') and self.btn_finir_qualif:
            self.btn_finir_qualif.setText(translations.get('Finir qualification', self.btn_finir_qualif.text()))
        if hasattr(self, 'btn_finir_validation') and self.btn_finir_validation:
            self.btn_finir_validation.setText(translations.get('Finir validation', self.btn_finir_validation.text()))
        for page_ctrl in getattr(self, 'page_controllers', []):
            if hasattr(page_ctrl, 'set_language'):
                page_ctrl.set_language(self.current_language)
        for page_ctrl in getattr(self, 'page_controllers', []):
            if hasattr(page_ctrl, 'set_language'):
                page_ctrl.set_language(self.current_language)

    def gerer_ouverture_campagne(self, nom_derusher):
        # 1. RESET : Si on ouvre une NOUVELLE campagne, on réinitialise l'état bloqué
        self.qualification_terminee = False
        self.validation_terminee = False

        if hasattr(self, 'btn_finir_qualif') and self.btn_finir_qualif:
            self.btn_finir_qualif.setEnabled(True)
            self.btn_finir_qualif.setText("Finir qualification")
            
        if hasattr(self, 'btn_finir_validation') and self.btn_finir_validation:
            self.btn_finir_validation.setEnabled(True)
            self.btn_finir_validation.setText("Finir validation")

        # 2. Page qualif charge ses données métier (Vidéos, GPS, etc.)
        self.qualif_ctrl.ouvrir_explorateur_systeme(nom_derusher)
        
        # 3. On récupère le chemin brut du dossier stocké par page_qualif
        dossier = getattr(self.qualif_ctrl, 'dossier_campagne_actuel', None)
        print(f"[DEBUG MAIN] Dossier récupéré : {dossier}")
        
        if dossier:
            # 4. Extraction de la donnée système (filtrée) pour ton affichage d'IHM actuel
            data_systeme = get_campaign_json_data(dossier, extract_system=True)
            
            # Extraction du JSON complet pour avoir accès à tout (Météo, GPS, etc.)
            data_complete = get_campaign_json_data(dossier, extract_system=False)
            
            if data_systeme:
                # 5. DÉVERROUILLAGE PARTIEL : Active l'accueil, la qualif et les métadonnées
              
              
                self.verrouiller_navigation(False)

                # 6. Envoi direct à l'affichage des métadonnées système
                self.metadonnees_ctrl.injecter_donnes_systeme(data_systeme)
                
                # 7. Extraction des coordonnées GPS depuis le JSON complet pour l'API Météo
                try:
                    lat = None
                    lon = None
                    
                    if data_complete and "video_observation" in data_complete:
                        block = data_complete["video_observation"]
                        lat = block.get("latitude", {}).get("value")
                        lon = block.get("longitude", {}).get("value")
                    
                    # Lancement du thread si les coordonnées sont présentes
                    if lat is not None and lon is not None:
                        print(f"[METEO] Coordonnées lues avec succès -> Lat: {lat}, Lon: {lon}. Lancement de l'API...")
                        self.weather_thread = WeatherWorker(lat, lon)
                        self.weather_thread.meteo_recuperee.connect(self.metadonnees_ctrl.injecter_donnees_meteo)
                        self.weather_thread.start()
                    else:
                        print("[METEO] Attention : Coordonnées 'latitude'/'longitude' absentes du fichier JSON.")
                        self.metadonnees_ctrl.injecter_donnees_meteo({})
                        
                except Exception as e:
                    print(f"[METEO] Erreur lors du traitement des données météo : {e}")
                    self.metadonnees_ctrl.injecter_donnees_meteo({})
                
                # 8. Redirection automatique vers l'écran de qualification
                self.changer_page(self.page_qualification)
                # 9. Affichage du nom du derusher dans la toolbar
                try:
                    if hasattr(self, 'derusher_label') and nom_derusher:
                        self.derusher_label.setText(self.translations[self.current_language].get('derusher_active', '{} est en train de derusher').format(nom_derusher))
                except Exception:
                    pass
            else:
                print("[DEBUG MAIN] Blocage : data_systeme est vide ou False !")
                self.verrouiller_navigation(True)


    def terminer_qualification(self):
        """Action déclenchée par le bouton 'Finir qualification'."""
        self.qualification_terminee = True
        print("[CAMPAGNE] Qualification validée ! Ouverture des modules de validation et d'export.")
        
        # On active les pages de l'étape suivante
        self.actionValidation.setEnabled(True)
        self.actionEvenements.setEnabled(True)
        
        # Optionnel : masquer ou désactiver le bouton pour montrer que c'est fait
        if self.btn_finir_qualif:
            self.btn_finir_qualif.setEnabled(False)
            self.btn_finir_qualif.setText(self.translations[self.current_language].get('Qualification Terminée ✓', 'Qualification Terminée ✓'))
            
        # Redirection automatique vers la page de Validation pour fluidifier l'expérience
        self.changer_page(self.page_validation)

    def terminer_validation(self):
        """Action déclenchée par le bouton 'Finir validation'."""
        self.validation_terminee = True
        print("[CAMPAGNE] Validation validée ! Ouverture des modules Événements et Export.")
        
        # On débloque enfin les étapes finales
        self.actionEvenements.setEnabled(True)
        
        if self.btn_finir_validation:
            self.btn_finir_validation.setEnabled(False)
            self.btn_finir_validation.setText(self.translations[self.current_language].get('Validation Terminée ✓', 'Validation Terminée ✓'))
            
        # Redirection automatique vers la page Métadonnées
        self.changer_page(self.page_metadonnees)

    def verrouiller_navigation(self, verrouiller: bool):
        """Gère le verrouillage dynamique des étapes de la campagne."""
        # Étape 1 : Accès à la qualification et métadonnées dès qu'une campagne est ouverte
        self.actionQualification.setEnabled(not verrouiller)
        self.actionMetadonnees.setEnabled(not verrouiller)
        
        if verrouiller:
            self.actionValidation.setEnabled(False)
            self.actionEvenements.setEnabled(False)
        else:
            # L'accès à la Validation dépend de la fin de la Qualification
            self.actionValidation.setEnabled(self.qualification_terminee)
            
            # L'accès aux Événements et à l'Export dépend désormais de la fin de la Validation
            self.actionEvenements.setEnabled(self.qualification_terminee and self.validation_terminee)

    def changer_page(self, page):
        # --- SÉCURITÉ STRICTE SUR LES ÉTAPES ---
        # Cas 1 : Aucune campagne ouverte
        if page != self.page_accueil and page != self.page_apropos and not self.actionQualification.isEnabled():
            print("[SECURITE] Accès refusé : aucune campagne n'est ouverte.")
            return
            
        # Cas 2 : Qualification non validée -> Bloque tout le reste
        pages_apres_qualif = [self.page_validation, self.page_evenements]
        if page in pages_apres_qualif and not self.qualification_terminee:
            print("[SECURITE] Accès refusé : vous devez d'abord cliquer sur 'Finir qualification'.")
            return

        # Cas 3 : Validation non cliquée -> Bloque Événements et Export
        pages_apres_validation = [self.page_evenements]
        if page in pages_apres_validation and not self.validation_terminee:
            print("[SECURITE] Accès refusé : vous devez d'abord cliquer sur 'Finir validation'.")
            return

        # 1. Changement de l'index du stackedWidget
        self.stackedWidget.setCurrentWidget(page)
        
        # 2. Gestion du focus de la toolbar
        if self.nav_toolbar:
            self.nav_toolbar.clearFocus()

        # 3. Rafraîchissement spécifique si page métadonnées
        if page == self.page_metadonnees and hasattr(self, 'metadonnees_ctrl'):
            self.metadonnees_ctrl.rafraichir_statistiques()
            
        # 4. MISE À JOUR DYNAMIQUE DES BOUTONS
        for page_widget, action in self.mapping_boutons.items():
            bouton_associe = action.data()
            if bouton_associe:
                bouton_associe.setProperty("actif", (page_widget == page))
                bouton_associe.style().unpolish(bouton_associe)
                bouton_associe.style().polish(bouton_associe)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MyApp()
    window.show()
    sys.exit(app.exec())