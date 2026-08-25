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

    _EXPLOITABLE_TEXT_COLORS = {
        "oui": "#4CAF50", "yes": "#4CAF50",
        "non": "#ff6060", "no": "#ff6060",
        "habitat": "#E8A838", "communication": "#E8A838",
        "?": "#aaaaaa",
    }

    def __init__(self, parent=None, highlight_short_light: bool = False):
        super().__init__(parent)
        self._working_dir = ""
        self.current_language = 'fr'
        self.show_point_number = False
        # Page Validation uniquement : affiche le statut d'exploitabilité de la vidéo
        # (oui/non/habitat/communication/?) en plus du numéro de point.
        self.show_exploitable_status = False
        # Page Validation uniquement : signale en rouge vif les vidéos courtes (<9 min)
        # et légères (<500 Mo), souvent révélatrices d'un problème d'acquisition.
        self.highlight_short_light = highlight_short_light
        # Désactivable sur les pages au panneau étroit (ex. Événements) où "Taille"
        # n'aurait de toute façon jamais la place de s'afficher utilement.
        self.show_size = True

    def set_working_dir(self, path: str):
        self._working_dir = path

    def set_language(self, language: str):
        self.current_language = language

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    # ── Couleur de complétion ─────────────────────────────────────────────

    def _get_video_status(self, video_path: str) -> tuple:
        """Retourne (couleur_barre, ardoise_manquante, exploitable_value).

        Couleur : rouge = rien, orange = ardoise/manquante, vert = ardoise + statut.
        ardoise_manquante : True si ardoise_missing a été explicitement signalée.
        exploitable_value : valeur brute de video_observation.exploitable ("" si absente).
        """
        json_path = resolve_video_json_path(self._working_dir, str(video_path))
        if not os.path.exists(json_path):
            return QtGui.QColor("#D94F38"), False, ""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return QtGui.QColor("#D94F38"), False, ""

        obs = data.get("video_observation", {})

        has_ardoise = bool((obs.get("timecode_ardoise") or {}).get("value"))
        ardoise_missing = bool((obs.get("ardoise_missing") or {}).get("value"))
        has_ardoise_effective = has_ardoise or ardoise_missing

        expl = obs.get("exploitable", {})
        expl_val = expl.get("value", "") if isinstance(expl, dict) else str(expl or "")
        expl_val = "" if str(expl_val).strip() in ("", "None", "null") else str(expl_val).strip()
        has_status = bool(expl_val and expl_val != "?")

        if has_ardoise_effective and has_status:
            color = QtGui.QColor("#5DBB63")
        elif has_ardoise_effective:
            color = QtGui.QColor("#E8A838")
        else:
            color = QtGui.QColor("#D94F38")

        return color, ardoise_missing, expl_val

    # ── Seuils durée/taille ──────────────────────────────────────────────

    @staticmethod
    def _parse_duration_minutes(text: str):
        """Convertit 'MM:SS' en minutes (float). None si non parsable."""
        try:
            mm, ss = text.strip().split(":")
            return int(mm) + int(ss) / 60.0
        except Exception:
            return None

    @staticmethod
    def _parse_size_mb(text: str):
        """Extrait la valeur numérique en MB depuis 'XXX.XX MB'. None si non parsable."""
        try:
            return float(text.strip().split()[0].replace(",", "."))
        except Exception:
            return None

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

        color, _, exploitable_value = self._get_video_status(str(vp))
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

        # Pas de point ambre séparé pour "ardoise manquante" : c'est une déclaration
        # volontaire et résolue (la barre de complétion orange/verte suffit déjà).

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
        size_idx = index.sibling(index.row(), 2)
        size_text = (size_idx.data(QtCore.Qt.ItemDataRole.DisplayRole) or "") if size_idx.isValid() else ""

        is_short_or_light = False
        if self.highlight_short_light:
            duration_min = self._parse_duration_minutes(duration)
            size_mb = self._parse_size_mb(size_text)
            is_short_or_light = (
                (duration_min is not None and duration_min < 9)
                or (size_mb is not None and size_mb < 500)
            )

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
        exploitable_label = ""
        if self.show_exploitable_status and exploitable_value:
            exploitable_label = exploitable_value.capitalize()

        # Sous-titre — moitié basse (heure + durée)
        sub_font = QtGui.QFont(painter.font())
        sub_font.setBold(False)
        sub_font.setPointSize(8)
        sub_rect = QtCore.QRect(text_left, rect.top() + half_h, text_w, half_h - 4)

        _NORMAL_COLOR = QtGui.QColor("#90b8d0")
        _WARNING_COLOR = QtGui.QColor("#FF3B30")  # rouge vif : vidéo courte (<9 min) ET légère (<500 Mo)

        segments = []
        if station_time:
            segments.append((self.translate(f"Heure : {station_time}", f"Time: {station_time}"), _NORMAL_COLOR))
        if duration:
            segments.append((self.translate(f"Durée : {duration}", f"Duration: {duration}"),
                              _WARNING_COLOR if is_short_or_light else _NORMAL_COLOR))
        if size_text and self.show_size:
            segments.append((self.translate(f"Taille : {size_text}", f"Size: {size_text}"),
                              _WARNING_COLOR if is_short_or_light else _NORMAL_COLOR))

        if segments:
            painter.setFont(sub_font)
            fm = QtGui.QFontMetrics(sub_font)
            gap = fm.horizontalAdvance("    ")
            x = sub_rect.left()
            right_edge = sub_rect.right()
            for seg_text, seg_color in segments:
                available = right_edge - x
                if available <= 6:
                    # Plus assez de place : on arrête plutôt que de laisser du texte
                    # invisible/tronqué en plein milieu (ex. "Durée : 19:" sans les secondes).
                    break
                display_text = seg_text
                if fm.horizontalAdvance(seg_text) > available:
                    display_text = fm.elidedText(seg_text, QtCore.Qt.TextElideMode.ElideRight, available)
                seg_rect = QtCore.QRect(x, sub_rect.top(), available, sub_rect.height())
                painter.setPen(seg_color)
                painter.drawText(
                    seg_rect,
                    QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                    display_text,
                )
                x += fm.horizontalAdvance(display_text) + gap
            info_w = (x - sub_rect.left()) + 12  # +12 d'espace avant le statut d'exploitabilité
        else:
            info_w = 0

        # Numéro de point + statut d'exploitabilité — plus grand, couleurs distinctes
        trailing = []
        if point_number:
            trailing.append((f"Pt {point_number}", QtGui.QColor("#f0a030")))
        if exploitable_label:
            excl_color = self._EXPLOITABLE_TEXT_COLORS.get(exploitable_value.lower(), "#f0a030")
            trailing.append((exploitable_label, QtGui.QColor(excl_color)))

        if trailing:
            trail_font = QtGui.QFont(painter.font())
            trail_font.setBold(True)
            trail_font.setPointSize(10)
            painter.setFont(trail_font)
            fm_trail = QtGui.QFontMetrics(trail_font)
            trail_gap = fm_trail.horizontalAdvance("   ")
            tx = text_left + info_w
            trail_right_edge = text_left + text_w
            for seg_text, seg_color in trailing:
                available = trail_right_edge - tx
                if available <= 6:
                    break
                display_text = seg_text
                if fm_trail.horizontalAdvance(seg_text) > available:
                    display_text = fm_trail.elidedText(seg_text, QtCore.Qt.TextElideMode.ElideRight, available)
                seg_rect = QtCore.QRect(tx, rect.top() + half_h, available, half_h - 4)
                painter.setPen(seg_color)
                painter.drawText(
                    seg_rect,
                    QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                    display_text,
                )
                tx += fm_trail.horizontalAdvance(display_text) + trail_gap
        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return QtCore.QSize(sh.width(), max(sh.height(), 52))
