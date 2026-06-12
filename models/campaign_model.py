from PyQt6.QtCore import QObject, pyqtSignal


class CampaignModel(QObject):
    """Modèle de campagne : dossier actif et nom du dérusher.

    Émet campaign_changed quand la campagne est ouverte.
    """

    campaign_changed = pyqtSignal(str, str)  # (campaign_folder, derusher_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._campaign_folder: str = ""
        self._derusher_name: str = ""

    @property
    def campaign_folder(self) -> str:
        return self._campaign_folder

    @property
    def derusher_name(self) -> str:
        return self._derusher_name

    def open_campaign(self, folder: str, derusher_name: str):
        """Définit le dossier actif et le nom du dérusher, puis émet campaign_changed."""
        self._campaign_folder = folder
        self._derusher_name = derusher_name
        self.campaign_changed.emit(folder, derusher_name)

    def is_open(self) -> bool:
        return bool(self._campaign_folder)
