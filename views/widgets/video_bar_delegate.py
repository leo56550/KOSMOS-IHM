import os
import re
import json

from PyQt6 import QtWidgets, QtGui, QtCore

from services.campaign_service import resolve_video_json_path


class VideoBarDelegate(QtWidgets.QStyledItemDelegate):
    """Dessine une barre de complétion (rouge/orange/vert) à gauche de chaque item vidéo.

    Pour deux vidéos séquentielles (X.mp4 + X_01.mp4), la barre s'étend jusqu'au bord
    de la ligne afin de créer une continuité visuelle entre les deux rows.
    """

    BAR_W = 4
    BAR_X = 2   # décalage depuis le bord gauche du rect

    def __init__(self, parent=None):
        super().__init__(parent)
        self._working_dir = ""

    def set_working_dir(self, path: str):
        self._working_dir = path

    # ── Couleur de complétion ─────────────────────────────────────────────

    def _completion_color(self, video_path: str) -> QtGui.QColor:
        json_path = resolve_video_json_path(self._working_dir, str(video_path))
        if not os.path.exists(json_path):
            return QtGui.QColor("#D94F38")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return QtGui.QColor("#D94F38")

        def _filled(block: dict, key: str) -> bool:
            e = block.get(key, {})
            v = e.get("value") if isinstance(e, dict) else e
            return bool(v and str(v).strip() not in ("", "None", "null"))

        obs  = data.get("video_observation", {})
        surv = data.get("survey", {})
        if not all([_filled(obs, "codeObs"), _filled(obs, "exploitable")]):
            return QtGui.QColor("#D94F38")
        if sum([_filled(obs, "habitat"), _filled(obs, "depth"), _filled(surv, "date")]) < 2:
            return QtGui.QColor("#E8A838")
        return QtGui.QColor("#5DBB63")

    # ── Détection liaison séquentielle ────────────────────────────────────

    def _link_info(self, index: QtCore.QModelIndex):
        """Retourne (extend_top, extend_bottom) pour la barre de ce row."""
        model = index.model()
        row   = index.row()
        par   = index.parent()
        n     = model.rowCount(par)

        vp = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not vp:
            return False, False

        stem   = os.path.splitext(os.path.basename(str(vp)))[0]
        is_seg = bool(re.search(r"_\d+$", stem))

        ext_top = ext_bot = False

        if not is_seg and row + 1 < n:
            nxt = model.index(row + 1, 0, par).data(QtCore.Qt.ItemDataRole.UserRole)
            if nxt:
                ns = os.path.splitext(os.path.basename(str(nxt)))[0]
                ext_bot = bool(re.fullmatch(rf"{re.escape(stem)}_\d+", ns))

        if is_seg and row > 0:
            prv = model.index(row - 1, 0, par).data(QtCore.Qt.ItemDataRole.UserRole)
            if prv:
                ps = os.path.splitext(os.path.basename(str(prv)))[0]
                ext_top = bool(re.fullmatch(rf"{re.escape(ps)}_\d+", stem))

        return ext_top, ext_bot

    # ── Peinture ──────────────────────────────────────────────────────────

    def paint(self, painter: QtGui.QPainter,
              option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex):
        super().paint(painter, option, index)

        if index.column() != 0:
            return

        vp = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not vp:
            return

        color              = self._completion_color(str(vp))
        ext_top, ext_bot   = self._link_info(index)

        rect = option.rect
        ti   = 0 if ext_top else 3
        bi   = 0 if ext_bot else 3
        bar  = QtCore.QRectF(rect.left() + self.BAR_X,
                             rect.top()  + ti,
                             self.BAR_W,
                             rect.height() - ti - bi)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QBrush(color))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)

        if ext_top or ext_bot:
            # Bords plats du côté connecté, arrondis de l'autre côté
            path = QtGui.QPainterPath()
            x, y, w, h = bar.x(), bar.y(), bar.width(), bar.height()
            r = 2.0
            path.moveTo(x + (r if not ext_top else 0), y)
            path.lineTo(x + w - (r if not ext_top else 0), y)
            if not ext_top:
                path.arcTo(x + w - 2*r, y, 2*r, 2*r, 90, -90)
            else:
                path.lineTo(x + w, y)
            path.lineTo(x + w, y + h - (r if not ext_bot else 0))
            if not ext_bot:
                path.arcTo(x + w - 2*r, y + h - 2*r, 2*r, 2*r, 0, -90)
            else:
                path.lineTo(x + w, y + h)
            path.lineTo(x + (r if not ext_bot else 0), y + h)
            if not ext_bot:
                path.arcTo(x, y + h - 2*r, 2*r, 2*r, 270, -90)
            else:
                path.lineTo(x, y + h)
            path.lineTo(x, y + (r if not ext_top else 0))
            if not ext_top:
                path.arcTo(x, y, 2*r, 2*r, 180, -90)
            else:
                path.lineTo(x, y)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawRoundedRect(bar, 2, 2)

        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return QtCore.QSize(sh.width(), max(sh.height(), 40))
