import os
import cv2
from PyQt6 import QtGui, QtCore


class SegmentModel(QtGui.QStandardItemModel):
    """Modèle des livrables de la page Extraction : segments vidéo et captures image."""

    COLUMNS = ["Nom", "Taille", "Type"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)

    def add_file(self, file_path: str):
        """Ajoute un fichier (vidéo ou image) avec sa miniature et ses métadonnées."""
        if not os.path.exists(file_path):
            print(f"[SegmentModel] Fichier introuvable : {file_path}")
            return

        self._clear_placeholder()

        file_name = os.path.basename(file_path)
        size_bytes = os.path.getsize(file_path)
        size_str = f"{size_bytes / (1024*1024):.2f} MB" if size_bytes > 1024*1024 else f"{size_bytes / 1024:.1f} KB"
        file_type = "Vidéo" if file_path.lower().endswith(('.mp4', '.avi')) else "Image"

        icon = self._make_icon(file_path, file_type)

        item_name = QtGui.QStandardItem(icon, file_name)
        item_name.setData(file_path, QtCore.Qt.ItemDataRole.UserRole)
        item_name.setEditable(False)

        row = [
            item_name,
            QtGui.QStandardItem(size_str),
            QtGui.QStandardItem(file_type),
        ]
        for item in row[1:]:
            item.setEditable(False)

        self.appendRow(row)

    def show_empty_message(self):
        """Affiche un message d'absence de livrables."""
        self.clear()
        self.setHorizontalHeaderLabels(self.COLUMNS)
        item = QtGui.QStandardItem("Aucun segment ou capture disponible")
        item.setEditable(False)
        item.setForeground(QtGui.QColor("gray"))
        self.appendRow([item, QtGui.QStandardItem(""), QtGui.QStandardItem("")])

    def _clear_placeholder(self):
        """Retire le message d'absence si présent."""
        if self.rowCount() > 0:
            first = self.item(0, 0)
            if first and "Aucun segment" in first.text():
                self.clear()
                self.setHorizontalHeaderLabels(self.COLUMNS)

    @staticmethod
    def _make_icon(file_path: str, file_type: str) -> QtGui.QIcon:
        try:
            if file_type == "Image":
                pixmap = QtGui.QPixmap(file_path).scaled(
                    64, 48,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation
                )
                return QtGui.QIcon(pixmap)
            else:
                cap = cv2.VideoCapture(file_path)
                ret, frame = cap.read()
                if ret:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    qimg = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format.Format_RGB888)
                    cap.release()
                    return QtGui.QIcon(QtGui.QPixmap.fromImage(qimg).scaled(64, 48))
                cap.release()
        except Exception as e:
            print(f"[SegmentModel] Erreur icône : {e}")
        return QtGui.QIcon()
