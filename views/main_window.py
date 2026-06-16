import os

from PyQt6 import QtWidgets, uic, QtCore, QtGui


class MainWindow(QtWidgets.QMainWindow):
    """Loads the .ui file and exposes all page widgets + navigation toolbar.

    No business logic lives here — that belongs in AppController.
    """

    def __init__(self):
        """Charge ihm2.ui, configure la toolbar de navigation et initialise les traductions."""
        super().__init__()
        self.base_path = os.path.dirname(os.path.dirname(__file__))
        ui_path = os.path.join(self.base_path, "ihm2.ui")
        uic.loadUi(ui_path, self)

        self.nav_toolbar = self.findChild(QtWidgets.QToolBar, "page_tool_bar")
        self.button_mapping: dict = {}

        self._setup_toolbar()

        self.translations = {
            'fr': {
                'Accueil': 'Accueil', 'Qualification': 'Qualification',
                'Validation': 'Validation', 'Événements': 'Événements',
                'Métadonnées': 'Métadonnées', 'À propos': 'À propos',
                'Finir qualification': 'Finir qualification',
                'Finir validation': 'Finir validation',
                'Qualification Terminée ✓': 'Qualification Terminée ✓',
                'Validation Terminée ✓': 'Validation Terminée ✓',
                'derusher_active': '{} est en train de derusher',
                'campaign_open': '📁 {}',
            },
            'en': {
                'Accueil': 'Home', 'Qualification': 'Qualification',
                'Validation': 'Validation', 'Événements': 'Events',
                'Métadonnées': 'Metadata', 'À propos': 'About',
                'Finir qualification': 'Finish qualification',
                'Finir validation': 'Finish validation',
                'Qualification Terminée ✓': 'Qualification completed ✓',
                'Validation Terminée ✓': 'Validation completed ✓',
                'derusher_active': '{} is currently derushing',
                'campaign_open': '📁 {}',
            },
        }
        self.current_language = 'fr'

    def _setup_toolbar(self):
        """Reconstruit la QToolBar avec les boutons de navigation, les drapeaux de langue et le label dérusher."""
        if not self.nav_toolbar:
            return
        self.nav_toolbar.setMovable(False)
        self.nav_toolbar.setFloatable(False)

        existing_actions = self.nav_toolbar.actions()
        self.nav_toolbar.clear()

        left_spacer = QtWidgets.QWidget()
        left_spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        right_spacer = QtWidgets.QWidget()
        right_spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)

        language_widget = QtWidgets.QWidget()
        language_layout = QtWidgets.QHBoxLayout(language_widget)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.setSpacing(4)

        self.btn_lang_fr = QtWidgets.QToolButton()
        self.btn_lang_fr.setIcon(self._load_flag_icon("drapeau_fr.png"))
        self.btn_lang_fr.setToolTip("Français")
        self.btn_lang_fr.setCheckable(True)
        self.btn_lang_fr.setAutoExclusive(True)
        self.btn_lang_fr.setObjectName('lang_fr')

        self.btn_lang_en = QtWidgets.QToolButton()
        self.btn_lang_en.setIcon(self._load_flag_icon("drpeau_en.png"))
        self.btn_lang_en.setToolTip("English")
        self.btn_lang_en.setCheckable(True)
        self.btn_lang_en.setAutoExclusive(True)
        self.btn_lang_en.setObjectName('lang_en')

        self.btn_lang_fr.setIconSize(QtCore.QSize(24, 16))
        self.btn_lang_en.setIconSize(QtCore.QSize(24, 16))
        language_layout.addWidget(self.btn_lang_fr)
        language_layout.addWidget(self.btn_lang_en)
        self.btn_lang_fr.setChecked(True)

        buttons_container = QtWidgets.QWidget()
        buttons_layout = QtWidgets.QHBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)

        ordered_actions = []
        for action in existing_actions:
            if action.text().strip().lower() == "export":
                continue
            elif action == self.actionEvenements:
                continue
            elif action == self.actionMetadonnees:
                ordered_actions.append(action)
                ordered_actions.append(self.actionEvenements)
            else:
                ordered_actions.append(action)

        for action in ordered_actions:
            button = QtWidgets.QToolButton()
            button.setDefaultAction(action)
            button.setProperty("actif", False)
            buttons_layout.addWidget(button)
            action.setData(button)

        self.derusher_label = QtWidgets.QLabel("")
        self.derusher_label.setStyleSheet(
            "color: #F2BFB4; font-weight: bold; font-family: 'Segoe UI', sans-serif;"
            " font-size: 11px; padding-left:12px; padding-right:12px; letter-spacing: 0.3px;"
        )
        self.derusher_label.setMinimumWidth(200)
        self.derusher_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.campaign_label = QtWidgets.QLabel("")
        self.campaign_label.setStyleSheet(
            "color: #7ec8e3; font-family: 'Segoe UI', sans-serif;"
            " font-size: 11px; padding-left:8px; padding-right:4px; letter-spacing: 0.3px;"
        )
        self.campaign_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.campaign_label.setMinimumWidth(0)

        self.campaign_mode_label = QtWidgets.QLabel("")
        self.campaign_mode_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.campaign_mode_label.setMinimumWidth(0)

        self.nav_toolbar.addWidget(language_widget)
        self.nav_toolbar.addWidget(left_spacer)
        self.nav_toolbar.addWidget(buttons_container)
        self.nav_toolbar.addWidget(self.derusher_label)
        self.nav_toolbar.addWidget(self.campaign_label)
        self._campaign_mode_action = self.nav_toolbar.addWidget(self.campaign_mode_label)
        self._campaign_mode_action.setVisible(False)
        self.nav_toolbar.addWidget(right_spacer)

        self.nav_toolbar.setStyleSheet("""
            QToolBar {
                background-color: #20415D;
                border-bottom: 2px solid #2778A2;
                padding: 6px 10px;
                spacing: 6px;
            }
            QToolButton {
                background-color: #1b3550;
                color: #F2BFB4;
                font-weight: bold;
                font-family: "Segoe UI Black", "Segoe UI", sans-serif;
                font-size: 11px;
                border: 1px solid #2a4a62;
                border-radius: 5px;
                padding: 6px 18px;
                letter-spacing: 0.5px;
            }
            QToolButton:hover {
                background-color: #2778A2;
                color: #ffffff;
                border-color: #2778A2;
            }
            QToolButton[actif="true"] {
                background-color: #2778A2;
                color: #ffffff;
                font-size: 12px;
                padding: 7px 22px;
                border: 1px solid #F2BFB4;
                border-radius: 5px;
            }
            QToolButton#lang_fr, QToolButton#lang_en {
                background-color: transparent;
                border: 1px solid transparent;
                padding: 2px 4px;
                border-radius: 4px;
            }
            QToolButton#lang_fr:hover, QToolButton#lang_en:hover {
                border-color: #2778A2;
            }
            QToolButton#lang_fr:checked, QToolButton#lang_en:checked {
                background-color: #F2BFB4;
                border: 1px solid #F2BFB4;
                border-radius: 4px;
            }
        """)

    def _load_flag_icon(self, filename: str) -> QtGui.QIcon:
        """Charge l'icône drapeau depuis img/filename, retourne une icône vide si absent."""
        path = os.path.join(self.base_path, "img", filename)
        if os.path.exists(path):
            return QtGui.QIcon(path)
        return QtGui.QIcon()

    def update_nav_highlight(self, page):
        """Surligne le bouton de navigation correspondant à la page active."""
        if self.nav_toolbar:
            self.nav_toolbar.clearFocus()
        for page_widget, action in self.button_mapping.items():
            btn = action.data()
            if btn:
                btn.setProperty("actif", (page_widget == page))
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    def update_language_buttons(self, language: str):
        """Met à jour l'état des boutons langue et traduit les textes des actions de navigation."""
        self.btn_lang_fr.setChecked(language == 'fr')
        self.btn_lang_en.setChecked(language == 'en')
        trans = self.translations.get(language, {})
        for attr, key in [
            ('actionAcceuil', 'Accueil'),
            ('actionQualification', 'Qualification'),
            ('actionValidation', 'Validation'),
            ('actionEvenements', 'Événements'),
            ('actionMetadonnees', 'Métadonnées'),
            ('actionA_propos', 'À propos'),
        ]:
            action = getattr(self, attr, None)
            if action:
                action.setText(trans.get(key, action.text()))
