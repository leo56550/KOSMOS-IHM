from PyQt6 import QtWidgets
from controllers.campagne_dialog import CampagneDialog


class AccueilController:
    """Contrôleur de la page Accueil — ouvre le dialog unifié de campagne."""

    def __init__(self, page_widget, open_campaign_callback):
        self.widget = page_widget
        self.open_campaign_callback = open_campaign_callback
        self.current_language = 'fr'
        self._last_campaign: str = ""
        self._last_working_dir: str = ""

        self.btn_open = self.widget.findChild(QtWidgets.QPushButton, "btn_ouvrir_campagne")
        if self.btn_open:
            self.btn_open.clicked.connect(self.open_campaign_dialog)

        self.set_language(self.current_language)

    # ── Language ────────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        self.current_language = language
        if self.btn_open:
            self.btn_open.setText(self.translate("Ouvrir campagne", "Open campaign"))

    # ── Dialog ──────────────────────────────────────────────────────────────

    def open_campaign_dialog(self):
        """Ouvre le dialog unifié (dérusher + dossier campagne + répertoire de travail)."""
        dlg = CampagneDialog(
            parent=self.widget,
            language=self.current_language,
            last_campaign=self._last_campaign,
            last_working_dir=self._last_working_dir,
        )
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        self._last_campaign = dlg.campaign_folder
        self._last_working_dir = dlg.working_dir
        self.open_campaign_callback(dlg.derusher_name, dlg.campaign_folder, dlg.working_dir)

    # ── Compat stubs (appelés depuis app_controller) ────────────────────────

    def show_working_dir_button(self):
        """Obsolète — conservé pour compatibilité."""

    def confirm_working_dir(self, path: str):
        """Obsolète — conservé pour compatibilité."""
