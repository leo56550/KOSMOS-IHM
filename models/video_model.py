import os
from PyQt6 import QtGui, QtCore


class VideoItem(QtGui.QStandardItem):
    """Item représentant une vidéo dans le VideoModel."""

    def __init__(self, text: str, video_path: str):
        super().__init__(text)
        self.setData(video_path, QtCore.Qt.ItemDataRole.UserRole)
        self.setEditable(False)


class VideoModel(QtGui.QStandardItemModel):
    """Modèle de liste de vidéos d'une campagne.

    Colonnes : Nom | Durée | FPS | Résolution | Taille | Date
    """

    COLUMNS = ["Nom", "Durée", "FPS", "Résolution", "Taille", "Date"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)

    def populate(self, video_data: list):
        """Remplit le modèle depuis une liste de dicts retournés par video_service."""
        self.removeRows(0, self.rowCount())
        for info in video_data:
            name_item = VideoItem(info["name"], info["path"])
            row = [
                name_item,
                QtGui.QStandardItem(info.get("duration", "--")),
                QtGui.QStandardItem(info.get("fps", "--")),
                QtGui.QStandardItem(info.get("res", "--")),
                QtGui.QStandardItem(info.get("size", "--")),
                QtGui.QStandardItem(info.get("date", "--")),
            ]
            for item in row[1:]:
                item.setEditable(False)
            self.appendRow(row)

    def get_video_path(self, row: int) -> str:
        """Retourne le chemin vidéo associé à une ligne."""
        item = self.item(row, 0)
        if item:
            return item.data(QtCore.Qt.ItemDataRole.UserRole)
        return ""

    def find_row_by_path(self, video_path: str) -> int:
        """Retourne l'index de ligne pour un chemin donné, ou -1."""
        for row in range(self.rowCount()):
            if self.get_video_path(row) == video_path:
                return row
        return -1


class TrashModel(QtGui.QStandardItemModel):
    """Modèle de la corbeille (vidéos supprimées)."""

    COLUMNS = ["Nom", "Durée", "FPS", "Résolution", "Taille", "Date"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)

    def populate(self, video_data: list):
        """Remplit depuis une liste de dicts (même format que VideoModel)."""
        self.removeRows(0, self.rowCount())
        for info in video_data:
            name_item = VideoItem(info["name"], info["path"])
            row = [
                name_item,
                QtGui.QStandardItem(info.get("duration", "--")),
                QtGui.QStandardItem(info.get("fps", "--")),
                QtGui.QStandardItem(info.get("res", "--")),
                QtGui.QStandardItem(info.get("size", "--")),
                QtGui.QStandardItem(info.get("date", "--")),
            ]
            for item in row[1:]:
                item.setEditable(False)
            self.appendRow(row)

    def get_video_path(self, row: int) -> str:
        item = self.item(row, 0)
        if item:
            return item.data(QtCore.Qt.ItemDataRole.UserRole)
        return ""


class VideoFilterProxyModel(QtCore.QSortFilterProxyModel):
    """Proxy model qui filtre les vidéos dans les dossiers '.trash'
    et optionnellement les vidéos non exploitables.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_non_exploitable = False

    def set_filter_non_exploitable(self, enabled: bool):
        self._filter_non_exploitable = enabled
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True

        index = model.index(source_row, 0, source_parent)
        item = model.itemFromIndex(index)
        if item is None:
            return True

        video_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if video_path and ".trash" in str(video_path).replace("\\", "/"):
            return False

        if self._filter_non_exploitable:
            exploitable = item.data(QtCore.Qt.ItemDataRole.UserRole + 1)
            if exploitable is not None and exploitable == "Non exploitable":
                return False

        return True
