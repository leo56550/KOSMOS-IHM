import os
import re
import json

from PyQt6 import QtWidgets, QtGui, QtCore

from services.campaign_service import resolve_video_json_path
from services.thumbnail_service import THUMB_W, THUMB_H


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
        self.show_point_number = False

    def set_working_dir(self, path: str):
        self._working_dir = path

    # ── Couleur de complétion ─────────────────────────────────────────────

    def _get_video_status(self, video_path: str) -> tuple:
        """Retourne (couleur_barre, ardoise_manquante).

        Couleur : rouge = rien, orange = ardoise/manquante, vert = ardoise + statut.
        ardoise_manquante : True si ardoise_missing a été explicitement signalée.
        """
        json_path = resolve_video_json_path(self._working_dir, str(video_path))
        if not os.path.exists(json_path):
            return QtGui.QColor("#D94F38"), False
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return QtGui.QColor("#D94F38"), False

        obs = data.get("video_observation", {})

        has_ardoise = bool((obs.get("timecode_ardoise") or {}).get("value"))
        ardoise_missing = bool((obs.get("ardoise_missing") or {}).get("value"))
        has_ardoise_effective = has_ardoise or ardoise_missing

        expl = obs.get("exploitable", {})
        expl_val = expl.get("value", "") if isinstance(expl, dict) else str(expl or "")
        has_status = bool(expl_val and str(expl_val).strip() not in ("", "None", "null", "?"))

        if has_ardoise_effective and has_status:
            color = QtGui.QColor("#5DBB63")
        elif has_ardoise_effective:
            color = QtGui.QColor("#E8A838")
        else:
            color = QtGui.QColor("#D94F38")

        return color, ardoise_missing

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

        if index.column() != 0:
            super().paint(painter, option, index)
            return

        # ── Fond / sélection ─────────────────────────────────────────────────
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QtGui.QIcon()
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(
            QtWidgets.QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget
        )

        vp = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not vp:
            return

        color, ardoise_missing = self._get_video_status(str(vp))
        ext_top, ext_bot = self._link_info(index)
        rect = option.rect

        # ── Barre de complétion ───────────────────────────────────────────────
        ti = 0 if ext_top else 3
        bi = 0 if ext_bot else 3
        bar = QtCore.QRectF(
            rect.left() + self.BAR_X, rect.top() + ti,
            self.BAR_W, rect.height() - ti - bi
        )
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QBrush(color))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        if ext_top or ext_bot:
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

        # ── Point amber (ardoise manquante) ───────────────────────────────────
        if ardoise_missing:
            painter.save()
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#E8A838")))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            dot_x = rect.left() + self.BAR_X + self.BAR_W + 2
            dot_y = rect.top() + (rect.height() - 5) // 2
            painter.drawEllipse(dot_x, dot_y, 5, 5)
            painter.restore()

        # ── Icône (miniature) ─────────────────────────────────────────────────
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        icon_left = rect.left() + self.BAR_X + self.BAR_W + 6
        icon_top  = rect.top() + (rect.height() - THUMB_H) // 2
        if icon and not icon.isNull():
            pix = icon.pixmap(THUMB_W, THUMB_H)
            painter.drawPixmap(icon_left, icon_top, THUMB_W, THUMB_H, pix)

        # ── Textes : nom (haut) + sous-titre (bas) ───────────────────────────
        text_left = icon_left + THUMB_W + 6
        text_w    = rect.right() - text_left - 4
        half_h    = rect.height() // 2

        name_text = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        station_time = index.data(QtCore.Qt.ItemDataRole.UserRole + 2) or ""
        if station_time == "99:99":
            station_time = ""
        dur_idx = index.sibling(index.row(), 1)
        duration = (dur_idx.data(QtCore.Qt.ItemDataRole.DisplayRole) or "") if dur_idx.isValid() else ""

        painter.save()
        # Nom — moitié haute
        name_font = QtGui.QFont(painter.font())
        name_font.setBold(True)
        name_font.setPointSize(9)
        painter.setFont(name_font)
        is_selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        painter.setPen(QtGui.QColor("#ffffff" if is_selected else "#d4e8f5"))
        name_rect = QtCore.QRect(text_left, rect.top() + 4, text_w, half_h - 4)
        painter.drawText(
            name_rect,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            name_text,
        )
        point_number = (index.data(QtCore.Qt.ItemDataRole.UserRole + 3) or "") if self.show_point_number else ""

        # Sous-titre — moitié basse (heure + durée)
        sub_font = QtGui.QFont(painter.font())
        sub_font.setBold(False)
        sub_font.setPointSize(8)
        sub_rect = QtCore.QRect(text_left, rect.top() + half_h, text_w, half_h - 4)
        if station_time or duration:
            parts = []
            if station_time:
                parts.append(f"Heure de prise : {station_time}")
            if duration:
                parts.append(f"Durée : {duration}")
            painter.setFont(sub_font)
            painter.setPen(QtGui.QColor("#90b8d0"))
            # Calcule la largeur du texte info pour positionner le numéro après
            info_text = "    ".join(parts)
            fm = QtGui.QFontMetrics(sub_font)
            info_w = fm.horizontalAdvance(info_text) + 12  # +12 d'espace
            painter.drawText(
                sub_rect,
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                info_text,
            )
        else:
            info_w = 0

        # Numéro de point — plus grand, couleur distincte
        if point_number:
            pt_font = QtGui.QFont(painter.font())
            pt_font.setBold(True)
            pt_font.setPointSize(10)
            painter.setFont(pt_font)
            painter.setPen(QtGui.QColor("#f0a030"))
            pt_rect = QtCore.QRect(
                text_left + info_w, rect.top() + half_h,
                text_w - info_w, half_h - 4
            )
            painter.drawText(
                pt_rect,
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                f"Pt {point_number}",
            )
        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return QtCore.QSize(sh.width(), max(sh.height(), 52))
