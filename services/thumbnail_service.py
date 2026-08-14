import os
import hashlib
import cv2
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6 import QtGui
from PyQt6.QtCore import pyqtSignal, QThread


def _thumb_cache_path(video_path: str) -> tuple[str, str]:
    """Retourne (cache_file_path, cache_dir) dans %APPDATA%/KOSMOS_IHM/thumbs/."""
    appdata = os.getenv("APPDATA") or os.path.expanduser("~")
    cache_dir = os.path.join(appdata, "KOSMOS_IHM", "thumbs")
    stem = os.path.splitext(os.path.basename(video_path))[0]
    path_hash = hashlib.md5(os.path.abspath(video_path).encode()).hexdigest()[:10]
    return os.path.join(cache_dir, f"{stem}_{path_hash}.jpg"), cache_dir


THUMB_W = 80
THUMB_H = 45   # ratio 16:9

_MAX_WORKERS = min(6, (os.cpu_count() or 2))


class ThumbnailWorker(QThread):
    """Extrait la frame du milieu de chaque vidéo et émet une QIcon par item de modèle."""

    thumbnail_ready = pyqtSignal(int, QtGui.QIcon)   # (row, icon)

    def __init__(self, items: list, parent=None):
        """items: liste de (row: int, video_path: str)"""
        super().__init__(parent)
        self._items = items

    def run(self):
        def _process(item):
            row, path = item
            return row, _make_thumbnail_icon(path)

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_process, it): it for it in self._items}
            for future in as_completed(futures):
                if self.isInterruptionRequested():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    row, icon = future.result()
                    if icon is not None:
                        self.thumbnail_ready.emit(row, icon)
                except Exception:
                    pass


class ThumbnailWorkerMulti(QThread):
    """Variante supportant plusieurs modèles : émet (model_key, row, icon)."""

    thumbnail_ready = pyqtSignal(str, int, QtGui.QIcon)   # (model_key, row, icon)

    def __init__(self, items: list, parent=None):
        """items: liste de (model_key: str, row: int, video_path: str)"""
        super().__init__(parent)
        self._items = items

    def run(self):
        def _process(item):
            model_key, row, path = item
            return model_key, row, _make_thumbnail_icon(path)

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_process, it): it for it in self._items}
            for future in as_completed(futures):
                if self.isInterruptionRequested():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    model_key, row, icon = future.result()
                    if icon is not None:
                        self.thumbnail_ready.emit(model_key, row, icon)
                except Exception:
                    pass


def _make_thumbnail_icon(path: str) -> QtGui.QIcon | None:
    """Extrait la frame du milieu de la vidéo (avec cache disque) et retourne une QIcon."""
    try:
        # ── Cache disque (%APPDATA%/KOSMOS_IHM/thumbs/) ─────────────────
        cache_path, cache_dir = _thumb_cache_path(path)

        if os.path.isfile(cache_path):
            # Invalide si le cache est plus ancien que la vidéo
            try:
                if os.path.getmtime(cache_path) >= os.path.getmtime(path):
                    img = cv2.imread(cache_path)
                    if img is not None:
                        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        h, w, c = rgb.shape
                        qimg = QtGui.QImage(
                            rgb.tobytes(), w, h, w * c,
                            QtGui.QImage.Format.Format_RGB888
                        )
                        return QtGui.QIcon(QtGui.QPixmap.fromImage(qimg))
            except OSError:
                pass

        # ── Extraction depuis la vidéo ───────────────────────────────
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

        # Enregistre dans le cache
        try:
            os.makedirs(cache_dir, exist_ok=True)
            cv2.imwrite(cache_path, thumb)
        except OSError:
            pass

        rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        h, w, c = rgb.shape
        qimg = QtGui.QImage(
            rgb.tobytes(), w, h, w * c,
            QtGui.QImage.Format.Format_RGB888
        )
        return QtGui.QIcon(QtGui.QPixmap.fromImage(qimg))
    except Exception:
        return None
