import cv2
from PyQt6 import QtGui
from PyQt6.QtCore import pyqtSignal, QThread


THUMB_W = 80
THUMB_H = 45   # ratio 16:9


class ThumbnailWorker(QThread):
    """Extrait la frame du milieu de chaque vidéo et émet une QIcon par item de modèle."""

    thumbnail_ready = pyqtSignal(int, QtGui.QIcon)   # (row, icon)

    def __init__(self, items: list, parent=None):
        """items: liste de (row: int, video_path: str)"""
        super().__init__(parent)
        self._items = items

    def run(self):
        for row, path in self._items:
            if self.isInterruptionRequested():
                break
            icon = _make_thumbnail_icon(path)
            if icon is not None:
                self.thumbnail_ready.emit(row, icon)


class ThumbnailWorkerMulti(QThread):
    """Variante supportant plusieurs modèles : émet (model_key, row, icon)."""

    thumbnail_ready = pyqtSignal(str, int, QtGui.QIcon)   # (model_key, row, icon)

    def __init__(self, items: list, parent=None):
        """items: liste de (model_key: str, row: int, video_path: str)"""
        super().__init__(parent)
        self._items = items

    def run(self):
        for model_key, row, path in self._items:
            if self.isInterruptionRequested():
                break
            icon = _make_thumbnail_icon(path)
            if icon is not None:
                self.thumbnail_ready.emit(model_key, row, icon)


def _make_thumbnail_icon(path: str) -> QtGui.QIcon | None:
    """Extrait la frame du milieu de la vidéo et retourne une QIcon, ou None en cas d'échec."""
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return None
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(total // 2)))
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None
        thumb = cv2.resize(frame, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        h, w, c = rgb.shape
        qimg = QtGui.QImage(rgb.tobytes(), w, h, w * c, QtGui.QImage.Format.Format_RGB888)
        return QtGui.QIcon(QtGui.QPixmap.fromImage(qimg))
    except Exception:
        return None
